import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Banknote,
  Bell,
  Boxes,
  Brain,
  Building2,
  CheckCircle2,
  ChevronDown,
  Cloud,
  Copy,
  Cpu,
  Database,
  FileText,
  Gauge,
  Github,
  IndianRupee,
  Layers3,
  LineChart,
  Receipt,
  Search,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Terminal,
  PlugZap,
  LogOut,
  Users,
  Eye,
  EyeOff,
  KeyRound,
  WalletCards,
  Zap,
} from "lucide-react";
import "./styles.css";

type Dashboard = {
  metrics: Record<string, number>;
  customers: Array<Record<string, string | number>>;
  cloudProviders: Array<{ name: string; amount: number }>;
  aiProviders: Array<{ name: string; amount: number; tokens: number; requests: number }>;
  teamChargeback: Array<{ team: string; amount: number }>;
  kubernetes: Array<Record<string, string | number>>;
  networkUsage: Array<Record<string, string | number>>;
  aiUsage: Array<Record<string, string | number>>;
  invoices: Array<Record<string, string | number>>;
  alerts: Array<Record<string, string | number>>;
  recommendations: string[];
};

type Session = {
  user: {
    id: number;
    name: string;
    email: string;
    avatar: string;
    username?: string;
    hasPassword?: boolean;
    firstName?: string;
    lastName?: string;
    countryCode?: string;
    phoneNumber?: string;
    onboardingComplete?: boolean;
  };
  session: { role: string; plan: string };
  limits: Record<string, boolean | number>;
};

type GoogleCredentialResponse = {
  credential?: string;
  select_by?: string;
};

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
            ux_mode?: "popup" | "redirect";
            auto_select?: boolean;
            cancel_on_tap_outside?: boolean;
          }) => void;
          renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
          prompt: (momentListener?: (notification: { isNotDisplayed: () => boolean; isSkippedMoment: () => boolean; getNotDisplayedReason: () => string; getSkippedReason: () => string }) => void) => void;
          cancel: () => void;
        };
      };
    };
  }
}

type Onboarding = {
  steps: Array<{ title: string; body: string }>;
  prerequisites: string[];
  clusters: Array<{
    id: number;
    clusterName: string;
    provider: string;
    environment: string;
    status: string;
    agentMode: string;
    lastSeen: string;
    installCommand: string;
    verifyCommand: string;
  }>;
};

type ManagedUser = {
  id: number;
  name: string;
  email: string;
  avatar: string;
  role: string;
  provider: string;
  hostedDomain: string;
  firstLoginAt: string;
  lastLoginAt: string;
  sessions: number;
};

const fallback: Dashboard = {
  metrics: {
    total_spend_inr: 4245000,
    cloud_spend_inr: 1563000,
    kubernetes_spend_inr: 795000,
    ai_spend_inr: 1382000,
    invoice_total_inr: 4416200,
    forecast_total_inr: 4924200,
    tokens: 448300000,
    requests: 1463000,
    gpu_hours: 70.6,
    active_customers: 3,
  },
  customers: [],
  cloudProviders: [
    { name: "AWS", amount: 583000 },
    { name: "GCP", amount: 473000 },
    { name: "OCI", amount: 507000 },
  ],
  aiProviders: [
    { name: "OpenAI", amount: 621000, tokens: 209200000, requests: 882000 },
    { name: "Claude", amount: 203000, tokens: 63200000, requests: 187000 },
    { name: "Gemini", amount: 139000, tokens: 41500000, requests: 91000 },
    { name: "Mistral", amount: 301000, tokens: 95800000, requests: 231000 },
    { name: "Ollama", amount: 118000, tokens: 27600000, requests: 72000 },
  ],
  teamChargeback: [],
  kubernetes: [],
  networkUsage: [],
  aiUsage: [],
  invoices: [],
  alerts: [],
  recommendations: [],
};

const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8001";
const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";

