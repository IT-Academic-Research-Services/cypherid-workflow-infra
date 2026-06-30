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
TESTED=(taxon-indexing-eviction)

rc=0
for d in "${TESTED[@]}"; do
  echo ">> testing: $d"
  venv="$(mktemp -d)/v"
  "$PY" -m venv "$venv"
  # shellcheck disable=SC1091
  . "$venv/bin/activate"
  pip install -q --upgrade pip
  # Install the lambda's runtime deps EXCLUDING chalice (packaging-only,
  # tracked separately under SEQTOID-131) plus the test tooling.
  reqs="$(mktemp)"
  grep -v '^chalice' "$d/requirements.txt" > "$reqs" || true
  pip install -q -r "$reqs" pytest pytest-mock
  # config.py reads DEPLOYMENT_ENVIRONMENT at import; the suite mocks SSM/params
  # itself, so the single var is all the unit tests need (don't source
  # environment.test — it makes live aws sts/iam calls).
  ( cd "$d" && DEPLOYMENT_ENVIRONMENT=test AWS_DEFAULT_REGION=us-west-2 \
      python -m pytest test/ -q ) || rc=1
  deactivate
done

[ "$rc" -eq 0 ] && echo ">> ALL LAMBDA TESTS PASSED" || echo ">> LAMBDA TESTS FAILED"
exit $rc
