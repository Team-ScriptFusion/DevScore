#!/usr/bin/env bash
# Redeploy: pull latest master, reinstall deps if they changed, restart all
# three services. Run from /opt/devscore as the devscore user:
#   sudo -u devscore bash deploy/aws/deploy.sh
set -euo pipefail
cd /opt/devscore

echo "==> Pulling latest master"
git pull origin master

echo "==> server (Node)"
(cd server && npm ci --omit=dev)

echo "==> cv_parser (Python)"
(cd cv_parser && venv/bin/pip install -r requirements.txt)

echo "==> semantic_engine (Python)"
(cd semantic_engine && venv/bin/pip install -r requirements.txt)

echo "==> Restarting services (requires sudo)"
sudo systemctl restart devscore-server cv-parser semantic-engine

echo "==> Done. Tail logs with: sudo journalctl -u devscore-server -f"