function formatInr(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

function compact(value: number) {
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatBytesPerSec(value: number) {
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MiB/s`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KiB/s`;
  }
  return `${Math.round(value)} B/s`;
}

function Bar({ value, max }: { value: number; max: number }) {
  return <span className="bar"><span style={{ width: `${Math.max(8, (value / max) * 100)}%` }} /></span>;
}

function Stat({ icon: Icon, label, value, signal }: { icon: any; label: string; value: string; signal: string }) {
  return (
    <article className="stat">
      <div className="stat-icon"><Icon size={20} /></div>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <span>{signal}</span>
      </div>
    </article>
  );
}

function LoginGate({ onLogin }: { onLogin: (session: Session) => void }) {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const googleButtonRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!googleClientId) {
      setError("Google OAuth is not configured. Add VITE_GOOGLE_CLIENT_ID in frontend/.env and GOOGLE_CLIENT_ID in backend/.env.");
      return;
    }

    function initializeGoogle() {
      window.google?.accounts.id.initialize({
        client_id: googleClientId,
        ux_mode: "popup",
        auto_select: false,
        cancel_on_tap_outside: true,
        callback: (googleResponse) => {
          if (!googleResponse.credential) {
            setLoading(false);
            setError("Google did not return a login credential. Please try again.");
            return;
          }

          fetch(`${apiUrl}/api/auth/google`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ credential: googleResponse.credential, username, password }),
          })
            .then(async (res) => {
              if (!res.ok) {
                const body = await res.json().catch(() => ({ detail: "Google login failed" }));
                throw new Error(body.detail ?? "Google login failed");
              }
              return res.json();
            })
            .then(onLogin)
            .catch((err: Error) => setError(err.message))
            .finally(() => setLoading(false));
        },
      });
      if (googleButtonRef.current) {
        googleButtonRef.current.innerHTML = "";
        window.google?.accounts.id.renderButton(googleButtonRef.current, {
          theme: "outline",
          size: "large",
          type: "standard",
          shape: "rectangular",
          text: "signin_with",
          logo_alignment: "left",
          width: googleButtonRef.current.offsetWidth || 340,
        });
      }
      setReady(true);
      setError("");
    }

    const existing = document.querySelector<HTMLScriptElement>('script[src="https://accounts.google.com/gsi/client"]');
    const script = existing ?? document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = initializeGoogle;
    script.onerror = () => setError("Could not load Google sign-in. Check your network and try again.");

    if (!existing) {
      document.head.appendChild(script);
    } else if (window.google) {
      initializeGoogle();
    }
  }, [onLogin, password, username]);

  function signIn() {
    googleButtonRef.current?.querySelector<HTMLElement>('[role="button"]')?.click();
  }

  function passwordSignIn() {
    if (!username || !password) {
      setError("Enter your email and password.");
      return;
    }
    setError("");
    setLoading(true);
    fetch(`${apiUrl}/api/auth/login`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Login failed" }));
          throw new Error(body.detail ?? "Login failed");
        }
        return res.json();
      })
      .then(onLogin)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  function startProvider(provider: "github" | "sso") {
    window.location.href = `${apiUrl}/api/auth/${provider}/start`;
  }

  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="login-brand">
          <span><Cloud size={34} /></span>
          <strong>CloudMeter AI</strong>
        </div>
        <section className="login-product">
          <span className="eyebrow">Infra billing cockpit</span>
          <h1>Meter cloud, Kubernetes and AI usage without billing chaos.</h1>
          <div>
            <label><CheckCircle2 size={15} /> Read-only cluster onboarding</label>
            <label><CheckCircle2 size={15} /> AI token and GPU chargeback</label>
            <label><CheckCircle2 size={15} /> Multi-cloud invoice workflows</label>
          </div>
        </section>
        <aside className="login-box" onKeyDown={(event) => {
          if (event.key === "Enter") {
            passwordSignIn();
          }
        }}>
          <h2>Sign in</h2>
          <p>Welcome back to your CloudMeter AI workspace.</p>
          <div className="provider-grid">
            <button className="provider-button" type="button" onClick={() => startProvider("github")} disabled={loading}>
              <Github size={24} /> Github
            </button>
            <div className="google-native-slot" ref={googleButtonRef} />
            <button className="provider-button provider-wide" type="button" onClick={() => startProvider("sso")} disabled={loading}>
              <KeyRound size={24} /> SSO
            </button>
          </div>
          <div className="login-divider"><span>OR</span></div>
          <label>Email address</label>
          <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Enter your email" type="email" autoComplete="email" />
          <label>Password</label>
          <div className="password-field">
            <input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" type={showPassword ? "text" : "password"} autoComplete="current-password" />
            <button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((visible) => !visible)}>
              {showPassword ? <EyeOff size={21} /> : <Eye size={21} />}
            </button>
          </div>
          <div className="forgot-row">
            Forgot password? <button type="button" onClick={() => setError("Password reset will be available after email delivery is configured.")}>Reset</button>
          </div>
          <button className="password-button" type="button" onClick={passwordSignIn} disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
          {error && <p className="login-error">{error}</p>}
          <small>Don't have an account? <button type="button" onClick={signIn} disabled={loading || !ready || !googleClientId}>Sign up with Google</button></small>
        </aside>
      </section>
    </main>
  );
}

