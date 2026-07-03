# type: ignore
#
# DRY-labeled shared snippet: this file is intentionally IDENTICAL across every
# chalice lambda in cypherid-workflow-infra (cloudwatch-alerting,
# pipeline-monitor-restarter, sfn-io-helper, taxon-indexing,
# taxon-indexing-eviction). Each chalice app is Docker-packaged from its own
# directory, so a single importable module cannot be shared across the separate
# packages; the copies are kept in lockstep. Edit them together.
#
# Mirrors the Rails app's Sentry config (config/initializers/sentry.rb): it
# reuses the SAME DSN (SENTRY_DSN_BACKEND) so Lambda errors land in the same
# Sentry project, tags events with the deploy environment, and only sends in the
# real deploy environments. Without this, unhandled Lambda errors die silently
# in CloudWatch (e.g. the heatmap ES timeout was invisible).

import logging
import os

logger = logging.getLogger()

# Environments that should send events, mirroring the Rails initializer's
# config.environments (['sandbox', 'staging', 'prod', 'dev', 'development']).
_REPORTING_ENVIRONMENTS = {"sandbox", "staging", "prod", "dev", "development"}

_initialized = False


def _resolve_dsn():
    """
    Resolve the backend Sentry DSN, giving priority to the environment variable
    (SENTRY_DSN_BACKEND) and falling back to the same /idseq-{env}-web/ SSM path
    the other parameters are read from. Returns None when no DSN is configured.
    """
    dsn = os.environ.get("SENTRY_DSN_BACKEND")
    if dsn:
        return dsn

    # Fall back to SSM, matching how the lambdas read /idseq-{env}-web/* config.
    # Never do this in local/CLI mode (no AWS creds / not desired).
    if "LOCAL_MODE" in os.environ or "AWS_CHALICE_CLI_MODE" in os.environ:
        return None

    deployment_environment = os.environ.get("DEPLOYMENT_ENVIRONMENT")
    if not deployment_environment:
        return None

    try:
        import boto3

        parameter_name = f"/idseq-{deployment_environment}-web/SENTRY_DSN_BACKEND"
        response = boto3.client("ssm").get_parameters(
            Names=[parameter_name], WithDecryption=True
        )
        for parameter in response["Parameters"]:
            if parameter["Value"]:
                return parameter["Value"]
    except Exception as e:  # pragma: no cover - best-effort, never break the lambda
        logger.warning("Could not resolve SENTRY_DSN_BACKEND from SSM: %s", e)

    return None


def init_sentry():
    """
    Initialize the Sentry SDK for this Lambda, if a DSN is configured and we are
    running in a real deploy environment. Safe to call multiple times and safe to
    call when Sentry is not configured (it simply no-ops). Callers should still
    guard against AWS_CHALICE_CLI_MODE so chalice codegen/CLI does not init.
    """
    global _initialized
    if _initialized:
        return

    deployment_environment = os.environ.get("DEPLOYMENT_ENVIRONMENT")
    if deployment_environment not in _REPORTING_ENVIRONMENTS:
        # Mirrors the Rails guard: only send from the real deploy environments
        # (skips local/test and anything unset).
        return

    dsn = _resolve_dsn()
    if not dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=deployment_environment,
        integrations=[AwsLambdaIntegration()],
        # Error reporting only; no performance tracing (mirrors the Rails setup).
        traces_sample_rate=0,
    )
    _initialized = True


def capture_exception(error):
    """
    Send a handled exception to Sentry. Safe no-op when Sentry is not
    initialized or the SDK is unavailable (e.g. local/CLI runs), so operational
    failures that are otherwise only logged/raised can still be made visible in
    Sentry without risk of breaking the Lambda.
    """
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(error)
    except Exception as e:  # pragma: no cover - never let reporting break the job
        logger.warning("Could not report exception to Sentry: %s", e)
