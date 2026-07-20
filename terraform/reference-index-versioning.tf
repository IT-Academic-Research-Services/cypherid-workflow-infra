# =============================================================================
# Lever-1 GR-7 -- NT/NR sequence-DB blue/green + backups + rollback.
# -----------------------------------------------------------------------------
# This is the VERSIONING / PROMOTION layer for the expensive NT/NR reference
# index (index-generation output). It is the sequence-DB mirror of the taxon-
# LINEAGE blue/green that already shipped in the web app:
#
#   lineage (shipped)                     sequence DB (this file)
#   -----------------------------------   -----------------------------------
#   default AlignmentConfig name          SSM /reference-index/current-version
#     (AppConfig DB row, flipped at         (flipped out-of-band by the promote/
#      runtime by taxonomy:cutover)          rollback scripts; TF ignores value)
#   register a new AlignmentConfig        replicate a new dated prefix (GR-2..6)
#   cutover = flip default (instant)      promote = flip SSM pointer (instant)
#   cutover_rollback = flip back          rollback = flip SSM pointer back
#   old table taxon_lineages_bak_<ts>     prior dated prefix kept immutable in S3
#   taxonomy:staleness CronJob + SLA      IndexAgeDays metric + staleness alarm
#
# WHY the pointer lives in SSM (not the web AlignmentConfig row): for lineage the
# reference is a DB table, so the pointer is naturally an AppConfig row. For the
# NT/NR sequence DB the reference is S3 artifacts consumed by the pipeline, and
# the promotion decision (which dated prefix is "current") is an infra concern
# resolved before a run is dispatched. An SSM parameter is the terraform-native,
# atomically-updatable pointer the replication/promote flow (GR-5/GR-6) reads and
# writes, and that the web AlignmentConfig registration can mirror. Flipping one
# parameter is atomic and instantly reversible -- exactly the lineage cutover
# property. Historical runs stay pinned to the AlignmentConfig they ran with, so
# a flip never rewrites a past result (same guarantee as lineage).
#
# WHAT STANDS ALONE (delivered, applies without the replication flow):
#   - the three SSM pointer parameters (current / previous / major version)
#   - the staleness alarm (off by default until the probe publishes the metric)
#   - the promote / rollback / staleness / prune operational scripts
# WHAT IS SCAFFOLDED (documented, disabled by default -- honest about deps):
#   - the AUPR-gated automatic flip: promote asserts an AUPR-PASS marker that the
#     benchmark gate (GR-6) writes; that marker producer is not built yet, so the
#     promote script fails closed if the marker is absent (see the script).
#   - the S3 lifecycle backup-retention config: gated on the env owning its own
#     per-account reference bucket (GR-8); count=0 until then.
#
# Authored, NOT applied. No AWS job is triggered by anything here.
# See LEVER1-SEQUENCE-DB-BLUEGREEN-DESIGN.md for the full runbook.
# =============================================================================

locals {
  # SSM parameter namespace for the reference-index pointers, per env.
  # Chosen to NOT begin with "aws"/"ssm" so the moto-backed test env accepts it
  # (see the note on data.aws_ssm_parameter.idseq_batch_ami in index-generation.tf).
  reference_index_ssm_prefix = "/seqtoid/${var.DEPLOYMENT_ENVIRONMENT}/reference-index"
}

# --- The "current index version" pointer (the blue/green flip target) --------
# This is the sequence-DB analog of the default AlignmentConfig name. Terraform
# OWNS the parameter's existence and SEEDS its initial value; the value itself is
# flipped at promotion/rollback time by scripts/reference_index_{promote,rollback}.sh
# via `aws ssm put-parameter --overwrite`. lifecycle.ignore_changes[value] keeps a
# later `terraform apply` from reverting an operational flip -- the same division
# of ownership as the lineage pointer (TF/seed owns existence, ops owns the live
# value). tier=Standard, type=String: a short version string, not a secret.
resource "aws_ssm_parameter" "reference_index_current_version" {
  name        = "${local.reference_index_ssm_prefix}/current-version"
  description = "Currently-serving NT/NR index-generation version (dated prefix segment). Flipped by the promote/rollback scripts; blue/green cutover pointer."
  type        = "String"
  value       = var.reference_index_current_version

  tags = {
    managed_by = "terraform"
    component  = "reference-index-versioning"
    env        = var.DEPLOYMENT_ENVIRONMENT
  }

  lifecycle {
    # Operational promote/rollback owns the live value; do not revert it on apply.
    ignore_changes = [value]
  }
}

