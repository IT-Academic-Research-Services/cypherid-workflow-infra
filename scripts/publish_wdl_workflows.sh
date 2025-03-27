#!/usr/bin/env bash

set -euxo pipefail

if [[ $# != 1 ]]; then
    echo "This script takes the name of a git release tag (like WORKFLOW_NAME-vX.Y.Z) in the czid-workflows repo,"
    echo "builds a Docker image for the Dockerfile for WORKFLOW_NAME at the given tag,"
    echo "and uploads all WDL files for WORKFLOW_NAME at the given tag to the czid-workflows S3 bucket."
    echo "Usage: $(basename $0) workflow-tag"
    exit 1
fi

WORKFLOW_TAG=$1
WORKFLOW_NAME=${WORKFLOW_TAG/-v*/}
IMAGE_TAG=v${WORKFLOW_TAG/*-v/}
CZID_WORKFLOWS_PATH="$(mktemp -d)"
git clone https://github.com/chanzuckerberg/czid-workflows "$CZID_WORKFLOWS_PATH" \
    --branch "$WORKFLOW_TAG" \
    --depth 1 \
    --reference-if-able $(dirname $0)/../../czid-workflows \
    -c advice.detachedHead=false

echo "Building Docker image for $WORKFLOW_TAG"
cd $CZID_WORKFLOWS_PATH
aws ecr get-login-password --region $AWS_DEFAULT_REGION \
    | docker login --username AWS --password-stdin      \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com"
export DOCKER_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com/${WORKFLOW_NAME}:${IMAGE_TAG}"
./scripts/docker-build.sh -t $DOCKER_IMAGE_URI "workflows/${WORKFLOW_NAME}"
docker push "$DOCKER_IMAGE_URI"
cd ..

if [[ $(aws iam list-account-aliases | jq -r '.AccountAliases[0]') == "idseq-prod" ]]; then
    cd "$CZID_WORKFLOWS_PATH"
    for file in $(git ls-tree -r --name-only "$WORKFLOW_TAG" | grep -e "^workflows/${WORKFLOW_NAME}/.*.wdl$" -e "^workflows/${WORKFLOW_NAME}/.*.json$" -e "^workflows/${WORKFLOW_NAME}/.*.wdl.zip$"); do
        s3_url="s3://idseq-workflows/${WORKFLOW_TAG}/$(basename ${file})"
        echo "[$WORKFLOW_TAG] Uploading $file to $s3_url"
        git show "${WORKFLOW_TAG}:${file}" | aws s3 cp --acl public-read - "$s3_url"
		if [[ "$file" == *.wdl ]]; then 
			miniwdl zip $file 
			aws s3 cp --acl public-read $(basename ${file}).zip "$s3_url".zip
		fi
    done
else
    echo "Run this script in the idseq-prod AWS account to publish WDL files to S3"
fi
