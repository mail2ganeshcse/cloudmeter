# CloudMeter AI

A working SaaS starter for multi-cloud costing, Kubernetes chargeback, AI usage billing, invoice generation, forecasting, and budget alerts.

## Stack

- Frontend: React + Vite + TypeScript
- Backend: FastAPI + SQLAlchemy
- Database: local PostgreSQL

## Run locally

Start Postgres:

```bash
docker compose up -d
```

Start the API:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8001
```

Start the frontend:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open `http://localhost:5173`.

The API seeds demo customers, AWS/GCP/OCI spend, Kubernetes namespace costs, AI provider usage, invoices, alerts, forecasts, and recommendations on first startup.

## Login and onboarding

- Configure a Google OAuth Web Client ID before using login.
- In Google Cloud Console, add `http://localhost:5173` as an authorized JavaScript origin.
- Put the same OAuth client ID in `backend/.env` as `GOOGLE_CLIENT_ID` and in `frontend/.env` as `VITE_GOOGLE_CLIENT_ID`.
- Click `Continue with Google` to open Google Identity Services popup authorization.
- Verified Google users enter a limited viewer workspace.
- Limited users can view the dashboard and connect one read-only Kubernetes cluster.
- Admin-style demo access is returned for `cloudmeter.ai` or `example.com` emails.
- The backend stores the Google profile and a hashed CloudMeter session in Postgres, then sets an HttpOnly `cloudmeter_session` cookie.
- The onboarding panel shows prerequisites, connected clusters, and copyable install/verify commands.
- The generated install command downloads `http://localhost:8001/api/agent/install.sh` and creates a `cloudmeter-agent` namespace, service account, read-only RBAC, and demo agent deployment.

Example command format:

```bash
CLOUDMETER_TOKEN=<token> CLOUDMETER_CLUSTER=<cluster-name> CLOUDMETER_PROVIDER='AWS EKS' /bin/bash -c "$(curl -fsSL http://localhost:8001/api/agent/install.sh)"
```
