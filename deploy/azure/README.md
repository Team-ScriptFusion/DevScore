# Deploying DevScore's backend to Azure (single VM)

Moves the three backend services currently on Render — `server` (Node),
`cv_parser` (Python/Flask), `semantic_engine` (Python/Flask) — onto one
always-on Azure VM, fronted by nginx with your own subdomains and free TLS.
The client stays on Vercel unless you decide to move it too.

**Why one VM instead of one-service-per-container (ACI/App Service):**
these are three small, low-traffic services. A `B1s` VM (free-tier eligible
for the first 12 months on a new Azure subscription) comfortably runs all
three, avoids paying for an Application Gateway / Load Balancer, and is one
thing to patch instead of three. Move to Azure Container Apps / AKS later if
traffic actually demands it.

**Subdomains used below** (adjust if you want different names):
- `api.madhushan.me` → Node server (port 5000)
- `cvparser.madhushan.me` → cv_parser (port 5001)
- `engine.madhushan.me` → semantic_engine (port 5002)

---

## 1. Create the VM

Azure Portal → Virtual Machines → Create:
- **Image:** Ubuntu Server 22.04 LTS
- **Size:** `Standard_B1s` (1 vCPU / 1GB RAM — free-tier eligible for 12
  months on a new subscription; 750 hrs/month included) — enough for all
  three services at this traffic level
- **Authentication:** SSH public key (generate/download a new key pair if
  you don't already have one — it's the only way to SSH in)
- **Inbound ports:** allow SSH (22) — restrict its source later in step 2
- **Disks:** default 30GB (Standard SSD) is fine — still within the
  free-tier disk allowance

Create it.

## 2. Lock down the network security group

Azure Portal → the VM's **Networking** blade (or the associated NSG
directly):
- **SSH (22):** restrict the source to **your IP only** (not `Any`) — edit
  the auto-created SSH rule's source to "My IP address"
- **HTTP (80):** add an inbound rule allowing `Any` source
- **HTTPS (443):** add an inbound rule allowing `Any` source

## 3. Confirm the static public IP

By default Azure assigns the VM's Public IP as **Static** when created via
"Create VM" with default settings on current API versions — double-check
under the VM's **Networking** blade → the public IP resource → **Assignment**
is `Static`, not `Dynamic`. If it's Dynamic, change it (VM must be stopped
first) so the IP doesn't change on restart and break DNS.

## 4. Point DNS at it

In whatever registrar/DNS host manages `madhushan.me` (Azure DNS if you
delegated the zone there, otherwise wherever you bought it), add three **A
records**, each pointing at the VM's public IP from step 3:

```
api.madhushan.me       A   <vm-public-ip>
cvparser.madhushan.me  A   <vm-public-ip>
engine.madhushan.me    A   <vm-public-ip>
```

DNS propagation can take a few minutes to a few hours — you can move on
while it settles.

## 5. SSH in and run the bootstrap script

```bash
ssh -i your-key.pem azureuser@<vm-public-ip>
git clone https://github.com/Team-ScriptFusion/DevScore.git /tmp/devscore-bootstrap
bash /tmp/devscore-bootstrap/deploy/azure/setup.sh
```

This installs Node 20, Python 3 + venv, nginx, certbot, git, creates a
dedicated non-login `devscore` system user, and enables `ufw` (SSH + HTTP/S
only).

## 6. Clone the real repo as the `devscore` user

```bash
sudo -u devscore -H bash -c '
  git clone https://github.com/Team-ScriptFusion/DevScore.git /opt/devscore
'
rm -rf /tmp/devscore-bootstrap
```

(Private repo: generate a GitHub PAT with repo read access first and clone
with `https://<token>@github.com/...` instead, or set up a deploy key.)

## 7. Create the three `.env` files

These are **not** in git — copy the values straight from each service's
current Render "Environment" tab, with the URLs updated to the new
subdomains.

