# Deploying DevScore's backend to Azure App Service

Moves the three backend services currently on Render — `server` (Node),
`cv_parser` (Python/Flask), `semantic_engine` (Python/Flask) — plus the new
`services/scoring` (Python/Flask) readiness-scoring model, which has never
been deployed anywhere yet, onto Azure App Service. The client stays on
Vercel unless you decide to move it too.

**Why App Service instead of a VM:** a single Linux VM (EC2-style) was the
original plan, but Azure for Students subscriptions commonly ship with a
0-vCPU quota for every general-purpose VM family (`Standard_Bs`,
`Standard_Dsv3`, ...) in every region — VM creation fails with
`NotAvailableForSubscription` no matter which size/region you pick, and
raising that quota needs a support request. App Service Plans draw from a
**separate** quota pool that student subscriptions do have, sidestepping
the problem entirely — and as a bonus there's no nginx, systemd, or certbot
to manage: each app gets its own `https://<name>.azurewebsites.net`
hostname with a free managed TLS certificate out of the box.

**One App Service Plan, four Web Apps** — these are four small,
low-traffic services, so they share a single `B1` (Basic) Linux plan rather
than paying for four. Each web app still gets its own hostname, own
environment variables, own logs, and can be scaled to its own plan later if
one service's traffic outgrows the others.

**Hostnames** (defaults from `provision.sh` — override via env vars if you
want different names):
- `devscore-server.azurewebsites.net` → Node server
- `devscore-cvparser.azurewebsites.net` → cv_parser
- `devscore-engine.azurewebsites.net` → semantic_engine
- `devscore-scoring.azurewebsites.net` → services/scoring

---

## 1. Install the Azure CLI and log in

```bash
az login
az account set --subscription "Azure for Students"
```

## 2. Find your subscription's allowed region

`az appservice list-locations --sku B1` lists every region the `B1` SKU
exists in worldwide — it does **not** account for a separate
subscription-level location-restriction policy that Azure for Students
accounts get, which locks deployment to one "best available" region
regardless of general SKU/quota availability (`provision.sh` will fail with
`RequestDisallowedByAzure` if you pick the wrong one). The Azure VM-creation
wizard's default region is usually a reliable hint at which region that is
(`Central India`, in testing for this project) — `provision.sh` defaults
`LOCATION` to `centralindia` for that reason. If it's different for your
subscription, check **Portal → Subscriptions → your subscription →
Policies → Compliance** for the location-restriction policy's allowed
region, or just try `provision.sh` and adjust `LOCATION` based on the
error.

## 3. Provision the plan and the four web apps

```bash
bash deploy/azure/provision.sh
```

(Or `LOCATION=<region> bash deploy/azure/provision.sh` to override.) This
creates the resource group, one `B1` Linux App Service Plan, and the four
web apps (Node 22 for `server`, Python 3.11 for the other three), sets each
Python app's gunicorn startup command, and turns on
`SCM_DO_BUILD_DURING_DEPLOYMENT` so a later `az webapp deploy` triggers
Azure's own `npm ci` / `pip install -r requirements.txt` instead of
expecting a pre-built artifact.

The script is safe to rerun if it fails partway through — `az group
create`/`az appservice plan create`/`az webapp create` all no-op on
resources that already exist. If it fails on the resource group step with
`InvalidResourceGroupLocation` because an earlier run created it in a
different region, delete it first (`az group delete --name devscore-rg
--yes`) and rerun.

Override any of `RESOURCE_GROUP`, `LOCATION`, `PLAN_NAME`, `PLAN_SKU`,
`SERVER_APP`, `CVPARSER_APP`, `ENGINE_APP`, `SCORING_APP` as environment
variables before running it if you want different names/region/SKU.

## 4. Configure environment variables

Each app's settings are its `.env` — set them with `az webapp config
appsettings set` (values shown are examples; copy the real ones from each
service's current Render "Environment" tab where noted).

**`devscore-server`** — same as Render's `devscore-poxa`, except the three
downstream URLs and both OAuth callback URLs point at the new hostnames:
```bash
az webapp config appsettings set --resource-group devscore-rg --name devscore-server --settings \
  CV_PARSER_URL="https://devscore-cvparser.azurewebsites.net" \
  SEMANTIC_ENGINE_URL="https://devscore-engine.azurewebsites.net" \
  SCORING_URL="https://devscore-scoring.azurewebsites.net" \
  GITHUB_CALLBACK_URL="https://devscore-server.azurewebsites.net/api/auth/github/callback" \
  GOOGLE_CALLBACK_URL="https://devscore-server.azurewebsites.net/api/auth/google/callback" \
  SUPABASE_URL="<copy from Render>" \
  SUPABASE_SERVICE_ROLE_KEY="<copy from Render>" \
  JWT_SECRET="<copy from Render>" \
  CLIENT_URL="<your Vercel client URL>" \
  GOOGLE_CLIENT_ID="<copy from Render>" \
  GOOGLE_CLIENT_SECRET="<copy from Render>" \
  GITHUB_CLIENT_ID="<copy from Render>" \
  GITHUB_CLIENT_SECRET="<copy from Render>" \
  PARSER_API_KEY="<same value as cv_parser's below>" \
  ENGINE_API_KEY="<same value as semantic_engine's below>" \
  SCORING_API_KEY="<same value as scoring's below>"