# --- The rollback target pointer (previous serving version) ------------------
# Promote copies current -> previous BEFORE overwriting current, so rollback is a
# single atomic flip back. Mirrors how lineage cutover prints the previous name
# for `taxonomy:cutover_rollback`.
resource "aws_ssm_parameter" "reference_index_previous_version" {
  name        = "${local.reference_index_ssm_prefix}/previous-version"
  description = "Prior NT/NR index-generation version retained as the fast rollback target. Set by the promote script; consumed by the rollback script."
  type        = "String"
  # An empty string is not a valid SSM value; seed a single "-" sentinel meaning
  # "no previous version yet" (the scripts treat "-" as unset).
  value = var.reference_index_previous_version == "" ? "-" : var.reference_index_previous_version

  tags = {
    managed_by = "terraform"
    component  = "reference-index-versioning"
    env        = var.DEPLOYMENT_ENVIRONMENT
  }

  lifecycle {
    ignore_changes = [value]
  }
}

# --- The major-version segment of the artifact prefix ------------------------
# Fully identifies the serving prefix ncbi-indexes-<env>/<version>/index-generation-<major>/
# without any path parsing at the consumer. Rarely changes (only on a new
# index-generation format), so this one is TF-managed end to end (no ignore).
resource "aws_ssm_parameter" "reference_index_major_version" {
  name        = "${local.reference_index_ssm_prefix}/major-version"
  description = "index-generation major-version segment of the serving artifact prefix (index-generation-<major>)."
  type        = "String"
  value       = var.reference_index_major_version

  tags = {
    managed_by = "terraform"
    component  = "reference-index-versioning"
    env        = var.DEPLOYMENT_ENVIRONMENT
  }
}

# --- Staleness alarm (the reference-age SLA) ---------------------------------
# Mirror of the lineage `taxonomy:staleness` CronJob. The NT/NR sequence index is
# rebuilt ~annually, so the SLA is far longer than the quarterly lineage SLA.
#
# CloudWatch has no native "S3 prefix age" metric, so the age is published by a
# scheduled probe (scripts/reference_index_staleness.sh, run as a CronJob /
# scheduled job) that reads the current-version pointer, parses its date, and
# emits IndexAgeDays. This alarm watches that metric. treat_missing_data =
# "breaching": if the probe stops reporting we do NOT know the age, which is
# itself an SLA failure (same intent as the rake task's non-zero exit on an
# unparseable/absent version). Reuses the existing pipeline-alerts SNS wiring
# (local.pipeline_alarm_actions, defined in cloudwatch-alarms.tf).
#
# Off by default (see var.enable_reference_index_staleness_alarm): enabling it
# before the probe publishes the metric would breach immediately on missing data.
resource "aws_cloudwatch_metric_alarm" "reference_index_staleness" {
  count = var.enable_reference_index_staleness_alarm ? 1 : 0

  alarm_name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-reference-index-staleness"
  alarm_description = "The serving NT/NR sequence index is older than the ${var.reference_index_staleness_max_age_days}-day SLA (or the staleness probe stopped reporting) -- pipeline ${var.DEPLOYMENT_ENVIRONMENT}."

  namespace   = var.reference_index_staleness_metric_namespace
  metric_name = "IndexAgeDays"
  dimensions  = { Environment = var.DEPLOYMENT_ENVIRONMENT }

  statistic           = "Maximum"
  period              = 86400 # once a day is plenty for an ~annual asset
  evaluation_periods  = 1
  threshold           = var.reference_index_staleness_max_age_days
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"

  alarm_actions = local.pipeline_alarm_actions
  ok_actions    = local.pipeline_alarm_actions
}

# --- Backup retention on the reference bucket (SCAFFOLD, gated) ---------------
# Immutable dated prefixes are the primary backup: a superseded index version is
# never overwritten, so rollback = re-point the SSM pointer at a prefix that is
# still present. This lifecycle config only adds COST CONTROL: after the archive
# window (comfortably beyond the rollback window) old index-version objects
# transition to cold storage. It deliberately does NOT expire/delete anything --
# deleting a version an env might still serve or roll back to would be
# catastrophic, so pruning old VERSIONS is an explicit operational runbook step
# (scripts/reference_index_prune.sh), never a blind lifecycle expiry.
#
# GATED (count=0 unless BOTH): the env has opted in AND it owns its own
# per-account reference bucket (PUBLIC_REFERENCES_BUCKET_NAME set). The shared
# reference bucket is a data source, not TF-owned (buckets.tf), so a lifecycle
# config must not target it -- it belongs to whoever created it, and managing it
# here would be a cross-owner change on a live multi-TB bucket. Activates per env
# only after the GR-8 migration to a TF-owned per-account bucket.
resource "aws_s3_bucket_lifecycle_configuration" "reference_index_backup_retention" {
  count = var.manage_reference_index_lifecycle && var.PUBLIC_REFERENCES_BUCKET_NAME != "" ? 1 : 0

  bucket = local.s3_bucket_public_references

  rule {
    id     = "archive-old-index-versions"
    status = "Enabled"

    filter {
      prefix = "ncbi-indexes-"
    }

    transition {
      days          = var.reference_index_archive_transition_days
      storage_class = var.reference_index_archive_storage_class
    }

    # No expiration: retention/pruning of superseded index VERSIONS is an
    # operational decision (reference_index_prune.sh), never automatic deletion.
  }
}