**`/opt/devscore/server/.env`** — same as Render's `devscore-poxa`, except:
```
CV_PARSER_URL=https://cvparser.madhushan.me
SEMANTIC_ENGINE_URL=https://engine.madhushan.me
GITHUB_CALLBACK_URL=https://api.madhushan.me/api/auth/github/callback
GOOGLE_CALLBACK_URL=https://api.madhushan.me/api/auth/google/callback
```
(`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `JWT_SECRET`, `CLIENT_URL`,
`GOOGLE_CLIENT_ID/SECRET`, `GITHUB_CLIENT_ID/SECRET`, the two API keys —
copy as-is from Render.)

**`/opt/devscore/cv_parser/.env`** — copy from Render's cv_parser service
(likely just `API_KEY`/similar + `PORT`, which systemd overrides anyway).

**`/opt/devscore/semantic_engine/.env`** — same as the `semantic-engine`
Render service: `GITHUB_TOKEN`, `ENGINE_API_KEY`.

Lock these down:
```bash
sudo chown devscore:devscore /opt/devscore/*/.env
sudo chmod 600 /opt/devscore/*/.env
```

## 8. Install dependencies

```bash
sudo -u devscore -H bash -c '
  cd /opt/devscore/server && npm ci --omit=dev

  cd /opt/devscore/cv_parser && python3 -m venv venv && venv/bin/pip install -r requirements.txt

  cd /opt/devscore/semantic_engine && python3 -m venv venv && venv/bin/pip install -r requirements.txt
'
```

## 9. Install and start the systemd services

```bash
sudo cp /opt/devscore/deploy/azure/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now devscore-server cv-parser semantic-engine
sudo systemctl status devscore-server cv-parser semantic-engine
```

All three now start on boot and auto-restart on crash (`Restart=always` in
each unit). Check logs any time with
`sudo journalctl -u <service-name> -f`.

## 10. nginx + TLS

```bash
sudo cp /opt/devscore/deploy/azure/nginx/devscore.conf /etc/nginx/sites-available/devscore.conf
sudo ln -s /etc/nginx/sites-available/devscore.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Once DNS from step 4 has propagated (`dig api.madhushan.me` should show the
VM's public IP), get certificates — certbot edits the nginx config in place
to add the `listen 443 ssl` blocks and sets up auto-renewal:

```bash
sudo certbot --nginx -d api.madhushan.me -d cvparser.madhushan.me -d engine.madhushan.me
```

## 11. Update the OAuth apps

- GitHub OAuth App settings → Authorization callback URL →
  `https://api.madhushan.me/api/auth/github/callback`
- Google Cloud Console → OAuth client → Authorized redirect URIs →
  `https://api.madhushan.me/api/auth/google/callback`

## 12. Point the client at the new API

In `client/vercel.json`, change the rewrite destination:
```json
"destination": "https://api.madhushan.me/api/:path*"
```
Commit, push, let Vercel redeploy (or trigger manually).

## 13. Verify

```bash
curl https://api.madhushan.me/api/health
curl https://cvparser.madhushan.me/health
curl https://engine.madhushan.me/health
```
Then walk through the real product flow: upload a resume, connect GitHub,
check the readiness score lands.

## Ongoing redeploys

```bash
ssh -i your-key.pem azureuser@<vm-public-ip>
sudo -u devscore bash /opt/devscore/deploy/azure/deploy.sh
```

(This is a manual step for now — wiring GitHub Actions to run it over SSH on
every push is a reasonable next step once this is stable, but is out of
scope here.)

## Cost / free-tier notes

- `Standard_B1s`: covered by Azure's free-tier VM allowance for the first 12
  months on a new subscription (750 hrs/month) — one instance running 24/7
  is exactly ~730 hrs/month, so this is $0 under the standard Azure Free
  Account offer during that window. After 12 months (or on a
  pay-as-you-go/existing subscription), `B1s` runs a few dollars/month —
  check current pricing for your region.
- Static public IP: Basic SKU static IPs are typically low/no cost while
  attached to a running VM; Azure can charge a small hourly fee for an
  **unattached** reserved IP, so don't deallocate the VM while keeping the
  IP reserved without checking current pricing.
- Data transfer out: Azure's free tier includes a monthly outbound data
  allowance, not a concern at this scale.
- Set a **Cost Management → Budget** alert (e.g. $5) so you get an email if
  anything unexpected starts charging — cheap insurance.
