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

to_win_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  else
    echo "$1"
  fi
}

zip_and_deploy() {
  local src_dir="$1" app_name="$2" zip_name="$3"
  local zip_path="$WORKDIR/$zip_name"
  echo "==> $app_name ($src_dir)"

  if command -v zip >/dev/null 2>&1; then
    (cd "$src_dir" && zip -rq "$zip_path" . -x "venv/*" -x "node_modules/*" -x "__pycache__/*" -x ".env")
  else
    # Git Bash on Windows usually has no `zip` binary. PowerShell's
    # Compress-Archive is present everywhere, but has a longstanding bug:
    # it stores nested entries with Windows backslashes (`src\app.js`)
    # instead of forward slashes, which corrupts the archive for Linux's
    # unzip/rsync on the App Service side. Stage a filtered copy and use
    # .NET's ZipFile.CreateFromDirectory instead, which always emits
    # forward-slash entry names.
    local win_src win_zip
    win_src="$(to_win_path "$(cd "$src_dir" && pwd)")"
    win_zip="$(to_win_path "$zip_path")"
    powershell.exe -NoProfile -Command "
      \$ErrorActionPreference = 'Stop'
      \$staging = Join-Path \$env:TEMP ('devscore_stage_' + [guid]::NewGuid())
      New-Item -ItemType Directory -Path \$staging | Out-Null
      \$exclude = @('venv','node_modules','__pycache__','.env')
      Get-ChildItem -LiteralPath '$win_src' -Force | Where-Object { \$exclude -notcontains \$_.Name } | ForEach-Object {
        Copy-Item -LiteralPath \$_.FullName -Destination (Join-Path \$staging \$_.Name) -Recurse -Force
      }
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      if (Test-Path '$win_zip') { Remove-Item '$win_zip' -Force }
      [System.IO.Compression.ZipFile]::CreateFromDirectory(\$staging, '$win_zip')
      Remove-Item \$staging -Recurse -Force
    "
  fi

  az webapp deploy \
    --resource-group "$RESOURCE_GROUP" \
    --name "$app_name" \
    --src-path "$zip_path" \
    --type zip \
    --clean true
}

zip_and_deploy "server" "$SERVER_APP" "server.zip"
zip_and_deploy "cv_parser" "$CVPARSER_APP" "cvparser.zip"
zip_and_deploy "semantic_engine" "$ENGINE_APP" "engine.zip"
zip_and_deploy "services/scoring" "$SCORING_APP" "scoring.zip"

echo "==> Done. Tail logs with: az webapp log tail --resource-group $RESOURCE_GROUP --name <app-name>"
