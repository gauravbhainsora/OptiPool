#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check backend scripts
.venv/bin/ruff format --check backend scripts
.venv/bin/pytest -q
npm --prefix frontend run build
(cd frontend && npx prettier --check 'src/**/*.{ts,tsx,css}' '*.ts' '*.json' 'tests/*.ts')
helm lint charts/optipool
helm template demo charts/optipool > /dev/null
if helm template invalid charts/optipool --set replicaCount=2 >/dev/null 2>&1; then
  echo 'ERROR: chart accepted more than one SQLite owner' >&2
  exit 1
fi
if helm template invalid charts/optipool --set ingress.enabled=true >/dev/null 2>&1; then
  echo 'ERROR: chart accepted public local authentication' >&2
  exit 1
fi
helm template secure charts/optipool --set config.mode=live --set config.auth_mode=iap \
  --set config.iap_audience=/projects/123/global/backendServices/456 \
  --set ingress.enabled=true --set ingress.host=optipool.example.org \
  --set ingress.managedCertificate=optipool --set ingress.iapOAuthSecret=optipool-iap > /dev/null
helm package charts/optipool --destination "${TMPDIR:-/tmp}"
