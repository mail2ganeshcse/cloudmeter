import React, { useEffect, useMemo, useState } from "react";
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
  FileText,
  Gauge,
  IndianRupee,
  Layers3,
  LineChart,
  Receipt,
  Search,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Terminal,
  UserCheck,
  LogOut,
  Users,
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
  aiUsage: Array<Record<string, string | number>>;
  invoices: Array<Record<string, string | number>>;
  alerts: Array<Record<string, string | number>>;
  recommendations: string[];
};

type Session = {
  user: { name: string; email: string; avatar: string; username?: string; hasPassword?: boolean };
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

  useEffect(() => {
    if (!googleClientId) {
      setError("Google OAuth is not configured. Add VITE_GOOGLE_CLIENT_ID in frontend/.env and GOOGLE_CLIENT_ID in backend/.env.");
      return;
    }

    const existing = document.querySelector<HTMLScriptElement>('script[src="https://accounts.google.com/gsi/client"]');
    const script = existing ?? document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => {
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
      setReady(true);
      setError("");
    };
    script.onerror = () => setError("Could not load Google sign-in. Check your network and try again.");

    if (!existing) {
      document.head.appendChild(script);
    } else if (window.google) {
      window.google.accounts.id.initialize({
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
      setReady(true);
      setError("");
    }
  }, [onLogin]);

  function signIn() {
    if (!username || !password) {
      setError("Enter your email and password, then connect with Google once to save local login.");
      return;
    }
    if (!googleClientId) {
      setError("Google OAuth is not configured. Add VITE_GOOGLE_CLIENT_ID before signing in.");
      return;
    }
    if (!window.google || !ready) {
      setError("Google sign-in is still loading. Please try again in a moment.");
      return;
    }
    setError("");
    setLoading(true);
    window.google.accounts.id.prompt((notification) => {
      if (notification.isNotDisplayed()) {
        setLoading(false);
        setError(`Google popup was not displayed: ${notification.getNotDisplayedReason()}`);
      }
      if (notification.isSkippedMoment()) {
        setLoading(false);
        setError(`Google sign-in was skipped: ${notification.getSkippedReason()}`);
      }
    });
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

  return (
    <main className="login-shell">
      <section className="login-hero">
        <div>
          <span className="eyebrow">CloudMeter AI</span>
          <h1>Enter with Google, connect a cluster, see cost clarity in minutes.</h1>
          <p>
            New users get a limited workspace for one cluster and seven days of metering. Company admins can unlock invoices, chargeback edits, and MSP customer billing.
          </p>
        </div>
        <aside className="login-box">
          <UserCheck size={26} />
          <h2>Sign in</h2>
          <label>Email</label>
          <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="you@company.com" type="email" />
          <label>Password</label>
          <input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Minimum 8 characters" type="password" />
          <button className="password-button" onClick={passwordSignIn} disabled={loading}>
            <KeyRound size={17} /> {loading ? "Signing in..." : "Login with password"}
          </button>
          <button className="google-button" onClick={signIn} disabled={loading || !ready || !googleClientId}>
            <span>G</span> {loading ? "Waiting for Google..." : "Connect / Continue with Google"}
          </button>
          {error && <p className="login-error">{error}</p>}
          <small>First time: enter email/password and connect Google once. Next time: use password login directly.</small>
        </aside>
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
  const k8sRows = data.kubernetes.slice(0, 6);
  const aiRows = data.aiUsage.slice(0, 6);
  const isSuperadmin = session?.session.role === "superadmin";
  const limited = session?.session.role !== "admin" && !isSuperadmin;

  useEffect(() => {
    if (!isSuperadmin) {
      return;
    }
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
  }, [isSuperadmin]);

  function copyCommand(value: string, label: string) {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(label);
      window.setTimeout(() => setCopied(""), 1800);
    });
  }

  function logout() {
    fetch(`${apiUrl}/api/auth/logout`, { method: "POST", credentials: "include" })
      .finally(() => setSession(null));
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

        <section className="onboarding-panel">
          <div className="onboarding-copy">
            <span className="eyebrow">Company onboarding</span>
            <h2>Connect Kubernetes with one read-only command.</h2>
            <p>
              Invite a customer, choose AWS EKS, GKE, OCI OKE, on-prem or generic Kubernetes, then run the generated command from terminal or cloud shell.
            </p>
            <div className="prereqs">
              {(onboarding?.prerequisites ?? ["kubectl access", "curl installed", "outbound HTTPS"]).map((item) => (
                <label key={item}><CheckCircle2 size={16} /> {item}</label>
              ))}
            </div>
          </div>
          <div className="cluster-stack">
            {(onboarding?.clusters ?? []).slice(0, limited ? 1 : 3).map((cluster) => (
              <article className="cluster-card" key={cluster.id}>
                <div>
                  <strong>{cluster.clusterName}</strong>
                  <span>{cluster.provider} · {cluster.environment} · {cluster.agentMode}</span>
                </div>
                <em className={cluster.status}>{cluster.status}</em>
                <code>{cluster.installCommand}</code>
                <div className="cluster-actions">
                  <button onClick={() => copyCommand(cluster.installCommand, cluster.clusterName)}><Copy size={16} /> {copied === cluster.clusterName ? "Copied" : "Copy install"}</button>
                  <button onClick={() => copyCommand(cluster.verifyCommand, `${cluster.clusterName}-verify`)}><Terminal size={16} /> Verify</button>
                </div>
              </article>
            ))}
          </div>
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

        <section className="grid main-grid">
          <article className="panel wide">
            <div className="panel-head"><div><span>Kubernetes Costing</span><h2>Namespace and pod-level chargeback</h2></div><ServerCog size={22} /></div>
            <table>
              <thead><tr><th>Namespace</th><th>Workload</th><th>Team</th><th>CPU</th><th>GPU</th><th>Cost</th></tr></thead>
              <tbody>
                {k8sRows.map((row) => (
                  <tr key={`${row.namespace}-${row.workload}`}>
                    <td>{row.namespace}</td><td>{row.workload}</td><td>{row.team}</td><td>{compact(Number(row.cpu))}</td><td>{row.gpu}</td><td>{formatInr(Number(row.amount))}</td>
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
        </section>

        <section className="grid two bottom">
          <article className="panel">
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

          <article className="panel recommendation">
            <div className="panel-head"><div><span>AI Recommendations</span><h2>Optimization playbook</h2></div><LineChart size={22} /></div>
            {data.recommendations.map((item) => (
              <p key={item}><Activity size={16} /> {item}</p>
            ))}
          </article>
        </section>

        {isSuperadmin && (
          <section className="panel user-management">
            <div className="panel-head"><div><span>Superadmin</span><h2>User Management</h2></div><Users size={22} /></div>
            {usersError ? (
              <p className="login-error">{usersError}</p>
            ) : (
              <table>
                <thead><tr><th>User</th><th>Email</th><th>Role</th><th>Provider</th><th>Sessions</th><th>Last login</th></tr></thead>
                <tbody>
                  {managedUsers.map((user) => (
                    <tr key={user.id}>
                      <td>{user.name}</td>
                      <td>{user.email}</td>
                      <td><span className={`role-pill ${user.role}`}>{user.role}</span></td>
                      <td>{user.provider}</td>
                      <td>{user.sessions}</td>
                      <td>{new Date(user.lastLoginAt).toLocaleString()}</td>
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
