#!/bin/bash

set -euo pipefail

export status=$1 description=${2:-""}

deploy_url=$(jq -r .deployment.url "$GITHUB_EVENT_PATH")
deploy_creator=$(jq -r .sender.login "$GITHUB_EVENT_PATH")
deploy_env=$(jq -r .deployment.environment "$GITHUB_EVENT_PATH")
deploy_payload=$(jq -rc .deployment.payload "$GITHUB_EVENT_PATH")
statuses_url=$(jq -r .deployment.statuses_url "$GITHUB_EVENT_PATH")
jq -n '.state=env.status | .description=env.description' | http --check-status --timeout=30 POST "$statuses_url" Authorization:"token $GITHUB_TOKEN" Accept:"application/vnd.github.flash-preview+json"

slack_api=https://slack.com/api/chat.postMessage
slack_msg="Status update for <${deploy_url}|${deploy_env}:${deploy_payload} deployment> by ${deploy_creator}: ${status} (${description})"
http POST $slack_api channel=="$ALERTS_SLACK_CHANNEL_ID" text=="$slack_msg" "Authorization: Bearer $SLACK_TOKEN" || true
