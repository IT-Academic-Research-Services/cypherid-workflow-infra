# Lever 4 cadence -- taxonomy snapshot pin + refresh_scope (platform-overhaul #802)

Companion to the fan-out (Lever 2). What is IMPLEMENTED in this branch, and the one residual
that is deploy-gated.

## Implemented (start_index_generation_lambda_src/main.py + tests)

### 1. Taxonomy snapshot pin (#778/#747)
NCBI FTP only serves the CURRENT taxonomy, so a rebuild that reads live NCBI is not
reproducible. New event override `index_generation.taxonomy_snapshot_prefix` (an S3 key
prefix under the references bucket, or a full `s3://` URI) repoints the taxonomy lane at a
held snapshot: the lambda passes the five sources (`nucl_gb`, `nucl_wgs`, `pdb`,
`prot.FULL`, `taxdump`) to the `download-taxonomy` sub-WDL, which already accepts each as an
overridable URI. Unset => live NCBI (unchanged default).

Operational companion (not code): stage the snapshot once with the same `.gz` filenames, e.g.
`s3://seqtoid-public-references/ncbi-indexes-dev/taxonomy-snapshots/<date>/`. That is the
"snapshot-and-hold" pin; the code consumes it.

### 2. refresh_scope (full / nt_only / nr_only / lineage_only)
New override `index_generation.refresh_scope` (default `full`). An out-of-scope DB lane
reuses the prior run's compressed fasta (`provided_*` = prior `*_compressed.fa`) and skips
(re)compression (`skip_*_compression = true`), so a scoped refresh pays neither the download
nor the compress pole for a DB it is not refreshing. `full` is unchanged (still seeds the
incremental compress from the prior compressed as before). Invalid values are rejected. An
explicit `provided_*` / `skip_*` override always wins over the scope default. If no prior
compressed artifact exists, the lane falls back to a full build (correct, just not skipped).

Covered by `test_main_lever4.py` (no AWS): per-mode input mapping, snapshot pin (prefix and
full-URI forms), explicit-override precedence, invalid-scope rejection.

## Residual (DEPLOY-GATED follow-on, NOT built)

refresh_scope today still *runs* the out-of-scope lane's index step (it rebuilds the index
from the reused, unchanged compressed fasta) so the artifact set stays complete. To truly
"skip whole lanes" -- not schedule the Batch job at all and reuse the prior INDEX directory
(minimap2 / diamond / loc / info) -- requires:

- SFN template: wrap each Phase-2 lane's `StartAt` in a `Choice` on a per-lane
  `<Lane>InScope` boolean; the false arm is a `Pass` that publishes the prior run's index
  output URIs as that lane's Result.
- io-helper: pre-seed the accumulated Result with those prior output URIs so `MergeLanes` /
  `Assemble` resolve them by bare name (the DAG handoff map is unchanged).
- register: `alignment_config_register` already derives every path from the version dir and
  `head_object`-validates each artifact exists; a scoped build must copy or hardlink the
  reused prior index artifacts into the new dated prefix so the new AlignmentConfig is
  self-contained (immutability -- never repoint a config at another version's dir).

This cannot be validated locally (Rosetta wall) and touches the not-yet-deployed fan-out, so
it is held until the fan-out is deployed + the full-scope validation run is green.
