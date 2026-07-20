# =============================================================================
# Lever-1 GR-7 -- NT/NR sequence-DB blue/green: variables for the versioning /
# promotion layer (the "current index version" pointer, staleness SLA, backup
# retention). Split into its own *-variables.tf per the repo convention
# (see cloudwatch-alarms-variables.tf). All defaults are chosen so a plan with
# nothing set is byte-identical to before EXCEPT the three SSM pointer params,
# which are the standalone deliverable (they seed the current serving version).
#
# See LEVER1-SEQUENCE-DB-BLUEGREEN-DESIGN.md and
# LEVER1-GENERATE-ONCE-REPLICATE-DESIGN.md (phase GR-7).
# =============================================================================

variable "reference_index_current_version" {
  description = "The dated index-generation version currently SERVING in this env (e.g. 2024-02-06). Seeds the SSM current-version pointer. Operational promote/rollback flips the SSM value out-of-band (terraform ignores value changes), mirroring how the lineage default AlignmentConfig is flipped at runtime, not in TF."
  type        = string
  default     = "2024-02-06"
}

variable "reference_index_previous_version" {
  description = "The prior index-generation version retained as the fast rollback target (empty until a first promotion happens). Seeds the SSM previous-version pointer."
  type        = string
  default     = ""
}

variable "reference_index_major_version" {
  description = "The index-generation major version segment of the artifact prefix (ncbi-indexes-<env>/<date>/index-generation-<major>/). Kept as a pointer so the serving prefix is fully identified without parsing paths elsewhere."
  type        = string
  default     = "2"
}

variable "reference_index_staleness_max_age_days" {
  description = "Staleness SLA for the serving NT/NR sequence index, in days. The NT/NR rebuild is ~annual, so this is far larger than the quarterly lineage SLA (92). Alarm fires when the published IndexAgeDays metric exceeds this, OR when the metric is missing (the staleness probe stopped reporting)."
  type        = number
  default     = 400
}

variable "reference_index_staleness_metric_namespace" {
  description = "CloudWatch namespace the staleness probe publishes IndexAgeDays into (scripts/reference_index_staleness.sh). The alarm reads the same namespace."
  type        = string
  default     = "Seqtoid/Reference"
}

variable "enable_reference_index_staleness_alarm" {
  description = "Toggle the sequence-index staleness alarm. Off by default so no alarm is created until the staleness probe (CronJob / scheduled job publishing IndexAgeDays) is wired in an env; turning it on before the probe reports would immediately breach on missing data."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Backup retention on the reference bucket. SCAFFOLD -- disabled by default and
# gated on the env owning its OWN per-account reference bucket. The shared
# reference bucket is a terraform DATA SOURCE (buckets.tf), not a TF-owned
# resource, on purpose: it holds many TB of live taxon indexes and converting it
# to a managed resource risks a destroy/recreate. A lifecycle configuration can
# only be safely applied once the env has migrated to its own TF-owned bucket
# (GR-8). Until then this stays count=0 (byte-identical plan). See the design doc
# "Backup retention" section for why pruning old index VERSIONS is an operational
# runbook step (scripts/reference_index_prune.sh), not a blind lifecycle expiry.
# ---------------------------------------------------------------------------
variable "manage_reference_index_lifecycle" {
  description = "Opt-in to manage an S3 lifecycle configuration on the per-account reference bucket for cost-control transitions of OLD index versions. Requires PUBLIC_REFERENCES_BUCKET_NAME to be set (the env owns its own bucket). Default false = no lifecycle managed (byte-identical plan; the shared data-source bucket is never touched)."
  type        = bool
  default     = false
}

variable "reference_index_archive_transition_days" {
  description = "Age (days) after which index-version objects transition to a colder storage class for cost control. Comfortably beyond the rollback window so a rollback target is never archived. Only used when manage_reference_index_lifecycle = true."
  type        = number
  default     = 180
}

variable "reference_index_archive_storage_class" {
  description = "Cold storage class for aged index-version objects (GLACIER or DEEP_ARCHIVE). DEEP_ARCHIVE is cheapest but has multi-hour restore; acceptable for a superseded, non-serving index version kept only as a deep backup."
  type        = string
  default     = "DEEP_ARCHIVE"
}
