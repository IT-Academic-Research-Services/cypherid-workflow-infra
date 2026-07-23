# Index-generation download split: per-database compute + volume (platform-overhaul #799)

Split the single `download` stage into three concurrent per-database stages so core_nt,
nr, and the taxonomy files download **at the same time on separate boxes with isolated
disks**. Fixes the two problems that killed run `index-generation-core-nt-s3-192600`:
serialized nt-behind-nr, and nr's `nr.fsa` filling the shared scratch so core_nt died
("Need 269326843136 bytes, only 144753012736 available").

## Why (from the failed run)
- One `download` stage ran update_blastdb.pl + `blastdbcmd -out <db>.fsa` for core_nt AND
  nr AND taxonomy on ONE 8-vCPU box, ONE scratch volume.
- nr ran ~7.4h; core_nt then pended "insufficient resources on 1 node" and, when it did
  start, failed out-of-disk because nr.fsa had consumed the volume.
- Splitting per-database: wall-clock drops from `taxonomy + nr + nt` (~15h) to
  `max(taxonomy, nr, nt)` (~7.5h), and disk exhaustion is impossible (isolated volumes).
- **Resume already exists**: `swipe.tf` sets `call_cache = true` -> miniwdl S3 call cache
  (PUT/GET). Once split, nr/nt/taxonomy are independent cached stages, so a re-run after a
  partial failure skips the succeeded stages and re-runs only the failed one.

## Status: infra foundation BUILT (held); routing is step 2
This branch (`index-gen-split-nt-nr-download`) implements the compute+volume foundation.
The SFN/lambda/WDL routing that activates it is specified below and is the completing
increment -- it **requires a dev apply + one validation index run** (the multi-stage SFN
cannot be locally test-applied: Rosetta wall, and the io-helper contract is exercised only
at runtime). Held as a draft PR; nothing applies until deliberately run.

## Step 1 -- DONE here (compute + volume)
- `terraform/index-generation.tf`: `index_generation_stages_base` gains `download_taxonomy`
  (512 GB scratch), `download_nt` (1536 GB), `download_nr` (2048 GB) -- each an 8-vCPU box
  (c6i.2xlarge / m7g.2xlarge) with its OWN gp3 scratch volume. The `for_each` over the stage
  map auto-generates a launch template + compute environment + queue per entry, so these
  three get isolated compute + disk for free. The old `download` stage is retained (additive)
  until step 2 switches routing off it, then it is deleted.
- `terraform/swipe.tf`: `extra_template_vars` gains
  `index_generation_download_{taxonomy,nt,nr}_job_queue_arn` so the SFN template can route
  each branch to its queue.

Volume sizing rationale: nr is the largest (compressed volumes + full nr.fsa) -> 2 TB;
core_nt smaller -> 1.5 TB; taxonomy (accession2taxid incl prot.FULL ~23.6GB + taxdump) ->
512 GB. gp3, IO-bound, cheap. Cores can be right-sized after a profiling run if the nr
`blastdbcmd` extraction (largely single-threaded) is the long pole.

## Step 2 -- SPECIFIED (the routing switch; needs the validation run)

### 2a. Sub-WDLs (split `download.wdl`)
The Download stage runs a per-stage sub-WDL (`.../index-generation-vX/download.wdl`, the
per-stage split of the monolith `seqtoid-workflows/.../index-generation.wdl`). Split it into
three sub-WDLs, each a single-database workflow reusing the existing `DownloadDatabase` /
`UnzipFile` tasks unchanged:
- `download-taxonomy.wdl` -- the `scatter (UnzipFile)` over the accession2taxid + taxdump
  files. Outputs the 5 unzipped taxonomy files.
- `download-nt.wdl` -- `call DownloadDatabase as DownloadNT { database_type = "nt" }`
  (core_nt via `update_blastdb.pl --source aws`). Output: `nt.fsa`.
- `download-nr.wdl` -- `call DownloadDatabase as DownloadNR { database_type = "nr" }`.
  Output: `nr.fsa`.
Upload alongside the existing per-stage WDLs (the deploy script's WDL upload step).

### 2b. Lambda (`start_index_generation_lambda_src/main.py`)
Currently emits `DOWNLOAD_WDL_URI` + `Input.Download` + a `STAGES_IO_MAP` (Download ->
Compress -> Index). Change to emit:
- `DOWNLOAD_TAXONOMY_WDL_URI`, `DOWNLOAD_NT_WDL_URI`, `DOWNLOAD_NR_WDL_URI` (+ matching
  `Input.DownloadTaxonomy/DownloadNT/DownloadNR` payloads, each `{docker_image_id}`).
- Per-stage memory overrides for the three (reuse the download memory default).
- `STAGES_IO_MAP`: Compress's `download_out_nt` <- DownloadNT output, `download_out_nr` <-
  DownloadNR output, taxonomy files <- DownloadTaxonomy outputs (replacing the single
  Download->Compress handoff). Update `test_main.py` assertions accordingly.

### 2c. SFN template (`terraform/sfn_templates/index-generation.yml`)
Replace the single `Download` Task (currently `Next: DownloadReadOutput -> DownloadSucceeded
-> Compress`) with a `Parallel` state, three branches, each mirroring the existing Download
Task+ReadOutput pattern but pointed at its own queue + WDL URI:
- branch DownloadTaxonomy -> `${index_generation_download_taxonomy_job_queue_arn}`, WDL
  `$.DOWNLOAD_TAXONOMY_WDL_URI`
- branch DownloadNT -> `${index_generation_download_nt_job_queue_arn}`, `$.DOWNLOAD_NT_WDL_URI`
- branch DownloadNR -> `${index_generation_download_nr_job_queue_arn}`, `$.DOWNLOAD_NR_WDL_URI`
Each branch keeps the `Retry: *BatchRetryConfig` and a per-branch ReadOutput lambda call.
The Parallel state's `Catch: [States.ALL] -> HandleFailure`; on success `Next: Compress`.
AWS Batch runs the three submitJob.sync branches concurrently -> three separate boxes.
Then remove the retained `download` stage from `index-generation.tf` + its
`extra_template_vars` arn.

### 2d. Validation run (the gate before merge)
1. Apply this via CI (dev). 2. Trigger one index-generation run. 3. Confirm three download
Batch jobs run CONCURRENTLY on three boxes (each its own queue), none out-of-disk, and the
Compress stage receives nt + nr + taxonomy via the io-map. 4. Kill one branch mid-run and
re-trigger -> confirm call_cache skips the two succeeded branches (resume proof). Only then
merge + remove `download`.

## Time impact (why "correct" is also faster)
Serialized re-run to a completed download ~15h; split ~7.5h (max of the three) + ~3-4h eng
= ~11-12h. The parallelism saves more than the split costs to build. Compress + Index stages
are unchanged.
