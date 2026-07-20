#!/bin/bash
#
# reference_index_staleness.sh -- reference-age SLA probe for the NT/NR index.
#
# The sequence-DB mirror of `rake taxonomy:staleness`. Reads the current
# index-version pointer, parses its date, computes the age in days, and:
#   1. publishes the age as the CloudWatch metric IndexAgeDays (the
#      reference-index staleness alarm in terraform watches this metric), and
#   2. exits non-zero when the age exceeds the SLA, so it doubles as a CronJob
#      probe (same behavior as the rake task's non-zero exit).
#
# Run it on a schedule (a Kubernetes CronJob or an EventBridge-scheduled job).
# The alarm's treat_missing_data=breaching means: if this probe stops running,
# the alarm fires -- an unmeasured reference age is itself an SLA failure.
#
# Usage:
#   DEPLOYMENT_ENVIRONMENT=dev scripts/reference_index_staleness.sh
#
# Env:
#   DEPLOYMENT_ENVIRONMENT  (required)
#   AWS_REGION              (optional, default us-west-2)
#   MAX_AGE_DAYS            (optional, default 400 -- ~annual NT/NR SLA)
#   METRIC_NAMESPACE        (optional, default Seqtoid/Reference)
#   REPORT_ONLY            (optional, "1" = publish + log but always exit 0)

set -euo pipefail

: "${DEPLOYMENT_ENVIRONMENT:?set DEPLOYMENT_ENVIRONMENT (dev|staging|prod|sandbox)}"
AWS_REGION="${AWS_REGION:-us-west-2}"
MAX_AGE_DAYS="${MAX_AGE_DAYS:-400}"
METRIC_NAMESPACE="${METRIC_NAMESPACE:-Seqtoid/Reference}"
PREFIX="/seqtoid/${DEPLOYMENT_ENVIRONMENT}/reference-index"

VERSION="$(aws ssm get-parameter --region "$AWS_REGION" --name "${PREFIX}/current-version" --query 'Parameter.Value' --output text)"

# Parse a YYYY-MM-DD date out of the version string.
if [[ ! "$VERSION" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "[staleness] cannot parse a date from current-version='${VERSION}'" >&2
    [[ "${REPORT_ONLY:-}" == "1" ]] && exit 0
    exit 3
fi

# Age in days (portable between GNU date and BSD/macOS date).
if date -d "$VERSION" +%s >/dev/null 2>&1; then
    VER_EPOCH="$(date -d "$VERSION" +%s)"          # GNU
else
    VER_EPOCH="$(date -j -f %Y-%m-%d "$VERSION" +%s)" # BSD/macOS
fi
NOW_EPOCH="$(date +%s)"
AGE_DAYS=$(( (NOW_EPOCH - VER_EPOCH) / 86400 ))

echo "[staleness] env=${DEPLOYMENT_ENVIRONMENT} current-version=${VERSION} age=${AGE_DAYS}d SLA=${MAX_AGE_DAYS}d"

aws cloudwatch put-metric-data \
    --region "$AWS_REGION" \
    --namespace "$METRIC_NAMESPACE" \
    --metric-name IndexAgeDays \
    --unit Count \
    --value "$AGE_DAYS" \
    --dimensions "Environment=${DEPLOYMENT_ENVIRONMENT}" >/dev/null

if (( AGE_DAYS > MAX_AGE_DAYS )); then
    echo "[staleness] STALE: reference '${VERSION}' is ${AGE_DAYS} days old (SLA ${MAX_AGE_DAYS})" >&2
    [[ "${REPORT_ONLY:-}" == "1" ]] && exit 0
    exit 1
fi
echo "[staleness] OK"
