#!/usr/bin/env bash

set -euxo pipefail

if [[ $# != 1 ]]; then
    echo "Publishes a single WDL workflow version (Docker image + WDL/JSON files) for a git release tag."
    echo
    echo "This script takes the name of a git release tag (like WORKFLOW_NAME-vX.Y.Z) in the workflows repo,"
    echo "builds the Docker image for WORKFLOW_NAME at that tag, and uploads its WDL files to the"
    echo "PER-ENVIRONMENT workflows S3 bucket for the account this runs in."
    echo
    echo "Usage: $(basename "$0") WORKFLOW_NAME-vX.Y.Z"
    echo
    echo "Required env: AWS_ACCOUNT_ID, AWS_DEFAULT_REGION, DEPLOYMENT_ENVIRONMENT (dev|staging|prod|sandbox)."
    echo "Optional env: WORKFLOWS_BUCKET (override the derived per-env bucket name)."
    exit 1
fi

WORKFLOW_TAG=$1
WORKFLOW_NAME=${WORKFLOW_TAG/-v*/}
IMAGE_TAG=v${WORKFLOW_TAG/*-v/}

# Per-environment workflows bucket (see terraform/buckets.tf:
#   seqtoid-workflows-${DEPLOYMENT_ENVIRONMENT}-${AWS_ACCOUNT_ID}).
# This replaces the legacy single shared "idseq-workflows" bucket (migration 20032 / #335).
# The per-env buckets BLOCK ALL PUBLIC ACCESS, so objects are uploaded private (no public-read ACL);
# consumers read them via account-root IAM, which is how the Step Functions / miniwdl dispatch already
# fetches them. Override with WORKFLOWS_BUCKET if you must target a non-standard bucket during cutover.
WORKFLOWS_BUCKET="${WORKFLOWS_BUCKET:-seqtoid-workflows-${DEPLOYMENT_ENVIRONMENT:?set DEPLOYMENT_ENVIRONMENT or WORKFLOWS_BUCKET}-${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID}}"

CZID_WORKFLOWS_PATH="$(mktemp -d)"
git clone https://github.com/chanzuckerberg/czid-workflows "$CZID_WORKFLOWS_PATH" \
    --branch "$WORKFLOW_TAG" \
    --depth 1 \
    --reference-if-able "$(dirname "$0")/../../czid-workflows" \
    -c advice.detachedHead=false

echo "Building Docker image for $WORKFLOW_TAG"
cd "$CZID_WORKFLOWS_PATH"
aws ecr get-login-password --region "$AWS_DEFAULT_REGION" \
    | docker login --username AWS --password-stdin      \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com"
export DOCKER_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com/${WORKFLOW_NAME}:${IMAGE_TAG}"
./scripts/docker-build.sh -t "$DOCKER_IMAGE_URI" "workflows/${WORKFLOW_NAME}"
docker push "$DOCKER_IMAGE_URI"
cd ..

# Confirm the target bucket exists in this account before publishing (replaces the old
# hardcoded `idseq-prod`-account gate — each environment publishes into its own bucket).
if ! aws s3api head-bucket --bucket "$WORKFLOWS_BUCKET" 2>/dev/null; then
    echo "ERROR: workflows bucket '$WORKFLOWS_BUCKET' not found / not accessible in this account." >&2
    echo "Run this in the target environment's account, or set WORKFLOWS_BUCKET correctly." >&2
    exit 1
fi

cd "$CZID_WORKFLOWS_PATH"
for file in $(git ls-tree -r --name-only "$WORKFLOW_TAG" | grep -e "^workflows/${WORKFLOW_NAME}/.*.wdl$" -e "^workflows/${WORKFLOW_NAME}/.*.json$" -e "^workflows/${WORKFLOW_NAME}/.*.wdl.zip$"); do
    s3_url="s3://${WORKFLOWS_BUCKET}/${WORKFLOW_TAG}/$(basename "${file}")"
    echo "[$WORKFLOW_TAG] Uploading $file to $s3_url"
    git show "${WORKFLOW_TAG}:${file}" | aws s3 cp - "$s3_url"
    if [[ "$file" == *.wdl ]]; then
        miniwdl zip "$file"
        aws s3 cp "$(basename "${file}")".zip "$s3_url".zip
    fi
done
