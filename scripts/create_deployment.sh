#!/bin/bash

set -euo pipefail

if [[ $# != 1 ]]; then
    echo "Create a GitHub deployment object."
    echo
    echo "Usage: $(basename $0) dest_deployment_environment"
    echo "Example: $(basename $0) staging"
    exit 1
fi

export DEPLOYMENT_ENVIRONMENT=$1
export GITHUB_TOKEN=${GH_DEPLOY_TOKEN:-$GITHUB_TOKEN}
export DEPLOY_REF=$(git rev-parse --abbrev-ref HEAD)
deployment_args=$(jq -n ".auto_merge=false | .ref=env.DEPLOY_REF | .environment=env.DEPLOYMENT_ENVIRONMENT | .required_contexts=[]")
gh api repos/:owner/:repo/deployments --input - <<< "$deployment_args"
