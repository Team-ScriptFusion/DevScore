# Deploying DevScore's backend to AWS (single EC2 instance)

Moves the three backend services currently on Render — `server` (Node),
`cv_parser` (Python/Flask), `semantic_engine` (Python/Flask) — onto one
always-on EC2 instance, fronted by nginx with your own subdomains and free
TLS. The client stays on Vercel unless you decide to move it too.

**Why one instance instead of one-service-per-container (ECS/App Runner):**
these are three small, low-traffic services. A `t3.micro` (free-tier
eligible, 750 hrs/month for 12 months) comfortably runs all three, avoids
paying for a load balancer (~$16/mo alone on ALB), and is one thing to patch
instead of three. Move to ECS/Fargate later if traffic actually demands it.

**Subdomains used below** (adjust if you want different names):
- `api.madhushan.me` → Node server (port 5000)
- `cvparser.madhushan.me` → cv_parser (port 5001)
- `engine.madhushan.me` → semantic_engine (port 5002)

---

## 1. Launch the EC2 instance

AWS Console → EC2 → Launch Instance:
- **AMI:** Ubuntu Server 22.04 LTS (free-tier eligible)
- **Instance type:** `t3.micro` (or `t2.micro` if `t3.micro` isn't free-tier
  eligible on your account) — 1 vCPU / 1GB RAM is enough for all three
  services at this traffic level
- **Key pair:** create a new one, download the `.pem`, keep it safe — it's
  the only way to SSH in
- **Storage:** bump the default 8GB gp3 volume to 20GB (still free-tier
  eligible up to 30GB) — Python venvs + node_modules + OS add up
- **Security group:** create one allowing:
  - SSH (22) from **your IP only** (not 0.0.0.0/0 — pick "My IP" in the console)
  - HTTP (80) from anywhere
  - HTTPS (443) from anywhere

Launch it.

## 2. Allocate a static IP

EC2 → Elastic IPs → Allocate → associate it with the new instance. Without
this, the public IP changes every time the instance stops/starts and your
DNS records would break.

## 3. Point DNS at it

In whatever registrar/DNS host manages `madhushan.me` (Route 53 if you
transferred it in, otherwise wherever you bought it), add three **A
records**, each pointing at the Elastic IP from step 2:

```
api.madhushan.me       A   <elastic-ip>
cvparser.madhushan.me  A   <elastic-ip>
engine.madhushan.me    A   <elastic-ip>
```

DNS propagation can take a few minutes to a few hours — you can move on
while it settles.

## 4. SSH in and run the bootstrap script

```bash
ssh -i your-key.pem ubuntu@<elastic-ip>
git clone https://github.com/Team-ScriptFusion/DevScore.git /tmp/devscore-bootstrap
bash /tmp/devscore-bootstrap/deploy/aws/setup.sh
```

This installs Node 20, Python 3 + venv, nginx, certbot, git, creates a
dedicated non-login `devscore` system user, and enables `ufw` (SSH + HTTP/S
only).

## 5. Clone the real repo as the `devscore` user

```bash
sudo -u devscore -H bash -c '
  git clone https://github.com/Team-ScriptFusion/DevScore.git /opt/devscore
'
rm -rf /tmp/devscore-bootstrap
```

(Private repo: generate a GitHub PAT with repo read access first and clone
with `https://<token>@github.com/...` instead, or set up a deploy key.)

## 6. Create the three `.env` files

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

## 7. Install dependencies

```bash
sudo -u devscore -H bash -c '
  cd /opt/devscore/server && npm ci --omit=dev

  cd /opt/devscore/cv_parser && python3 -m venv venv && venv/bin/pip install -r requirements.txt

  cd /opt/devscore/semantic_engine && python3 -m venv venv && venv/bin/pip install -r requirements.txt
'
```

## 8. Install and start the systemd services

```bash
sudo cp /opt/devscore/deploy/aws/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now devscore-server cv-parser semantic-engine
sudo systemctl status devscore-server cv-parser semantic-engine
```

All three now start on boot and auto-restart on crash (`Restart=always` in
each unit). Check logs any time with
`sudo journalctl -u <service-name> -f`.

## 9. nginx + TLS

```bash
sudo cp /opt/devscore/deploy/aws/nginx/devscore.conf /etc/nginx/sites-available/devscore.conf
sudo ln -s /etc/nginx/sites-available/devscore.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Once DNS from step 3 has propagated (`dig api.madhushan.me` should show the
Elastic IP), get certificates — certbot edits the nginx config in place to
add the `listen 443 ssl` blocks and sets up auto-renewal:

```bash
sudo certbot --nginx -d api.madhushan.me -d cvparser.madhushan.me -d engine.madhushan.me
```

## 10. Update the OAuth apps

- GitHub OAuth App settings → Authorization callback URL →
  `https://api.madhushan.me/api/auth/github/callback`
- Google Cloud Console → OAuth client → Authorized redirect URIs →
  `https://api.madhushan.me/api/auth/google/callback`

## 11. Point the client at the new API

In `client/vercel.json`, change the rewrite destination:
```json
"destination": "https://api.madhushan.me/api/:path*"
```
Commit, push, let Vercel redeploy (or trigger manually).

## 12. Verify

```bash
curl https://api.madhushan.me/api/health
curl https://cvparser.madhushan.me/health
curl https://engine.madhushan.me/health
```
Then walk through the real product flow: upload a resume, connect GitHub,
check the readiness score lands.

## Ongoing redeploys

```bash
ssh -i your-key.pem ubuntu@<elastic-ip>
sudo -u devscore bash /opt/devscore/deploy/aws/deploy.sh
```

(This is a manual step for now — wiring GitHub Actions to run it over SSH on
every push is a reasonable next step once this is stable, but is out of
scope here.)

## Cost / free-tier notes

- `t3.micro` (or `t2.micro`): free for 750 hrs/month for 12 months on a new
  account — one instance running 24/7 is exactly 730 hrs/month, so this is
  $0 under the standard AWS Free Tier, independent of any promotional
  credit.
- Elastic IP: free while attached to a running instance; AWS charges a
  small hourly fee if it's ever left unattached — don't deallocate it while
  keeping the instance stopped.
- Data transfer out: free tier includes 100GB/month, not a concern at this
  scale.
- Set a **Billing → Budget** alert (e.g. $5) so you get an email if
  anything unexpected starts charging — cheap insurance.
