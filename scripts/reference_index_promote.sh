#!/bin/bash
#
# reference_index_promote.sh -- blue/green PROMOTE for the NT/NR sequence index.
#
# The sequence-DB mirror of the lineage `rake taxonomy:cutover`: flip the
# "current index version" SSM pointer to a new dated version so NEW pipeline runs
# resolve to it. Instant and fully reversible (reference_index_rollback.sh flips
# back). The previous version is saved to the previous-version pointer first, so
# rollback is a single atomic flip.
#
# FAIL-CLOSED AUPR GATE (mirrors the lineage "benchmark AUPR >= 0.98 before
# cutover" rule): promotion refuses unless an AUPR-PASS marker exists for the
# EXACT version being promoted. That marker is written by the benchmark gate
# (design phase GR-6), keyed on <version>/<major> so a stale pass cannot
# green-light a different build. GR-6's marker producer is not built yet, so
# today this gate blocks until the marker is written by hand or by GR-6; set
# ALLOW_UNVERIFIED=1 ONLY for a documented dev dry-run. NOTHING here builds or
# copies an index -- it only flips the pointer once the artifacts + gate exist.
#
# Usage:
#   DEPLOYMENT_ENVIRONMENT=dev scripts/reference_index_promote.sh 2026-08-01
#   AWS_REGION=us-west-2 DEPLOYMENT_ENVIRONMENT=dev scripts/reference_index_promote.sh 2026-08-01
#
# Env:
#   DEPLOYMENT_ENVIRONMENT  (required)  which env's pointer to flip
#   AWS_REGION              (optional)  defaults to us-west-2
#   ALLOW_UNVERIFIED        (optional)  "1" bypasses the AUPR-PASS marker (dev dry-run only)

set -euo pipefail

if [[ $# != 1 ]]; then
    echo "Promote (blue/green cutover) the NT/NR sequence index to a new version."
    echo
    echo "Usage: $(basename "$0") <new-version>"
    echo "Example: DEPLOYMENT_ENVIRONMENT=dev $(basename "$0") 2026-08-01"
    exit 1
fi

NEW_VERSION="$1"
: "${DEPLOYMENT_ENVIRONMENT:?set DEPLOYMENT_ENVIRONMENT (dev|staging|prod|sandbox)}"
AWS_REGION="${AWS_REGION:-us-west-2}"
PREFIX="/seqtoid/${DEPLOYMENT_ENVIRONMENT}/reference-index"

ssm_get() { aws ssm get-parameter --region "$AWS_REGION" --name "$1" --query 'Parameter.Value' --output text; }
ssm_put() { aws ssm put-parameter --region "$AWS_REGION" --name "$1" --value "$2" --type String --overwrite >/dev/null; }

CURRENT="$(ssm_get "${PREFIX}/current-version")"
MAJOR="$(ssm_get "${PREFIX}/major-version")"

if [[ "$CURRENT" == "$NEW_VERSION" ]]; then
    echo "[promote] current is already '${NEW_VERSION}'; nothing to do."
    exit 0
fi

# --- AUPR-PASS gate (fail-closed) --------------------------------------------
# The marker is an SSM parameter the benchmark gate (GR-6) writes on a passing
# per-sample AUPR >= 0.98 run, keyed on the exact version+major being promoted.
MARKER="${PREFIX}/aupr-pass/index-generation-${MAJOR}/${NEW_VERSION}"
if [[ "${ALLOW_UNVERIFIED:-}" == "1" ]]; then
    echo "[promote] WARNING: ALLOW_UNVERIFIED=1 -- skipping the AUPR-PASS gate (dev dry-run only)."
else
    if ! MARKER_VAL="$(ssm_get "$MARKER" 2>/dev/null)"; then
        echo "[promote] REFUSED: no AUPR-PASS marker at ${MARKER}" >&2
        echo "  The benchmark gate (design phase GR-6) must record a passing AUPR >= 0.98 run for" >&2
        echo "  index-generation-${MAJOR}/${NEW_VERSION} before it can be promoted. Fail-closed." >&2
        exit 2
    fi
    echo "[promote] AUPR-PASS marker present for ${NEW_VERSION} (${MARKER_VAL})."
fi

echo "[promote] flipping current NT/NR index: '${CURRENT}' -> '${NEW_VERSION}' (env=${DEPLOYMENT_ENVIRONMENT})"
ssm_put "${PREFIX}/previous-version" "$CURRENT"   # save the rollback target FIRST
ssm_put "${PREFIX}/current-version" "$NEW_VERSION"
echo "[promote] DONE. New runs resolve to '${NEW_VERSION}'; existing runs stay pinned to their AlignmentConfig."
echo "  Rollback (instant): DEPLOYMENT_ENVIRONMENT=${DEPLOYMENT_ENVIRONMENT} scripts/reference_index_rollback.sh"
