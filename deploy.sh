#!/usr/bin/env bash
# Deploys a translator service to Cloud Run in us-central1 (hard rule 2). With no settings, the
# live chongqing-translator service with the Chongqing language profile, exactly as before.
#
#   ./deploy.sh            build and deploy (scales to zero; see AGENTS.md for 15-23 Dec)
#   ./deploy.sh --secrets  create or update the 4 secrets from backend/.env (asks first)
#   ./deploy.sh --bucket   create the clip bucket once: private, 30-day delete, no soft delete
#
# A second service with another language profile (owner decision 2026-11-23) has its own
# bucket and shares the service account and the 4 secrets (same hub PIN and API token):
#
#   SERVICE=cantonese-guide-translator BUCKET=<project>-cg-clips PROFILE=cantonese-guide \
#     ./deploy.sh --bucket      (once), then the same settings with ./deploy.sh
#
# Only the app's sources are uploaded: the files git tracks or would track under backend/ and
# frontend/, copied to a temporary folder. .env files, node_modules, bakeoff/ recordings and
# results never leave the laptop. The service runs as its own service account, which may call
# Speech-to-Text, Vertex AI, Text-to-Speech and Cloud Translation, and read its own 4 secrets.
set -euo pipefail
cd "$(dirname "$0")"

# Read before backend/.env, so nothing in it can change which service is deployed.
SERVICE=${SERVICE:-chongqing-translator}
want_profile=${PROFILE:-chongqing}
want_bucket=${BUCKET:-}
SA_NAME=${SA_NAME:-chongqing-translator}

set -a
# shellcheck disable=SC1091
source backend/.env
set +a
: "${GCP_PROJECT:?set GCP_PROJECT in backend/.env}"

REGION=us-central1
PROFILE=$want_profile
ACCOUNT="$SA_NAME@$GCP_PROJECT.iam.gserviceaccount.com"
# Clips and transcripts, kept 30 days (hard rule 14 exception for our own storage). Each
# service has its own: sharing one would mix their days and their join link.
LIVE_BUCKET="$GCP_PROJECT-cq-clips"
if [[ "$SERVICE" == chongqing-translator ]]; then
  BUCKET=${want_bucket:-$LIVE_BUCKET}
  if [[ "$PROFILE" != chongqing || "$BUCKET" != "$LIVE_BUCKET" ]]; then
    echo "chongqing-translator runs only the chongqing profile on $LIVE_BUCKET" >&2
    exit 1
  fi
else
  BUCKET=$want_bucket
  if [[ -z "$BUCKET" || "$BUCKET" == "$LIVE_BUCKET" ]]; then
    echo "set BUCKET to $SERVICE's own bucket (not $LIVE_BUCKET)" >&2
    exit 1
  fi
fi
if [[ "$PROFILE" != chongqing && ! -f "backend/profiles/$PROFILE.yaml" ]]; then
  echo "unknown PROFILE $PROFILE: no backend/profiles/$PROFILE.yaml" >&2
  exit 1
fi
# Secret Manager name -> environment variable: the Groq and OpenAI keys, the hub PIN and the
# API token.
SECRETS=(groq-api-key:GROQ_API_KEY openai-api-key:OPENAI_API_KEY hub-pin:HUB_PIN
  api-token:API_TOKEN)

if [[ "${1:-}" == "--bucket" ]]; then
  if ! gcloud storage buckets describe "gs://$BUCKET" --project "$GCP_PROJECT" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://$BUCKET" --project "$GCP_PROJECT" --location "$REGION" \
      --uniform-bucket-level-access --public-access-prevention --soft-delete-duration=0
  fi
  lifecycle=$(mktemp)
  # Only the day folders expire (clips, transcripts, usage); settings/ holds the join link,
  # which must outlive 30 days.
  echo '{"rule": [{"action": {"type": "Delete"},
    "condition": {"age": 30, "matchesPrefix": ["days/"]}}]}' >"$lifecycle"
  gcloud storage buckets update "gs://$BUCKET" --project "$GCP_PROJECT" \
    --lifecycle-file="$lifecycle" --soft-delete-duration=0
  rm -f "$lifecycle"
  # The app's service account may read and write objects in this bucket, and nothing else.
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$GCP_PROJECT" \
    --member "serviceAccount:$ACCOUNT" --role roles/storage.objectAdmin >/dev/null
  echo "bucket gs://$BUCKET ready"
  exit 0
fi

if [[ "${1:-}" == "--secrets" ]]; then
  read -r -p "Create or update ${#SECRETS[@]} secrets in $GCP_PROJECT from backend/.env? [y/N] " ok
  [[ "$ok" == "y" ]] || exit 1
  for pair in "${SECRETS[@]}"; do
    name=${pair%%:*} var=${pair##*:}
    : "${!var:?set $var in backend/.env}"
    if ! gcloud secrets describe "$name" --project "$GCP_PROJECT" >/dev/null 2>&1; then
      gcloud secrets create "$name" --project "$GCP_PROJECT" --replication-policy automatic
    fi
    # The value goes through stdin, never onto the command line or the screen.
    printf '%s' "${!var}" | gcloud secrets versions add "$name" --project "$GCP_PROJECT" \
      --data-file=- >/dev/null
    echo "updated secret $name"
  done
  exit 0
fi

if ! gcloud iam service-accounts describe "$ACCOUNT" --project "$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --project "$GCP_PROJECT" \
    --display-name "Chongqing translator (Cloud Run)"
fi
for role in roles/speech.client roles/aiplatform.user roles/cloudtranslate.user \
  roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member "serviceAccount:$ACCOUNT" \
    --role "$role" --condition None --quiet >/dev/null
done
secret_flags=()
for pair in "${SECRETS[@]}"; do
  name=${pair%%:*} var=${pair##*:}
  gcloud secrets add-iam-policy-binding "$name" --project "$GCP_PROJECT" \
    --member "serviceAccount:$ACCOUNT" --role roles/secretmanager.secretAccessor --quiet >/dev/null
  secret_flags+=("$var=$name:latest")
done

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
git ls-files -z --cached --others --exclude-standard -- backend frontend Dockerfile .dockerignore \
  | tar --null -T - -cf - | tar -xf - -C "$stage"

echo "deploying $SERVICE: profile $PROFILE, bucket gs://$BUCKET, account $ACCOUNT"
# --timeout 3600: the hub's WebSocket ends at the request timeout, and the hub reconnects.
gcloud run deploy "$SERVICE" --source "$stage" --project "$GCP_PROJECT" --region "$REGION" \
  --cpu 1 --memory 512Mi --max-instances 1 --timeout 3600 \
  --service-account "$ACCOUNT" --allow-unauthenticated --quiet \
  --set-env-vars "GCP_PROJECT=$GCP_PROJECT,CLIP_BUCKET=$BUCKET,PROFILE=$PROFILE" \
  --set-secrets "$(IFS=,; echo "${secret_flags[*]}")"
