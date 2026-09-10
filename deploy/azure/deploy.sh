#!/usr/bin/env bash
# Redeploy: zip each service's own directory and push it with `az webapp
# deploy`. Run from the repo root, with the Azure CLI logged in and the 4
# web apps already provisioned (deploy/azure/provision.sh). Each app has
# SCM_DO_BUILD_DURING_DEPLOYMENT=true, so Azure runs `npm ci`/`pip install
# -r requirements.txt` itself after unzipping — no local build step needed.
set -euo pipefail
cd "$(dirname "$0")/../.."

RESOURCE_GROUP="${RESOURCE_GROUP:-devscore-rg}"
SERVER_APP="${SERVER_APP:-devscore-server}"
CVPARSER_APP="${CVPARSER_APP:-devscore-cvparser}"
ENGINE_APP="${ENGINE_APP:-devscore-engine}"
SCORING_APP="${SCORING_APP:-devscore-scoring}"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

zip_and_deploy() {
  local src_dir="$1" app_name="$2" zip_name="$3"
  echo "==> $app_name ($src_dir)"
  (cd "$src_dir" && zip -rq "$WORKDIR/$zip_name" . -x "venv/*" -x "node_modules/*" -x "__pycache__/*" -x ".env")
  az webapp deploy \
    --resource-group "$RESOURCE_GROUP" \
    --name "$app_name" \
    --src-path "$WORKDIR/$zip_name" \
    --type zip
}

zip_and_deploy "server" "$SERVER_APP" "server.zip"
zip_and_deploy "cv_parser" "$CVPARSER_APP" "cvparser.zip"
zip_and_deploy "semantic_engine" "$ENGINE_APP" "engine.zip"
zip_and_deploy "services/scoring" "$SCORING_APP" "scoring.zip"

echo "==> Done. Tail logs with: az webapp log tail --resource-group $RESOURCE_GROUP --name <app-name>"
