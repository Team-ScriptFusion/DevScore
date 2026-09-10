#!/usr/bin/env bash
# One-time bootstrap for a fresh Ubuntu 22.04 EC2 instance. Run as a sudo
# user (e.g. the default `ubuntu` user) via: bash setup.sh
#
# What this does NOT do (deliberately manual — see deploy/aws/README.md):
#   - clone the repo (needs your GitHub auth)
#   - write the three .env files (secrets)
#   - configure DNS / obtain TLS certs
set -euo pipefail

echo "==> Updating packages"
sudo apt-get update -y && sudo apt-get upgrade -y

echo "==> Installing Node.js 20.x"
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

echo "==> Installing Python 3, venv, pip"
sudo apt-get install -y python3 python3-venv python3-pip

echo "==> Installing nginx + certbot"
sudo apt-get install -y nginx certbot python3-certbot-nginx

echo "==> Installing git"
sudo apt-get install -y git

echo "==> Creating dedicated 'devscore' service user (no login shell)"
if ! id -u devscore >/dev/null 2>&1; then
  sudo useradd --system --create-home --shell /usr/sbin/nologin devscore
fi

echo "==> Creating /opt/devscore (owned by devscore)"
sudo mkdir -p /opt/devscore
sudo chown devscore:devscore /opt/devscore

echo "==> Enabling nginx + basic firewall"
sudo systemctl enable --now nginx
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

cat <<'EOF'

==> Base packages installed. Next steps (see deploy/aws/README.md):
    1. Clone the repo into /opt/devscore as the devscore user
    2. Create server/.env, cv_parser/.env, semantic_engine/.env
    3. python3 -m venv venv + pip install -r requirements.txt for the two Python services
    4. npm ci --omit=dev for the Node server
    5. Copy deploy/aws/systemd/*.service into /etc/systemd/system/, enable + start them
    6. Copy deploy/aws/nginx/devscore.conf into /etc/nginx/sites-available/, symlink into sites-enabled
    7. Point DNS at this instance's Elastic IP, then run certbot
EOF
