#!/bin/bash
#
# reference_index_prune.sh -- operational retention for OLD NT/NR index versions.
#
# Retention is deliberately an OPERATIONAL step, not a blind S3 lifecycle expiry:
# deleting an index version an env still serves or might roll back to would be
# catastrophic. This script lists the dated index versions in the reference
# bucket, keeps the newest RETAIN_COUNT of them PLUS the pointer-referenced
# current and previous versions (the rollback target), and prints what falls
# outside retention. It DELETES NOTHING unless CONFIRM=1 is set -- dry-run first,
# always. The immutable dated prefixes are the primary backup; this only reclaims
# storage from versions well past the rollback window.
#
# Usage (dry-run):
#   DEPLOYMENT_ENVIRONMENT=dev BUCKET=seqtoid-public-references-dev-<acct> \
#     scripts/reference_index_prune.sh
#   ... then re-run with CONFIRM=1 to actually delete.
#
# Env:
#   DEPLOYMENT_ENVIRONMENT  (required)
#   BUCKET                  (required)  the per-account reference bucket
#   AWS_REGION              (optional, default us-west-2)
#   RETAIN_COUNT            (optional, default 3)  newest N versions always kept
#   CONFIRM                 (optional, "1" to actually delete; otherwise dry-run)

set -euo pipefail

: "${DEPLOYMENT_ENVIRONMENT:?set DEPLOYMENT_ENVIRONMENT}"
: "${BUCKET:?set BUCKET (the per-account reference bucket)}"
AWS_REGION="${AWS_REGION:-us-west-2}"
RETAIN_COUNT="${RETAIN_COUNT:-3}"
PREFIX="/seqtoid/${DEPLOYMENT_ENVIRONMENT}/reference-index"
INDEX_ROOT="ncbi-indexes-${DEPLOYMENT_ENVIRONMENT}/"

CURRENT="$(aws ssm get-parameter --region "$AWS_REGION" --name "${PREFIX}/current-version" --query 'Parameter.Value' --output text)"
PREVIOUS="$(aws ssm get-parameter --region "$AWS_REGION" --name "${PREFIX}/previous-version" --query 'Parameter.Value' --output text)"

# The dated version "directories" one level under the index root.
mapfile -t VERSIONS < <(
    aws s3api list-objects-v2 --region "$AWS_REGION" --bucket "$BUCKET" \
        --prefix "$INDEX_ROOT" --delimiter / \
        --query 'CommonPrefixes[].Prefix' --output text 2>/dev/null | tr '\t' '\n' |
        sed "s#^${INDEX_ROOT}##; s#/\$##" | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -r
)

if (( ${#VERSIONS[@]} == 0 )); then
    echo "[prune] no dated versions found under s3://${BUCKET}/${INDEX_ROOT}"
    exit 0
fi

echo "[prune] env=${DEPLOYMENT_ENVIRONMENT} bucket=${BUCKET} retain_newest=${RETAIN_COUNT}"
echo "[prune] protected pointers: current=${CURRENT} previous=${PREVIOUS}"

KEEP=("${VERSIONS[@]:0:RETAIN_COUNT}" "$CURRENT" "$PREVIOUS")
is_kept() { local v="$1"; for k in "${KEEP[@]}"; do [[ "$k" == "$v" ]] && return 0; done; return 1; }

for v in "${VERSIONS[@]}"; do
    if is_kept "$v"; then
        echo "  KEEP   ${v}"
    else
        echo "  PRUNE  ${v}"
        if [[ "${CONFIRM:-}" == "1" ]]; then
            aws s3 rm --region "$AWS_REGION" --recursive "s3://${BUCKET}/${INDEX_ROOT}${v}/"
            echo "         deleted s3://${BUCKET}/${INDEX_ROOT}${v}/"
        fi
    fi
done

[[ "${CONFIRM:-}" == "1" ]] || echo "[prune] DRY-RUN (set CONFIRM=1 to delete the PRUNE-marked versions)."
