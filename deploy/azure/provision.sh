#!/usr/bin/env bash
# One-time provisioning of the 4 backend services as Azure App Service
# (Linux) web apps sharing a single App Service Plan. Run locally with the
# Azure CLI logged in (`az login`) — this does NOT deploy code or set
# secrets, see deploy/azure/README.md for those steps.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-devscore-rg}"
# Pick whichever region your subscription's location-restriction policy
# actually allows — Azure for Students subscriptions are often locked to
# one region regardless of general SKU/quota availability. Confirm with:
#   az group create --name <test-rg> --location <region>
LOCATION="${LOCATION:-centralindia}"
PLAN_NAME="${PLAN_NAME:-devscore-plan}"
PLAN_SKU="${PLAN_SKU:-B1}"

SERVER_APP="${SERVER_APP:-devscore-server}"
CVPARSER_APP="${CVPARSER_APP:-devscore-cvparser}"
ENGINE_APP="${ENGINE_APP:-devscore-engine}"
SCORING_APP="${SCORING_APP:-devscore-scoring}"

echo "==> Resource group"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" >/dev/null

echo "==> App Service Plan ($PLAN_SKU, Linux) — shared by all 4 apps"
az appservice plan create \
  --name "$PLAN_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --is-linux \
  --sku "$PLAN_SKU" >/dev/null

echo "==> Web app: $SERVER_APP (Node)"
az webapp create \
  --name "$SERVER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --plan "$PLAN_NAME" \
  --runtime "NODE|22-lts" >/dev/null

echo "==> Web app: $CVPARSER_APP (Python)"
az webapp create \
  --name "$CVPARSER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --plan "$PLAN_NAME" \
  --runtime "PYTHON|3.11" >/dev/null
az webapp config set --name "$CVPARSER_APP" --resource-group "$RESOURCE_GROUP" \
  --startup-file "gunicorn --bind=0.0.0.0 --timeout 90 app:app" >/dev/null

echo "==> Web app: $ENGINE_APP (Python)"
az webapp create \
  --name "$ENGINE_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --plan "$PLAN_NAME" \
  --runtime "PYTHON|3.11" >/dev/null
az webapp config set --name "$ENGINE_APP" --resource-group "$RESOURCE_GROUP" \
  --startup-file "gunicorn --bind=0.0.0.0 --timeout 120 service.app:app" >/dev/null

echo "==> Web app: $SCORING_APP (Python)"
az webapp create \
  --name "$SCORING_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --plan "$PLAN_NAME" \
  --runtime "PYTHON|3.11" >/dev/null
az webapp config set --name "$SCORING_APP" --resource-group "$RESOURCE_GROUP" \
  --startup-file "gunicorn --bind=0.0.0.0 --timeout 90 app:app" >/dev/null

echo "==> Enabling build-on-deploy for all 4 apps (installs requirements.txt/package.json on every zip deploy)"
for app in "$SERVER_APP" "$CVPARSER_APP" "$ENGINE_APP" "$SCORING_APP"; do
  az webapp config appsettings set \
    --name "$app" --resource-group "$RESOURCE_GROUP" \
    --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true >/dev/null
done

cat <<EOF

==> Provisioned. Default hostnames (HTTPS + cert included for free, no certbot needed):
    https://$SERVER_APP.azurewebsites.net
    https://$CVPARSER_APP.azurewebsites.net
    https://$ENGINE_APP.azurewebsites.net
    https://$SCORING_APP.azurewebsites.net

Next: set each app's environment variables (see deploy/azure/README.md
step "Configure environment variables"), then run deploy/azure/deploy.sh
to push code.
EOF
