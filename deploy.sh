#!/usr/bin/env bash
# Deploy Orbit to Google Cloud: Cloud Run + Firestore + Secret Manager + Cloud Scheduler.
# Run it in Google Cloud Shell from the repository folder:  ./deploy.sh
# Safe to run again: every step checks what already exists.
set -euo pipefail

REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-orbit}"
PROJECT="$(gcloud config get-value project 2>/dev/null)"
if [[ -z "${PROJECT}" ]]; then
  echo "No project set. Run: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "Project ${PROJECT}, region ${REGION}, service ${SERVICE}"

echo "1/6 Turning on the Google Cloud APIs Orbit uses…"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com --quiet

echo "2/6 Creating the Firestore database (skipped if it exists)…"
if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  gcloud firestore databases create --database='(default)' --location="${REGION}" --type=firestore-native --quiet
fi

echo "3/6 Giving the service account only the roles it needs…"
for role in roles/datastore.user roles/secretmanager.secretAccessor roles/run.builder roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${RUNTIME_SA}" \
    --role="${role}" --condition=None --quiet >/dev/null
done

echo "4/6 Storing secrets in Secret Manager (never in the code)…"
put_secret() {  # name, value
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- --quiet >/dev/null
  else
    printf '%s' "$2" | gcloud secrets create "$1" --data-file=- --replication-policy=automatic --quiet >/dev/null
  fi
}
ensure_random_secret() {  # name
  if ! gcloud secrets describe "$1" >/dev/null 2>&1; then
    put_secret "$1" "$(head -c 48 /dev/urandom | base64 | tr -d '/+=\n')"
  fi
}
ensure_random_secret orbit-secret-key
ensure_random_secret orbit-tick-token

SECRETS="ORBIT_SECRET_KEY=orbit-secret-key:latest,ORBIT_TICK_TOKEN=orbit-tick-token:latest"
if ! gcloud secrets describe gemini-api-key >/dev/null 2>&1; then
  read -r -s -p "Paste the Gemini API key (from aistudio.google.com), or press Enter to skip: " GEMINI_KEY; echo
  [[ -n "${GEMINI_KEY}" ]] && put_secret gemini-api-key "${GEMINI_KEY}"
  unset GEMINI_KEY
fi
gcloud secrets describe gemini-api-key >/dev/null 2>&1 && SECRETS="${SECRETS},GEMINI_API_KEY=gemini-api-key:latest"

SMTP_USER="${SMTP_USER:-}"
if ! gcloud secrets describe smtp-password >/dev/null 2>&1; then
  read -r -p "Gmail address to send reminders from (Enter to skip email): " SMTP_USER
  if [[ -n "${SMTP_USER}" ]]; then
    read -r -s -p "Its 16-character Gmail app password: " SMTP_PASS; echo
    put_secret smtp-password "${SMTP_PASS}"
    unset SMTP_PASS
  fi
fi
if gcloud secrets describe smtp-password >/dev/null 2>&1; then
  SECRETS="${SECRETS},SMTP_PASSWORD=smtp-password:latest"
  if [[ -z "${SMTP_USER}" ]]; then
    SMTP_USER="$(gcloud run services describe "${SERVICE}" --region "${REGION}" \
      --format='value(spec.template.spec.containers[0].env.filter(name=SMTP_USER).extract(value).flatten())' 2>/dev/null || true)"
  fi
fi

echo "5/6 Building and deploying to Cloud Run (a few minutes the first time)…"
gcloud run deploy "${SERVICE}" --source . --region "${REGION}" --allow-unauthenticated \
  --service-account "${RUNTIME_SA}" --memory 512Mi --cpu 1 --min-instances 0 --max-instances 3 \
  --set-env-vars "ORBIT_STORE=firestore,GEMINI_MODEL=gemini-3.1-flash-lite,SMTP_USER=${SMTP_USER}" \
  --set-secrets "${SECRETS}" --quiet
URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
gcloud run services update "${SERVICE}" --region "${REGION}" --update-env-vars "ORBIT_BASE_URL=${URL}" --quiet >/dev/null

echo "6/6 Scheduling the reminder check every 5 minutes (Cloud Scheduler)…"
TICK_TOKEN="$(gcloud secrets versions access latest --secret=orbit-tick-token)"
if gcloud scheduler jobs describe orbit-tick --location "${REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http orbit-tick --location "${REGION}" --schedule="*/5 * * * *" \
    --uri="${URL}/tasks/tick" --http-method=POST --update-headers="X-Tick-Token=${TICK_TOKEN}" --quiet >/dev/null
else
  gcloud scheduler jobs create http orbit-tick --location "${REGION}" --schedule="*/5 * * * *" \
    --uri="${URL}/tasks/tick" --http-method=POST --headers="X-Tick-Token=${TICK_TOKEN}" --quiet >/dev/null
fi
unset TICK_TOKEN

echo
echo "Done. Orbit is live at: ${URL}"
curl -fsS "${URL}/healthz" && echo