function SetupWizard({ session, onboarding, onUpdate }: { session: Session; onboarding: Onboarding | null; onUpdate: (session: Session) => void }) {
  const [step, setStep] = useState(session.user.firstName && session.user.lastName ? 1 : 0);
  const [firstName, setFirstName] = useState(session.user.firstName || session.user.name.split(" ")[0] || "");
  const [lastName, setLastName] = useState(session.user.lastName || session.user.name.split(" ").slice(1).join(" ") || "");
  const [countryCode, setCountryCode] = useState(session.user.countryCode || "+91");
  const [phoneNumber, setPhoneNumber] = useState(session.user.phoneNumber || "");
  const [clusterProvider, setClusterProvider] = useState("Any cloud / On-prem");
  const [clusterName, setClusterName] = useState("production-ai-cluster");
  const [generatedCluster, setGeneratedCluster] = useState<Onboarding["clusters"][number] | null>(null);
  const [cloudProvider, setCloudProvider] = useState("AWS");
  const [dbProvider, setDbProvider] = useState("PostgreSQL");
  const [copiedSetup, setCopiedSetup] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  const existingCluster = generatedCluster ?? onboarding?.clusters?.[0] ?? null;
  const steps = ["Profile", "Kubernetes", "Cloud", "Database"];
  const clusterProviders = ["Any cloud / On-prem"];
  const cloudProviders = [
    { name: "AWS", detail: "CUR, Cost Explorer, EKS, S3, EC2 and GPU billing." },
    { name: "GCP", detail: "BigQuery export, GKE, GPUs, storage and project labels." },
    { name: "OCI", detail: "Usage reports, OKE, compute, object storage and tags." },
    { name: "Azure", detail: "Cost Management exports, AKS, VMs and shared budgets." },
  ];
  const dbProviders = [
    { name: "PostgreSQL", command: "curl -fsSL https://cloudmeter.in/api/db/install.sh | CLOUDMETER_DB=postgres bash" },
    { name: "MySQL", command: "curl -fsSL https://cloudmeter.in/api/db/install.sh | CLOUDMETER_DB=mysql bash" },
    { name: "MongoDB", command: "curl -fsSL https://cloudmeter.in/api/db/install.sh | CLOUDMETER_DB=mongodb bash" },
    { name: "ClickHouse", command: "curl -fsSL https://cloudmeter.in/api/db/install.sh | CLOUDMETER_DB=clickhouse bash" },
    { name: "Redis", command: "curl -fsSL https://cloudmeter.in/api/db/install.sh | CLOUDMETER_DB=redis bash" },
    { name: "Oracle", command: "curl -fsSL https://cloudmeter.in/api/db/install.sh | CLOUDMETER_DB=oracle bash" },
  ];
  const selectedDb = dbProviders.find((provider) => provider.name === dbProvider) ?? dbProviders[0];

  function saveProfile() {
    setSaving(true);
    setMessage("");
    fetch(`${apiUrl}/api/auth/profile`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ first_name: firstName, last_name: lastName, country_code: countryCode, phone_number: phoneNumber }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not save profile" }));
          throw new Error(body.detail ?? "Could not save profile");
        }
        return res.json();
      })
      .then((updatedSession) => {
        onUpdate(updatedSession);
        setStep(1);
      })
      .catch((err: Error) => setMessage(err.message))
      .finally(() => setSaving(false));
  }

  function generateClusterScript() {
    setSaving(true);
    setMessage("");
    fetch(`${apiUrl}/api/onboarding/clusters`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customer_id: 1, cluster_name: clusterName, provider: clusterProvider, environment: "Kubernetes" }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not create cluster setup" }));
          throw new Error(body.detail ?? "Could not create cluster setup");
        }
        return res.json();
      })
      .then((cluster) => {
        setGeneratedCluster({ ...cluster, id: cluster.id, provider: "Any cloud / On-prem", environment: "Kubernetes", agentMode: "read-only", lastSeen: "Waiting for agent" });
        setMessage("Install script generated. Run it from a terminal with kubectl access.");
      })
      .catch((err: Error) => setMessage(err.message))
      .finally(() => setSaving(false));
  }

  function copySetup(value: string, key: string) {
    navigator.clipboard.writeText(value);
    setCopiedSetup(key);
    window.setTimeout(() => setCopiedSetup(""), 1800);
  }

  function completeSetup() {
    setSaving(true);
    setMessage("");
    fetch(`${apiUrl}/api/auth/onboarding/complete`, { method: "POST", credentials: "include" })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not finish setup" }));
          throw new Error(body.detail ?? "Could not finish setup");
        }
        return res.json();
      })
      .then(onUpdate)
      .catch((err: Error) => setMessage(err.message))
      .finally(() => setSaving(false));
  }

  return (
    <main className="setup-shell">
      <section className="setup-frame">
        <aside className="setup-side">
          <div className="brand setup-brand">
            <span><IndianRupee size={24} /></span>
            <div>
              <strong>CloudMeter AI</strong>
              <small>Workspace setup</small>
            </div>
          </div>
          {steps.map((item, index) => (
            <button key={item} className={step === index ? "active" : index < step ? "done" : ""} onClick={() => setStep(index)}>
              <span>{index < step ? <CheckCircle2 size={16} /> : index + 1}</span>
              {item}
            </button>
          ))}
          <div className="setup-side-card">
            <ShieldCheck size={20} />
            <strong>Read-only by default</strong>
            <p>Kubernetes, cloud and DB connectors are designed for billing visibility without write access.</p>
          </div>
        </aside>

        <section className="setup-main">
          <header className="setup-top">
            <div>
              <span className="eyebrow">Let's get started</span>
              <h1>{step === 0 ? "We need a few details to set up your account." : `Welcome, ${firstName || session.user.name}! Get started in 4 simple steps`}</h1>
            </div>
            <div className="setup-user">
              {session.user.avatar ? <img src={session.user.avatar} alt="" /> : <span>{session.user.email.slice(0, 2).toUpperCase()}</span>}
              <small>{session.user.email}</small>
            </div>
          </header>

          {step === 0 && (
            <section className="profile-card">
              <div className="profile-visual">
                <Sparkles size={22} />
                <strong>Personalize your CloudMeter workspace</strong>
                <p>Your name appears on reports, cluster invitations, approval trails and billing handoffs.</p>
              </div>
              <div className="profile-form">
                <label>First name</label>
                <input value={firstName} onChange={(event) => setFirstName(event.target.value)} placeholder="John" />
                <label>Last name</label>
                <input value={lastName} onChange={(event) => setLastName(event.target.value)} placeholder="Smith" />
                <label>Phone number <span>(optional)</span></label>
                <div className="phone-row">
                  <input value={countryCode} onChange={(event) => setCountryCode(event.target.value)} placeholder="+00" />
                  <input value={phoneNumber} onChange={(event) => setPhoneNumber(event.target.value)} placeholder="000 000 000" />
                </div>
                <button className="setup-primary" onClick={saveProfile} disabled={saving}>{saving ? "Saving..." : "Continue setup"}</button>
              </div>
            </section>
          )}

          {step === 1 && (
            <section className="connect-view">
              <div className="connect-head">
                <div><span className="step-dot">1</span><h2>Connect your Kubernetes cluster</h2><p>Use one generic agent for any cloud, on-prem, managed, or self-hosted Kubernetes.</p></div>
                <button className="ghost-button"><Terminal size={16} /> Terraform</button>
              </div>
              <div className="provider-options">
                {clusterProviders.map((provider) => (
                  <button key={provider} className={clusterProvider === provider ? "selected" : ""} onClick={() => setClusterProvider(provider)}>
                    <span /> <Boxes size={20} /> {provider}
                    <small>Works with EKS, GKE, AKS, OKE, OpenShift, bare metal and private clusters</small>
                  </button>
                ))}
              </div>
              <div className="script-panel">
                <label>Cluster name</label>
                <input value={clusterName} onChange={(event) => setClusterName(event.target.value)} />
                <button className="setup-primary" onClick={generateClusterScript} disabled={saving}>{saving ? "Generating..." : "Generate script"}</button>
                {existingCluster && (
                  <>
                    <code>{existingCluster.installCommand}</code>
                    <div className="cluster-actions">
                      <button onClick={() => copySetup(existingCluster.installCommand, "cluster")}>{copiedSetup === "cluster" ? "Copied" : "Copy install command"}</button>
                      <button onClick={() => copySetup(existingCluster.verifyCommand, "verify")}>{copiedSetup === "verify" ? "Copied" : "Copy verify command"}</button>
                    </div>
                  </>
                )}
              </div>
            </section>
          )}

          {step === 2 && (
            <section className="connect-view">
              <div className="connect-head">
                <div><span className="step-dot">2</span><h2>Connect cloud billing</h2><p>Bring cost exports, labels, projects and accounts into one chargeback ledger.</p></div>
                <button className="ghost-button"><Cloud size={16} /> Secure read-only access</button>
              </div>
              <div className="cloud-grid">
                {cloudProviders.map((provider) => (
                  <button key={provider.name} className={cloudProvider === provider.name ? "selected" : ""} onClick={() => setCloudProvider(provider.name)}>
                    <Cloud size={24} />
                    <strong>{provider.name}</strong>
                    <span>{provider.detail}</span>
                    <em>{cloudProvider === provider.name ? "Selected" : "Connect"}</em>
                  </button>
                ))}
              </div>
              <article className="permission-card">
                <PlugZap size={20} />
                <div><strong>{cloudProvider} setup package</strong><span>Creates least-privilege billing import, tag sync, anomaly detection and daily forecast jobs.</span></div>
              </article>
            </section>
          )}

          {step === 3 && (
            <section className="connect-view">
              <div className="connect-head">
                <div><span className="step-dot">3</span><h2>Connect database clusters</h2><p>Track database CPU, memory, storage, replicas, backup cost and customer chargeback.</p></div>
                <button className="ghost-button"><Database size={16} /> Agentless or agent mode</button>
              </div>
              <div className="db-grid">
                {dbProviders.map((provider) => (
                  <button key={provider.name} className={dbProvider === provider.name ? "selected" : ""} onClick={() => setDbProvider(provider.name)}>
                    <Database size={22} />
                    <strong>{provider.name}</strong>
                    <span>Query insights, storage trends, backup cost and forecast alerts.</span>
                  </button>
                ))}
              </div>
              <div className="script-panel">
                <strong>{selectedDb.name} collector command</strong>
                <code>{selectedDb.command}</code>
                <div className="cluster-actions">
                  <button onClick={() => copySetup(selectedDb.command, "db")}>{copiedSetup === "db" ? "Copied" : "Copy DB command"}</button>
                </div>
              </div>
            </section>
          )}

          {message && <p className="setup-message">{message}</p>}
          <footer className="setup-footer">
            <button className="ghost-button" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>Back</button>
            {step < 3 ? (
              <button className="setup-primary" onClick={() => (step === 0 ? saveProfile() : setStep(step + 1))} disabled={saving}>{step === 0 ? "Save and continue" : "Next"}</button>
            ) : (
              <button className="setup-primary" onClick={completeSetup} disabled={saving}>{saving ? "Finishing..." : "Open dashboard"}</button>
            )}
          </footer>
        </section>
      </section>
    </main>
  );
}

