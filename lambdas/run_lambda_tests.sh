#!/usr/bin/env bash
# Local test harness for the Chalice lambdas (cypherid-workflow-infra).
#
# Proves the modernized Python runtime + bumped deps (boto3, opensearch-py,
# aws-lambda-powertools) do not break lambda code. The unit suites are pure
# (pytest-mock; no live AWS), so a clean venv fully exercises them.
#
# Usage:   lambdas/run_lambda_tests.sh
#          PYTHON=python3.12 lambdas/run_lambda_tests.sh   # pin an interpreter
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.12 python3.11 python3; do command -v "$c" >/dev/null 2>&1 && PY="$c" && break; done
fi
[ -n "$PY" ] || { echo "no python3 found"; exit 2; }
echo ">> interpreter: $("$PY" --version 2>&1)"

# Lambdas that ship a unit-test suite (extend as more gain tests).
# The suites are pure (no live AWS); the sfn-io-helper and cloudwatch-alerting
# suites cover only chalicelib logic that never imports the chalice framework,
# so they are unaffected by the chalice/py312 packaging blocker (CZID-443).
#
# Each suite carries a per-suite line-coverage FLOOR (CZID-749). The floor is a
# RATCHET, not an aspiration: it is set one point BELOW the coverage measured at
# the time it was introduced, so it only ever fails a change that REMOVES covered
# code without covering it (a regression), mirroring seqtoid-web's coverage
# philosophy. Coverage is scoped to `chalicelib` (the unit-testable package);
# `app.py` imports the chalice framework and is never imported by these unit
# suites, so including it would only add spurious 0% noise. The absolute numbers
# are low because untested boilerplate lives in-package (sentry_init.py,
# es_queries.py, batch_events.py, reporting.py); raising them is future work,
# but the floor guarantees they cannot silently drop. To raise a floor, measure
# the new coverage and set the floor one point below it.
#
# TESTED and FLOORS are parallel arrays: FLOORS[i] is the floor for TESTED[i].
TESTED=(taxon-indexing-eviction sfn-io-helper cloudwatch-alerting)
FLOORS=(61                      14            22)

rc=0
i=0
for d in "${TESTED[@]}"; do
  floor="${FLOORS[$i]}"
  i=$((i + 1))
  echo ">> testing: $d (coverage floor: ${floor}%)"
  venv="$(mktemp -d)/v"
  "$PY" -m venv "$venv"
  # shellcheck disable=SC1091
  . "$venv/bin/activate"
  pip install -q --upgrade pip
  # Install the lambda's runtime deps EXCLUDING chalice (packaging-only,
  # tracked separately under SEQTOID-131) plus the test tooling.
  reqs="$(mktemp)"
  grep -v '^chalice' "$d/requirements.txt" > "$reqs" || true
  pip install -q -r "$reqs" pytest pytest-mock pytest-cov
  # config.py reads DEPLOYMENT_ENVIRONMENT at import; the suite mocks SSM/params
  # itself, so the single var is all the unit tests need (don't source
  # environment.test -- it makes live aws sts/iam calls).
  # --cov-fail-under makes pytest exit non-zero if coverage drops below the floor.
  ( cd "$d" && DEPLOYMENT_ENVIRONMENT=test AWS_DEFAULT_REGION=us-west-2 \
      python -m pytest test/ -q \
        --cov=chalicelib --cov-report=term-missing \
        --cov-fail-under="$floor" ) || rc=1
  deactivate
done

[ "$rc" -eq 0 ] && echo ">> ALL LAMBDA TESTS PASSED" || echo ">> LAMBDA TESTS FAILED"
exit $rc
