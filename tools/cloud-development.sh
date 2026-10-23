#!/usr/bin/env bash
# Reproducible development setup for a private Codex Cloud environment.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cloud_venv="${EDOC_CLOUD_VENV:-$project_root/.venv-cloud}"
operation="${1:-check}"
cd "$project_root"

fail() { printf '%s\n' "$1" >&2; exit 1; }

case "$operation" in setup|check|serve) ;; *) fail 'Usage: bash tools/cloud-development.sh setup|check|serve' ;; esac

# Cloud development starts with disposable SQLite and the Mock provider.
# A credential-bearing environment must be configured as a separate task.
for variable in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY EDOC_STORAGE_SUPABASE_URL \
  EDOC_STORAGE_SERVICE_ROLE_KEY EDOC_SIGNATURE_API_URL EDOC_SIGNATURE_API_KEY \
  EDOC_TSA_URL EDOC_TSA_API_KEY EDOC_FINANCE_BRIDGE_URL EDOC_FINANCE_BRIDGE_SECRET \
  CRON_SECRET RESEND_API_KEY LINE_WEBHOOK_URL LINE_CHANNEL_ACCESS_TOKEN \
  SMTP_HOST SMTP_PASSWORD; do
  [[ -z "${!variable:-}" ]] || fail "Cloud development refuses a configured service credential or endpoint: $variable"
done
for secret_file in .env .env.local .env.production .env.production.local; do
  [[ ! -e "$secret_file" ]] || fail "Keep private environment files outside the cloud development checkout: $secret_file"
done
[[ "${EDOC_DEPLOYMENT_ENV:-development}" != production && "${EDOC_DEPLOYMENT_ENV:-development}" != prod ]] || fail 'Production mode is not allowed for this development workflow.'
[[ "${VERCEL_ENV:-development}" != production ]] || fail 'Run this workflow in the development environment.'
[[ "${EDOC_EXCHANGE_PROVIDER:-mock}" == mock ]] || fail 'Only the Mock exchange provider is allowed.'
[[ "${EDOC_DB_MODE:-sqlite}" == sqlite ]] || fail 'Only disposable SQLite is allowed.'
[[ "${EDOC_STORAGE_PROVIDER:-local}" == local ]] || fail 'Only local test storage is allowed.'
[[ "${EDOC_SIGNATURE_PROVIDER:-local-simulation}" == local-simulation ]] || fail 'Only local signature simulation is allowed.'

export EDOC_DEPLOYMENT_ENV=development EDOC_DB_MODE=sqlite
export EDOC_EXCHANGE_PROVIDER=mock EDOC_EXCHANGE_ENV=sandbox EDOC_STORAGE_PROVIDER=local
export EDOC_SIGNATURE_PROVIDER=local-simulation

command -v node >/dev/null || fail 'Install Node.js 22 or 24 in the cloud environment.'
node -e 'if (![22,24].includes(Number(process.versions.node.split(".")[0]))) process.exit(1)' || fail 'Use Node.js 22 or 24.'

if [[ "$operation" == setup ]]; then
  python_command="${EDOC_CLOUD_PYTHON:-python3.12}"
  command -v "$python_command" >/dev/null || fail 'Install Python 3.12, or set EDOC_CLOUD_PYTHON to its executable.'
  "$python_command" -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 required"'
  "$python_command" -m venv "$cloud_venv"
  "$cloud_venv/bin/python" -m pip install --disable-pip-version-check \
    -r requirements.txt -r scripts/backup-restore-requirements.txt pglast==7.21
  printf '%s\n' 'Cloud dependencies prepared. Run: bash tools/cloud-development.sh check'
  exit 0
fi

cloud_python="$cloud_venv/bin/python"
[[ -x "$cloud_python" ]] || fail 'Run the setup command first, or set EDOC_CLOUD_VENV to an existing development virtualenv.'

if [[ "$operation" == serve ]]; then
  export EDOC_WRITABLE_DIR="${EDOC_WRITABLE_DIR:-$project_root/.cloud-local-state}"
  mkdir -p "$EDOC_WRITABLE_DIR"
  exec "$cloud_python" backend.py --host 127.0.0.1 --port "${EDOC_CLOUD_PORT:-5174}"
fi

check_state="$(mktemp -d "${TMPDIR:-/tmp}/edoc-cloud-check.XXXXXX")"
trap 'rm -rf "$check_state"' EXIT
export EDOC_WRITABLE_DIR="$check_state"
"$cloud_python" -m py_compile backend.py api/index.py
"$cloud_python" tools/verify_no_embedded_credentials.py
node --check app.js
node --test tests/*.test.js
"$cloud_python" -m unittest -v \
  tests.test_exchange_gateway \
  tests.test_compose_preflight_seals \
  tests.test_private_draft_archive \
  tests.test_official_document_workflow \
  tests.test_runtime_readiness_probes
printf '%s\n' 'Cloud development smoke passed. Required full database and frontend CI still run on each PR.'