function App() {
  const [data, setData] = useState<Dashboard>(fallback);
  const [session, setSession] = useState<Session | null>(null);
  const [onboarding, setOnboarding] = useState<Onboarding | null>(null);
  const [activeView, setActiveView] = useState("Command");
  const [copied, setCopied] = useState("");
  const [authLoading, setAuthLoading] = useState(true);
  const [managedUsers, setManagedUsers] = useState<ManagedUser[]>([]);
  const [usersError, setUsersError] = useState("");
  const [usersMessage, setUsersMessage] = useState("");
  const [savingRoleUserId, setSavingRoleUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [passwordMessage, setPasswordMessage] = useState("");
  const [clusterRefreshMessage, setClusterRefreshMessage] = useState("");
  const [connectorClusterName, setConnectorClusterName] = useState("stage-cluster");
  const [generatedConnectorCluster, setGeneratedConnectorCluster] = useState<Onboarding["clusters"][number] | null>(null);
  const [verifiedConnectorCluster, setVerifiedConnectorCluster] = useState<Onboarding["clusters"][number] | null>(null);
  const [connectorSaving, setConnectorSaving] = useState(false);
  const [connectorVerifying, setConnectorVerifying] = useState(false);

  useEffect(() => {
    fetch(`${apiUrl}/api/auth/me`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((authSession) => {
        if (authSession) {
          setSession(authSession);
        }
      })
      .finally(() => setAuthLoading(false));
    fetch(`${apiUrl}/api/dashboard`)
      .then((res) => res.json())
      .then(setData)
      .catch(() => setData(fallback));
    fetch(`${apiUrl}/api/onboarding`)
      .then((res) => res.json())
      .then(setOnboarding)
      .catch(() => setOnboarding(null));
  }, []);

  const maxProvider = useMemo(() => Math.max(...data.cloudProviders.map((p) => p.amount), 1), [data.cloudProviders]);
  const maxAi = useMemo(() => Math.max(...data.aiProviders.map((p) => p.amount), 1), [data.aiProviders]);
  const maxTeam = useMemo(() => Math.max(...data.teamChargeback.map((p) => p.amount), 1), [data.teamChargeback]);
  const k8sRows = data.kubernetes;
  const aiRows = data.aiUsage.slice(0, 6);
  const isSuperadmin = session?.session.role === "superadmin";
  const limited = session?.session.role !== "admin" && !isSuperadmin;
  const connectorCluster = generatedConnectorCluster ?? onboarding?.clusters?.find((cluster) => cluster.clusterName === connectorClusterName) ?? null;
  const pageCopy: Record<string, { title: string; body: string; icon: any }> = {
    Command: {
      title: "Command center",
      body: "One place to watch cloud, Kubernetes, AI usage, forecasts and customer billing health.",
      icon: Gauge,
    },
    Cloud: {
      title: "Cloud cost ledger",
      body: "Connect AWS, GCP, OCI and Azure billing exports, normalize tags and allocate spend to teams or customers.",
      icon: Cloud,
    },
    Kubernetes: {
      title: "Kubernetes costing and chargeback",
      body: "Onboard clusters, track namespace and pod cost, then produce team-level chargeback without write access.",
      icon: Boxes,
    },
    "AI Metering": {
      title: "AI usage billing",
      body: "Meter OpenAI, Claude, Gemini, Mistral and Ollama by tokens, requests, documents, storage and GPU usage.",
      icon: Brain,
    },
    Invoices: {
      title: "Invoice generation",
      body: "Turn cloud, Kubernetes and AI usage into customer-ready invoices with transparent line items.",
      icon: Receipt,
    },
    Alerts: {
      title: "Budget alerts and recommendations",
      body: "Catch anomalies, budget overruns and optimization opportunities before month-end surprises.",
      icon: Bell,
    },
    "User Management": {
      title: "User management",
      body: "Superadmin-only workspace for users, roles, sessions and account visibility.",
      icon: Users,
    },
  };
  const ActiveIcon = pageCopy[activeView]?.icon ?? Gauge;

  function loadManagedUsers() {
    fetch(`${apiUrl}/api/users`, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not load users" }));
          throw new Error(body.detail ?? "Could not load users");
        }
        return res.json();
      })
      .then((body) => {
        setManagedUsers(body.users ?? []);
        setUsersError("");
      })
      .catch((err: Error) => setUsersError(err.message));
  }

  useEffect(() => {
    if (!isSuperadmin) {
      return;
    }
    loadManagedUsers();
  }, [isSuperadmin]);

  function copyCommand(value: string, label: string) {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(label);
      window.setTimeout(() => setCopied(""), 1800);
    });
  }

  function refreshClusterStatus(clusterName?: string) {
    fetch(`${apiUrl}/api/onboarding`)
      .then((res) => res.json())
      .then((freshOnboarding) => {
        setOnboarding(freshOnboarding);
        const cluster = freshOnboarding.clusters?.find((item: Onboarding["clusters"][number]) => item.clusterName === clusterName);
        if (cluster) {
          setClusterRefreshMessage(`${cluster.clusterName} is ${cluster.status}. Last seen ${cluster.lastSeen}.`);
        } else {
          setClusterRefreshMessage("Cluster status refreshed.");
        }
        window.setTimeout(() => setClusterRefreshMessage(""), 3500);
      })
      .catch(() => setClusterRefreshMessage("Could not refresh cluster status."));
  }

  function generateConnectorScript() {
    const cleanName = connectorClusterName.trim();
    if (!cleanName) {
      setClusterRefreshMessage("Enter a cluster name before generating the script.");
      return;
    }
    setConnectorSaving(true);
    setClusterRefreshMessage("");
    setVerifiedConnectorCluster(null);
    fetch(`${apiUrl}/api/onboarding/clusters`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customer_id: 1, cluster_name: cleanName, provider: "Any cloud / On-prem", environment: "Kubernetes" }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not generate cluster script" }));
          throw new Error(body.detail ?? "Could not generate cluster script");
        }
        return res.json();
      })
      .then((cluster) => {
        setGeneratedConnectorCluster(cluster);
        setOnboarding((current) => current ? { ...current, clusters: [cluster, ...current.clusters.filter((item) => item.id !== cluster.id)] } : current);
        setClusterRefreshMessage(`Script generated for ${cluster.clusterName}. Run it from your kubectl terminal, then verify status.`);
      })
      .catch((err: Error) => setClusterRefreshMessage(err.message))
      .finally(() => setConnectorSaving(false));
  }

  function verifyConnectorStatus() {
    if (!connectorCluster) {
      setClusterRefreshMessage("Generate a cluster script before verifying status.");
      return;
    }
    setConnectorVerifying(true);
    setClusterRefreshMessage("");
    fetch(`${apiUrl}/api/onboarding/clusters/${connectorCluster.id}/verify`, { method: "POST", credentials: "include" })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not verify cluster" }));
          throw new Error(body.detail ?? "Could not verify cluster");
        }
        return res.json();
      })
      .then((body) => {
        setGeneratedConnectorCluster(body.cluster);
        setOnboarding((current) => current ? { ...current, clusters: [body.cluster, ...current.clusters.filter((item) => item.id !== body.cluster.id)] } : current);
        if (body.verified) {
          setVerifiedConnectorCluster(body.cluster);
          fetch(`${apiUrl}/api/dashboard`).then((res) => res.json()).then(setData).catch(() => undefined);
        } else {
          setVerifiedConnectorCluster(null);
        }
        setClusterRefreshMessage(body.message);
      })
      .catch((err: Error) => setClusterRefreshMessage(err.message))
      .finally(() => setConnectorVerifying(false));
  }

  function logout() {
    fetch(`${apiUrl}/api/auth/logout`, { method: "POST", credentials: "include" })
      .finally(() => setSession(null));
  }

  function saveLocalPassword() {
    if (newPassword.length < 8) {
      setPasswordMessage("Password must be at least 8 characters.");
      return;
    }
    fetch(`${apiUrl}/api/auth/password`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: newPassword }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not save password" }));
          throw new Error(body.detail ?? "Could not save password");
        }
        return res.json();
      })
      .then((updatedSession) => {
        setSession(updatedSession);
        setNewPassword("");
        setPasswordMessage("Password saved. You can now login without Google.");
      })
      .catch((err: Error) => setPasswordMessage(err.message));
  }

  function updateManagedUserRole(user: ManagedUser, role: string) {
    setSavingRoleUserId(user.id);
    setUsersMessage("");
    setUsersError("");
    fetch(`${apiUrl}/api/users/${user.id}/role`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: "Could not update role" }));
          throw new Error(body.detail ?? "Could not update role");
        }
        return res.json();
      })
      .then((body) => {
        setManagedUsers((current) => current.map((item) => (item.id === user.id ? body.user : item)));
        setUsersMessage(`${body.user.email} is now ${body.user.role}.`);
        if (session?.user.id === user.id) {
          fetch(`${apiUrl}/api/auth/me`, { credentials: "include" })
            .then((res) => (res.ok ? res.json() : null))
            .then((updatedSession) => {
              if (updatedSession) {
                setSession(updatedSession);
              }
            });
        }
      })
      .catch((err: Error) => setUsersError(err.message))
      .finally(() => setSavingRoleUserId(null));
  }

  if (authLoading) {
    return (
      <main className="login-shell">
        <section className="login-loading">Loading CloudMeter workspace...</section>
      </main>
    );
  }

  if (!session) {
    return <LoginGate onLogin={setSession} />;
  }

  if (!session.user.onboardingComplete) {
    return <SetupWizard session={session} onboarding={onboarding} onUpdate={setSession} />;
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span><IndianRupee size={24} /></span>
          <div>
            <strong>CloudMeter AI</strong>
            <small>Usage Billing Platform</small>
          </div>
        </div>
        {["Command", "Cloud", "Kubernetes", "AI Metering", "Invoices", "Alerts", ...(isSuperadmin ? ["User Management"] : [])].map((item, index) => {
          const icons = [Gauge, Cloud, Boxes, Brain, Receipt, Bell, Users];
          const Icon = icons[index];
          return (
            <button key={item} className={activeView === item ? "active" : ""} onClick={() => setActiveView(item)}>
              <Icon size={18} /> {item}
            </button>
          );
        })}
        <div className="sidebar-card">
          <ShieldCheck size={20} />
          <strong>MSP ready</strong>
          <span>Multi-tenant chargeback, private AI, cloud resale, GST invoices.</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="search">
            <Search size={18} />
            <input placeholder="Search customer, namespace, model, invoice..." />
          </div>
          <button className="selector"><Building2 size={17} /> {limited ? "Limited workspace" : "All customers"} <ChevronDown size={16} /></button>
          <button className="primary" disabled={limited}><Sparkles size={17} /> Optimize plan</button>
          <button className="logout-button" onClick={logout}><LogOut size={17} /> Logout</button>
        </header>

        {limited && (
          <section className="access-strip">
            <ShieldCheck size={18} />
            <span>
              {isSuperadmin
                ? `${session.user.email} is the master superadmin account with full workspace and user-management access.`
                : `${session.user.email} is in limited mode: dashboard view, one cluster onboarding, read-only reports, no invoice sending.`}
            </span>
          </section>
        )}

        {!session.user.hasPassword && (
          <section className="password-link-panel">
            <div>
              <strong>Set local login password</strong>
              <span>Google is connected for {session.user.email}. Add a CloudMeter password to login later without opening Google.</span>
            </div>
            <input
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              type="password"
              placeholder="Minimum 8 characters"
            />
            <button onClick={saveLocalPassword}><KeyRound size={16} /> Save password</button>
            {passwordMessage && <small>{passwordMessage}</small>}
          </section>
        )}

        <section className="page-title">
          <div className="page-icon"><ActiveIcon size={24} /></div>
          <div>
            <span className="eyebrow">{activeView}</span>
            <h1>{pageCopy[activeView]?.title}</h1>
            <p>{pageCopy[activeView]?.body}</p>
          </div>
        </section>

        {activeView === "Command" && (
          <>
            <section className="hero">
              <div>
                <span className="eyebrow">Unified cloud, Kubernetes and AI usage billing</span>
                <h1>Stripe-style metering for complex infra spend.</h1>
                <p>
                  Track AWS, OCI, GCP, on-prem Kubernetes and AI providers, then generate transparent chargeback and invoices for every team or customer.
                </p>
              </div>
              <div className="hero-panel">
                <span>June forecast</span>
                <strong>{formatInr(data.metrics.forecast_total_inr)}</strong>
                <div className="forecast-grid">
                  <label><Cloud size={16} /> Cloud {formatInr(data.metrics.cloud_spend_inr)}</label>
                  <label><Boxes size={16} /> K8s {formatInr(data.metrics.kubernetes_spend_inr)}</label>
                  <label><Brain size={16} /> AI {formatInr(data.metrics.ai_spend_inr)}</label>
                </div>
              </div>
            </section>

            <section className="stats-grid">
              <Stat icon={WalletCards} label="Spend captured" value={formatInr(data.metrics.total_spend_inr)} signal="Cloud + K8s + AI" />
              <Stat icon={Brain} label="AI tokens billed" value={compact(data.metrics.tokens)} signal={`${compact(data.metrics.requests)} requests`} />
              <Stat icon={Cpu} label="GPU metered" value={`${data.metrics.gpu_hours} hrs`} signal="Ollama + workloads" />
              <Stat icon={FileText} label="Invoice value" value={formatInr(data.metrics.invoice_total_inr)} signal={`${data.metrics.active_customers} active customers`} />
            </section>

            <section className="grid two">
              <article className="panel recommendation">
                <div className="panel-head"><div><span>AI Recommendations</span><h2>Optimization playbook</h2></div><LineChart size={22} /></div>
                {data.recommendations.slice(0, 4).map((item) => (
                  <p key={item}><Activity size={16} /> {item}</p>
                ))}
              </article>
              <article className="panel">
                <div className="panel-head"><div><span>Budget Alerts</span><h2>Needs attention</h2></div><AlertTriangle size={22} /></div>
                <div className="alerts">
                  {data.alerts.slice(0, 3).map((alert) => (
                    <div className={`alert ${alert.severity}`} key={`${alert.owner}`}>
                      <strong>{alert.owner}</strong>
                      <span>{alert.message}</span>
                      <label>{formatInr(Number(alert.current))} of {formatInr(Number(alert.threshold))}</label>
                    </div>
                  ))}
                </div>
              </article>
            </section>
          </>
        )}

        {activeView === "Cloud" && (
          <>
            <section className="stats-grid">
              <Stat icon={Cloud} label="Cloud spend" value={formatInr(data.metrics.cloud_spend_inr)} signal="AWS + GCP + OCI" />
              <Stat icon={LineChart} label="Forecast" value={formatInr(data.metrics.forecast_total_inr)} signal="All providers" />
              <Stat icon={Building2} label="Customers" value={`${data.metrics.active_customers}`} signal="Active billing owners" />
              <Stat icon={ShieldCheck} label="Access mode" value="Read-only" signal="Billing export sync" />
            </section>
            <section className="grid two">
              <article className="panel">
                <div className="panel-head"><div><span>Provider Cost</span><h2>Multi-cloud ledger</h2></div><Cloud size={22} /></div>
                <div className="list">
                  {data.cloudProviders.map((item) => (
                    <div className="row" key={item.name}>
                      <span className={`badge ${item.name.toLowerCase()}`}>{item.name}</span>
                      <Bar value={item.amount} max={maxProvider} />
                      <strong>{formatInr(item.amount)}</strong>
                    </div>
                  ))}
                </div>
              </article>
              <article className="panel">
                <div className="panel-head"><div><span>Connect Cloud</span><h2>Billing integrations</h2></div><PlugZap size={22} /></div>
                <div className="feature-list">
                  {["AWS CUR + Cost Explorer", "GCP BigQuery billing export", "OCI usage reports", "Azure Cost Management"].map((item) => (
                    <label key={item}><CheckCircle2 size={16} /> {item}</label>
                  ))}
                </div>
              </article>
            </section>
          </>
        )}

        {activeView === "Kubernetes" && (
          <>
            <section className="onboarding-panel">
              <div className="onboarding-copy">
                <span className="eyebrow">Company onboarding</span>
                <h2>Connect Kubernetes with one read-only command.</h2>
                <p>
                  Invite a customer, generate one cloud-neutral command, then run it from any terminal or cloud shell with kubectl access.
                </p>
                <div className="prereqs">
                  {(onboarding?.prerequisites ?? ["kubectl access", "curl installed", "outbound HTTPS"]).map((item) => (
                    <label key={item}><CheckCircle2 size={16} /> {item}</label>
                  ))}
                </div>
                {clusterRefreshMessage && <p className="cluster-refresh-message">{clusterRefreshMessage}</p>}
              </div>
              <div className="cluster-stack">
                <article className="cluster-card">
                  <div>
                    <strong>Kubernetes connector</strong>
                    <span>Any cloud / On-prem · Kubernetes · read-only</span>
                  </div>
                  <em className={verifiedConnectorCluster ? "connected" : "pending"}>{verifiedConnectorCluster ? "connected" : "not verified"}</em>
                  <label>Cluster name</label>
                  <input value={connectorClusterName} onChange={(event) => setConnectorClusterName(event.target.value)} placeholder="stage-cluster" />
                  <p>{verifiedConnectorCluster ? `Verified cluster: ${verifiedConnectorCluster.clusterName}` : "Generate a tokenized script, run it from a terminal with kubectl access, then verify status here."}</p>
                  <div className="cluster-actions">
                    <button onClick={generateConnectorScript} disabled={connectorSaving}><Terminal size={16} /> {connectorSaving ? "Generating..." : "Generate script"}</button>
                    {connectorCluster && (
                      <>
                        <button onClick={() => copyCommand(connectorCluster.installCommand, connectorCluster.clusterName)}><Copy size={16} /> {copied === connectorCluster.clusterName ? "Copied" : "Copy install"}</button>
                        <button onClick={verifyConnectorStatus} disabled={connectorVerifying}><CheckCircle2 size={16} /> {connectorVerifying ? "Verifying..." : "Verify status"}</button>
                      </>
                    )}
                  </div>
                </article>
              </div>
            </section>
            <section className="grid main-grid">
              <article className="panel wide">
                <div className="panel-head"><div><span>Kubernetes Costing</span><h2>Namespace and pod-level chargeback</h2></div><ServerCog size={22} /></div>
                <table>
                  <thead><tr><th>Cluster</th><th>Namespace</th><th>Workload</th><th>CPU</th><th>Memory</th><th>Source</th><th>Cost</th></tr></thead>
                  <tbody>
                    {k8sRows.map((row) => (
                      <tr key={`${row.namespace}-${row.workload}`}>
                        <td>{row.cluster}</td><td>{row.namespace}</td><td>{row.workload}</td><td>{compact(Number(row.cpu))} cores</td><td>{compact(Number(row.memory))} GiB</td><td><span className={`source-pill ${String(row.source)}`}>{row.source}</span></td><td>{formatInr(Number(row.amount))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </article>
              <article className="panel">
                <div className="panel-head"><div><span>Chargeback</span><h2>Owners</h2></div><Banknote size={22} /></div>
                <div className="chargeback">
                  {data.teamChargeback.slice(0, 8).map((item) => (
                    <div key={item.team}>
                      <label>{item.team}<strong>{formatInr(item.amount)}</strong></label>
                      <Bar value={item.amount} max={maxTeam} />
                    </div>
                  ))}
                </div>
              </article>
            </section>
            <section className="panel user-management">
              <div className="panel-head"><div><span>Network Traffic</span><h2>Namespace RX/TX from Prometheus, Cilium, Istio, or inventory fallback</h2></div><Activity size={22} /></div>
              <table>
                <thead><tr><th>Cluster</th><th>Namespace</th><th>Workload</th><th>Ingress</th><th>Egress</th><th>Source</th><th>Observed</th></tr></thead>
                <tbody>
                  {(data.networkUsage ?? []).map((row) => (
                    <tr key={`${row.cluster}-${row.namespace}-${row.workload}`}>
                      <td>{row.cluster}</td>
                      <td>{row.namespace}</td>
                      <td>{row.workload}</td>
                      <td>{formatBytesPerSec(Number(row.rxBytesPerSec))}</td>
                      <td>{formatBytesPerSec(Number(row.txBytesPerSec))}</td>
                      <td><span className={`source-pill ${String(row.source)}`}>{row.source}</span></td>
                      <td>{row.observedAt ? new Date(String(row.observedAt)).toLocaleTimeString() : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </>
        )}

        {activeView === "AI Metering" && (
          <>
            <section className="stats-grid">
              <Stat icon={Brain} label="AI spend" value={formatInr(data.metrics.ai_spend_inr)} signal="All model providers" />
              <Stat icon={Zap} label="Requests" value={compact(data.metrics.requests)} signal="Metered API calls" />
              <Stat icon={Layers3} label="Tokens" value={compact(data.metrics.tokens)} signal="Input + output" />
              <Stat icon={Cpu} label="GPU" value={`${data.metrics.gpu_hours} hrs`} signal="Private AI workloads" />
            </section>
            <section className="grid main-grid">
              <article className="panel wide">
                <div className="panel-head"><div><span>AI Metering</span><h2>Tokens, requests, documents, storage and GPU</h2></div><Layers3 size={22} /></div>
                <table>
                  <thead><tr><th>Product</th><th>Provider</th><th>Model</th><th>Requests</th><th>Docs</th><th>Bill</th></tr></thead>
                  <tbody>
                    {aiRows.map((row) => (
                      <tr key={`${row.provider}-${row.model}-${row.product}`}>
                        <td>{row.product}</td><td>{row.provider}</td><td>{row.model}</td><td>{compact(Number(row.requests))}</td><td>{compact(Number(row.documents))}</td><td>{formatInr(Number(row.amount))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </article>
              <article className="panel">
                <div className="panel-head"><div><span>AI Usage Billing</span><h2>Models and dimensions</h2></div><Zap size={22} /></div>
                <div className="list">
                  {data.aiProviders.map((item) => (
                    <div className="row ai" key={item.name}>
                      <span className="badge ai-badge">{item.name}</span>
                      <Bar value={item.amount} max={maxAi} />
                      <strong>{formatInr(item.amount)}</strong>
                      <small>{compact(item.tokens)} tokens</small>
                    </div>
                  ))}
                </div>
              </article>
            </section>
          </>
        )}

        {activeView === "Invoices" && (
          <section className="grid main-grid">
            <article className="panel wide">
              <div className="panel-head"><div><span>Invoice Generation</span><h2>Customer-ready bills</h2></div><Receipt size={22} /></div>
              <div className="invoice-list">
                {data.invoices.map((invoice) => (
                  <div key={invoice.invoiceNo}>
                    <span>{invoice.invoiceNo}</span>
                    <strong>{formatInr(Number(invoice.total))}</strong>
                    <em>{invoice.status}</em>
                  </div>
                ))}
              </div>
            </article>
            <article className="panel">
              <div className="panel-head"><div><span>Chargeback</span><h2>Billable owners</h2></div><Banknote size={22} /></div>
              <div className="chargeback">
                {data.teamChargeback.slice(0, 8).map((item) => (
                  <div key={item.team}>
                    <label>{item.team}<strong>{formatInr(item.amount)}</strong></label>
                    <Bar value={item.amount} max={maxTeam} />
                  </div>
                ))}
              </div>
            </article>
          </section>
        )}

        {activeView === "Alerts" && (
          <section className="grid main-grid">
            <article className="panel wide">
              <div className="panel-head"><div><span>Budget Alerts</span><h2>Needs attention</h2></div><AlertTriangle size={22} /></div>
              <div className="alerts">
                {data.alerts.map((alert) => (
                  <div className={`alert ${alert.severity}`} key={`${alert.owner}`}>
                    <strong>{alert.owner}</strong>
                    <span>{alert.message}</span>
                    <label>{formatInr(Number(alert.current))} of {formatInr(Number(alert.threshold))}</label>
                  </div>
                ))}
              </div>
            </article>
            <article className="panel recommendation">
              <div className="panel-head"><div><span>AI Recommendations</span><h2>Optimization playbook</h2></div><LineChart size={22} /></div>
              {data.recommendations.map((item) => (
                <p key={item}><Activity size={16} /> {item}</p>
              ))}
            </article>
          </section>
        )}

        {isSuperadmin && activeView === "User Management" && (
          <section className="panel user-management page-panel">
            <div className="panel-head"><div><span>Superadmin</span><h2>User Management</h2></div><Users size={22} /></div>
            {usersMessage && <p className="cluster-refresh-message">{usersMessage}</p>}
            {usersError ? (
              <p className="login-error">{usersError}</p>
            ) : (
              <table>
                <thead><tr><th>User</th><th>Email</th><th>Role</th><th>Provider</th><th>Sessions</th><th>Last login</th><th>Edit</th></tr></thead>
                <tbody>
                  {managedUsers.map((user) => (
                    <tr key={user.id}>
                      <td>{user.name}</td>
                      <td>{user.email}</td>
                      <td>
                        <select
                          className={`role-select ${user.role}`}
                          value={user.role}
                          disabled={savingRoleUserId === user.id || user.email === "raashviroyal@gmail.com"}
                          onChange={(event) => updateManagedUserRole(user, event.target.value)}
                        >
                          <option value="viewer">viewer</option>
                          <option value="admin">admin</option>
                          <option value="superadmin">superadmin</option>
                        </select>
                      </td>
                      <td>{user.provider}</td>
                      <td>{user.sessions}</td>
                      <td>{new Date(user.lastLoginAt).toLocaleString()}</td>
                      <td>
                        <span className={`role-pill ${user.role}`}>{savingRoleUserId === user.id ? "saving" : user.role}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
