#!/bin/bash
#
# reference_index_rollback.sh -- blue/green ROLLBACK for the NT/NR sequence index.
#
# The sequence-DB mirror of `rake taxonomy:cutover_rollback`: flip the current
# index-version pointer BACK to the previous version. Instant, no data moved --
# the prior dated prefix is immutable and still present in S3, so re-pointing is
# all it takes. Swaps current <-> previous so a rollback is itself reversible.
#
# Usage:
#   DEPLOYMENT_ENVIRONMENT=dev scripts/reference_index_rollback.sh
#   DEPLOYMENT_ENVIRONMENT=dev scripts/reference_index_rollback.sh 2024-02-06   # explicit target
#
# Env:
#   DEPLOYMENT_ENVIRONMENT  (required)
#   AWS_REGION              (optional, default us-west-2)

set -euo pipefail

: "${DEPLOYMENT_ENVIRONMENT:?set DEPLOYMENT_ENVIRONMENT (dev|staging|prod|sandbox)}"
AWS_REGION="${AWS_REGION:-us-west-2}"
PREFIX="/seqtoid/${DEPLOYMENT_ENVIRONMENT}/reference-index"

ssm_get() { aws ssm get-parameter --region "$AWS_REGION" --name "$1" --query 'Parameter.Value' --output text; }
ssm_put() { aws ssm put-parameter --region "$AWS_REGION" --name "$1" --value "$2" --type String --overwrite >/dev/null; }

CURRENT="$(ssm_get "${PREFIX}/current-version")"
PREVIOUS="$(ssm_get "${PREFIX}/previous-version")"

# An explicit target overrides the stored previous pointer.
TARGET="${1:-$PREVIOUS}"

if [[ -z "$TARGET" || "$TARGET" == "-" ]]; then
    echo "[rollback] no previous version recorded (previous-version is unset) and no explicit target given." >&2
    echo "  Usage: DEPLOYMENT_ENVIRONMENT=${DEPLOYMENT_ENVIRONMENT} $(basename "$0") <version>" >&2
    exit 2
fi
if [[ "$TARGET" == "$CURRENT" ]]; then
    echo "[rollback] current is already '${CURRENT}'; nothing to do."
    exit 0
fi

echo "[rollback] restoring current NT/NR index: '${CURRENT}' -> '${TARGET}' (env=${DEPLOYMENT_ENVIRONMENT})"
ssm_put "${PREFIX}/previous-version" "$CURRENT"   # keep the just-rolled-back version as the new rollback target
ssm_put "${PREFIX}/current-version" "$TARGET"
echo "[rollback] DONE. New runs resolve to '${TARGET}' again."
