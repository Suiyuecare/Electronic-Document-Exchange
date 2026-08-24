#!/bin/sh
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$script_dir"

gcloud_bin="${GCLOUD_BIN:-$HOME/.local/google-cloud-sdk/bin/gcloud}"
if [ ! -x "$gcloud_bin" ]; then
  echo "Google Cloud CLI is not installed; set GCLOUD_BIN to its executable" >&2
  exit 1
fi
if [ -z "${CLOUDSDK_PYTHON:-}" ]; then
  for python_candidate in \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
    python3.14 python3.13 python3.12 python3.11 python3.10 python3
  do
    if command -v "$python_candidate" >/dev/null 2>&1 \
      && "$python_candidate" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)' 2>/dev/null
    then
      CLOUDSDK_PYTHON="$(command -v "$python_candidate")"
      export CLOUDSDK_PYTHON
      break
    fi
  done
fi
if [ -z "${CLOUDSDK_PYTHON:-}" ]; then
  echo "Google Cloud CLI requires Python 3.10 through 3.14" >&2
  exit 1
fi

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${EDOC_AV_SECRET_NAME:?Set EDOC_AV_SECRET_NAME to an existing Secret Manager secret}"
: "${EDOC_AV_ALLOWED_SOURCE_HOSTS:?Set the exact Supabase host}"

region="${GCP_REGION:-asia-east1}"
service="${EDOC_AV_SERVICE_NAME:-suiyue-edoc-private-av}"

case "$EDOC_AV_ALLOWED_SOURCE_HOSTS" in
  *://*|*/*|*\?*|*@*|*,*)
    echo "EDOC_AV_ALLOWED_SOURCE_HOSTS must be one exact hostname" >&2
    exit 1
    ;;
esac

secret_bytes="$("$gcloud_bin" secrets versions access latest \
  --secret "$EDOC_AV_SECRET_NAME" \
  --project "$GCP_PROJECT_ID" 2>/dev/null | wc -c | tr -d ' ')"
if [ "$secret_bytes" -lt 32 ]; then
  echo "The configured AV secret must contain at least 32 bytes" >&2
  exit 1
fi

"$gcloud_bin" run deploy "$service" \
  --project "$GCP_PROJECT_ID" \
  --region "$region" \
  --source . \
  --execution-environment gen2 \
  --cpu 2 \
  --memory 2Gi \
  --min-instances 1 \
  --max-instances 2 \
  --concurrency 4 \
  --timeout 120 \
  --set-env-vars "EDOC_AV_ALLOWED_SOURCE_HOSTS=$EDOC_AV_ALLOWED_SOURCE_HOSTS,EDOC_AV_MAX_FILE_SIZE_MB=50,EDOC_AV_INLINE_MAX_MB=4" \
  --set-secrets "EDOC_AV_SHARED_SECRET=$EDOC_AV_SECRET_NAME:latest" \
  --allow-unauthenticated \
  --quiet

service_url="$("$gcloud_bin" run services describe "$service" \
  --project "$GCP_PROJECT_ID" \
  --region "$region" \
  --format='value(status.url)')"

curl --fail --silent --show-error --max-time 20 "$service_url/healthz" >/dev/null
printf '%s\n' "$service_url/v1/scan"
