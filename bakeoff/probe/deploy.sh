#!/usr/bin/env bash
# Step 6: deploy the probe to Cloud Run in us-central1. Run from bakeoff/: probe/deploy.sh
#
# Only what the probe needs is uploaded: the files are copied to a temporary folder first, so
# recordings/, out/ and .env never leave the laptop. The service runs as its own service
# account, which may call Speech-to-Text, Vertex AI and Text-to-Speech, and nothing else.
# Delete everything after week 1 with: probe/deploy.sh --delete
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a
: "${GCP_PROJECT:?set GCP_PROJECT in bakeoff/.env}"
: "${PROBE_TOKEN:?set PROBE_TOKEN in bakeoff/.env}"

SERVICE=cq-probe
REGION=us-central1
ACCOUNT="$SERVICE@$GCP_PROJECT.iam.gserviceaccount.com"

if [[ "${1:-}" == "--delete" ]]; then
  gcloud run services delete "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --quiet
  gcloud iam service-accounts delete "$ACCOUNT" --project "$GCP_PROJECT" --quiet
  echo "Deleted. Also delete the image in Artifact Registry (cloud-run-source-deploy/$SERVICE)."
  exit 0
fi

if ! gcloud iam service-accounts describe "$ACCOUNT" --project "$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SERVICE" --project "$GCP_PROJECT" \
    --display-name "Week-1 probe (delete after week 1)"
fi
for role in roles/speech.client roles/aiplatform.user roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member "serviceAccount:$ACCOUNT" \
    --role "$role" --condition None --quiet >/dev/null
done

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/probe"
cp -r lib prompts config.yaml glossary.yaml "$stage/"
cp -r probe/app.py probe/static "$stage/probe/"
cp probe/Dockerfile "$stage/"
find "$stage" -name __pycache__ -prune -exec rm -rf {} +
uv export --frozen --no-dev --no-emit-project --no-hashes --quiet > "$stage/requirements.txt"

# --timeout 3600: WebSockets and the radio stream end at the request timeout.
gcloud run deploy "$SERVICE" --source "$stage" --project "$GCP_PROJECT" --region "$REGION" \
  --cpu 1 --memory 512Mi --max-instances 1 --timeout 3600 \
  --service-account "$ACCOUNT" --allow-unauthenticated --quiet \
  --set-env-vars "GCP_PROJECT=$GCP_PROJECT,PROBE_TOKEN=$PROBE_TOKEN"

url=$(gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" \
  --format 'value(status.url)')
echo
echo "Open on the iPhone (token from bakeoff/.env):"
echo "  $url/latency?t=<PROBE_TOKEN>"
echo "  $url/locktest?t=<PROBE_TOKEN>"
