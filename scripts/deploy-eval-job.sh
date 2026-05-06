#!/usr/bin/env bash
# scripts/deploy-eval-job.sh — build + deploy the eval Cloud Run Job.
#
# Usage:
#   ./scripts/deploy-eval-job.sh build     # build + push Docker image
#   ./scripts/deploy-eval-job.sh deploy    # create/update Cloud Run Job
#   ./scripts/deploy-eval-job.sh run       # trigger a single execution
#   ./scripts/deploy-eval-job.sh all       # build + deploy + run

set -euo pipefail

PROJECT="sondreskarsten-d7d14"
REGION="europe-north1"
REGISTRY="europe-north1-docker.pkg.dev/${PROJECT}/brreg-pipelines"
IMAGE="${REGISTRY}/regnskapsnoter-eval:latest"
JOB_NAME="regnskapsnoter-eval-production"
SA="s1sfreracct@${PROJECT}.iam.gserviceaccount.com"

ACTION="${1:-all}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

build() {
    echo "::: Building Docker image"
    docker build --no-cache -f Dockerfile.eval -t "$IMAGE" .
    echo "::: Pushing to Artifact Registry"
    docker push "$IMAGE"
}

deploy() {
    echo "::: Creating/updating Cloud Run Job"
    gcloud run jobs create "$JOB_NAME" \
        --project="$PROJECT" \
        --region="$REGION" \
        --image="$IMAGE" \
        --cpu=4 \
        --memory=16Gi \
        --max-retries=0 \
        --task-timeout=3600s \
        --service-account="$SA" \
        --set-env-vars="MODE=production_eval,GOOGLE_CLOUD_PROJECT=${PROJECT}" \
        2>/dev/null \
    || gcloud run jobs update "$JOB_NAME" \
        --project="$PROJECT" \
        --region="$REGION" \
        --image="$IMAGE" \
        --cpu=4 \
        --memory=16Gi \
        --task-timeout=3600s \
        --set-env-vars="MODE=production_eval,GOOGLE_CLOUD_PROJECT=${PROJECT}"
    echo "  Job: $JOB_NAME in $REGION"
}

run() {
    echo "::: Triggering execution"
    gcloud run jobs execute "$JOB_NAME" \
        --project="$PROJECT" \
        --region="$REGION" \
        --wait
}

case "$ACTION" in
    build)  build ;;
    deploy) deploy ;;
    run)    run ;;
    all)    build && deploy && run ;;
    *)
        echo "Usage: $0 [build|deploy|run|all]" >&2
        exit 1
        ;;
esac