```

**`devscore-cvparser`** — copy from Render's cv_parser service:
```bash
az webapp config appsettings set --resource-group devscore-rg --name devscore-cvparser --settings \
  PARSER_API_KEY="<matches server's PARSER_API_KEY above>"
```

**`devscore-engine`** — same as the `semantic-engine` Render service:
```bash
az webapp config appsettings set --resource-group devscore-rg --name devscore-engine --settings \
  GITHUB_TOKEN="<copy from Render>" \
  ENGINE_API_KEY="<matches server's ENGINE_API_KEY above>"
```

**`devscore-scoring`** — new service, no existing Render values to copy. It
only reads one variable (`services/scoring/app.py`):
```bash
az webapp config appsettings set --resource-group devscore-rg --name devscore-scoring --settings \
  SCORING_API_KEY="<generate a random secret, matches server's SCORING_API_KEY above>"
```
Leaving it unset degrades to open access (fine for local dev, not for a
public app) — always set it here.

## 5. Deploy the code

```bash
bash deploy/azure/deploy.sh
```

This zips each service's own directory (excluding `venv/`, `node_modules/`,
`__pycache__/`, `.env`) and pushes it with `az webapp deploy`. Azure then
runs its own build (`npm ci` for the Node app, `pip install -r
requirements.txt` for the three Python apps) because of the
`SCM_DO_BUILD_DURING_DEPLOYMENT` setting from step 3 — the first deploy of
each Python app will take noticeably longer for `services/scoring`, since
its `requirements.txt` pulls in numpy/scipy/scikit-learn.

## 6. Update the OAuth apps

- GitHub OAuth App settings → Authorization callback URL →
  `https://devscore-server.azurewebsites.net/api/auth/github/callback`
- Google Cloud Console → OAuth client → Authorized redirect URIs →
  `https://devscore-server.azurewebsites.net/api/auth/google/callback`

## 7. Point the client at the new API

In `client/vercel.json`, change the rewrite destination:
```json
"destination": "https://devscore-server.azurewebsites.net/api/:path*"
```
Commit, push, let Vercel redeploy (or trigger manually).

## 8. Verify

```bash
curl https://devscore-server.azurewebsites.net/api/health
curl https://devscore-cvparser.azurewebsites.net/health
curl https://devscore-engine.azurewebsites.net/health
curl https://devscore-scoring.azurewebsites.net/health
```
Then walk through the real product flow: upload a resume, connect GitHub,
check the readiness score lands.

## Ongoing redeploys

```bash
bash deploy/azure/deploy.sh
```
(This is a manual step for now — wiring GitHub Actions to run it on every
push is a reasonable next step once this is stable, but is out of scope
here.)

## Custom domain (optional)

`B1` supports custom domains and a free App Service Managed Certificate.
Azure Portal → the web app → **Custom domains** → add
`api.madhushan.me` (or similar) → add the CNAME/TXT records it gives you at
your DNS host → once verified, add a free managed certificate for it. Do
this per app if you want `cvparser.madhushan.me` /
`engine.madhushan.me` / `scoring.madhushan.me` too, then update the URLs in
steps 4/6/7 accordingly.

## Cost / free-tier notes

- `B1` Linux App Service Plan: not part of the always-free tier, but cheap
  (roughly $13/month at time of writing, shared across all four apps since
  they're on one plan) — check current pricing for your region. If your
  subscription's App Service quota only allows `F1` (Free), you can start
  there instead, but note F1 has no custom-domain support, a daily compute
  quota, and idles the app after inactivity (fine for testing, not for an
  always-on production backend).
- Data transfer out: Azure's free tier includes a monthly outbound data
  allowance, not a concern at this scale.
- Set a **Cost Management → Budget** alert (e.g. $5) so you get an email if
  anything unexpected starts charging — cheap insurance.
