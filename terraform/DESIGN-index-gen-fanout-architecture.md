# Index-generation fan-out architecture: per-DB DAG + sharding + cadence caching

Builds on the download split (#799). Covers levers (2) per-database end-to-end fan-out,
(3) shard the single-threaded long poles, and (4) decouple refresh cadence via caching.
Target: build the FULL nt+nr index (the #788 NT-only call is pending and we are NOT betting
on it) in the shortest wall-clock, and make future refreshes skip unchanged work.

All held. This is a multi-stage SFN + WDL + lambda re-architecture that cannot be locally
test-applied (Rosetta) and is gated on validation runs. Sequenced so each increment lands on
a green run before the next.

## The DAG (from index-generation.wdl) -- three independent lanes

Today's SFN is linear: `Download(all) -> Compress(nr) -> Index(all)`. But the task graph is
three lanes that share NOTHING until final assembly:

```
TAXONOMY lane:  UnzipFile x5 (accession2taxid nucl_gb/nucl_wgs/pdb/prot.FULL + taxdump)
                   -> GenerateIndexAccessions (accession2taxid_db)
                   -> GenerateIndexLineages   (lineage dbs, deuterostome, ignore/changed logs)

NT lane:        DownloadNT -> [CompressNT -> ShuffleNT]?  (compression optional for nt)
                   -> GenerateNTLocDB
                   -> GenerateNTInfoDB
                   -> GenerateIndexMinimap2   (minimap2_index)

NR lane:        DownloadNR -> CompressNR -> ShuffleNR       (the long pole)
                   -> GenerateNRLocDB
                   -> GenerateIndexDiamond    (diamond_index; already --scatter-gather chunked)

ASSEMBLE:       collect all lane outputs -> write_to_db / load
```

Wall-clock today = taxonomy + nt-work + nr-work serialized. Fanned out =
`max(taxonomy_lane, nt_lane, nr_lane)`. The NR lane (download ~7.4h + compress multi-hour +
diamond) is the long pole, so lever (3) targets it.

## Lever (2) -- per-database end-to-end fan-out

Restructure the SFN from one linear chain into **three parallel lanes** that run
concurrently and join once, at assembly. The download split (#799) is lane-step-1; this
extends the same Parallel-branch pattern through compress + index.

- **SFN template** (`sfn_templates/index-generation.yml`): replace `Download -> Compress ->
  IndexSPOT` with a top-level `Parallel` of three branches (Taxonomy, NT, NR), each an
  internal chain of submitJob.sync stages on that lane's queues, then an `Assemble` join
  stage after the Parallel.
- **Sub-WDLs**: split the monolith into per-lane WDLs -- `taxonomy.wdl` (unzip + accessions
  + lineages), `nt.wdl` (download-nt + optional compress + loc/info/minimap2), `nr.wdl`
  (download-nr + compress + shuffle + loc/diamond). Each reuses the existing tasks unchanged;
  only the workflow wiring is new. (The #799 download-{nt,nr,taxonomy}.wdl become the first
  call in each lane WDL.)
- **Lambda** (`start_index_generation_lambda_src/main.py`): emit per-lane WDL URIs +
  per-lane Input payloads + a `STAGES_IO_MAP` that threads each lane's outputs into Assemble
  (instead of the linear Download->Compress->Index handoff). Update `test_main.py`.
- **Compute**: the #799 per-DB download queues extend to per-lane compute -- each lane's
  compress/index stages route to their existing right-sized queues (compress = r6i/r7g.12xl
  on-demand; index = spot with on-demand fallback). Lanes run on separate compute
  concurrently; dev spot_max_vcpus=4096 has ample headroom.

Expected wall-clock: dominated by the NR lane. NT lane (download ~4-5h + minimap2) and
taxonomy lane (~3.4h today, cut by #799's own box) finish well inside the NR lane, so they
become free.

## Lever (3) -- shard the single-threaded long poles (attacks the NR lane)

Within the NR lane the poles are single-threaded, so bigger boxes do not help; sharding does.
The pre-built BLAST db arrives as multiple volume files (nr.00, nr.01, ...), a natural shard
boundary, and diamond already scatter-gathers -- so the pattern is in-repo.

- **NR FASTA extraction** (`blastdbcmd -entry all -out nr.fsa`): scatter by volume/OID range
  -- `blastdbcmd` per shard (`-entry_batch` or per-volume) in parallel, concat the shard
  fastas. N-way parallel -> ~1/N the extraction time.
- **CompressNR** (`ncbi-compress`, the other multi-hour single task): shard-then-merge ONLY
  if clustering correctness is preserved across shards. ncbi-compress dedups/clusters; naive
  sharding can change which representatives survive. Validate AUPR (>=0.98 gate) on a sharded
  vs unsharded build before adopting -- if sharding shifts AUPR, keep CompressNR whole and
  instead right-size its box. (This is the one lever with a correctness risk; gate it hard.)
- **DiamondIndex**: already chunked (`--scatter-gather -b chunksize`); confirm the chunk
  count uses the lane's full vCPU.

Sharding is additive to lever (2): each shard is a scatter inside the NR lane WDL, so it
needs no new SFN stages -- miniwdl fans the scatter across the lane box's cores (or, for
cross-box scale, promote the shard to its own Batch stage). Start with in-WDL scatter on a
larger NR box; promote to per-shard Batch stages only if a single box caps out.

## Lever (4) -- decouple refresh cadence via caching (mostly already there)

`call_cache = true` (swipe.tf) already caches every task by an input-hash. Combined with the
lane fan-out, each lane is an independently cacheable unit: a build whose NR inputs are
unchanged gets a full NR-lane cache hit and skips it. The work to make this real:

- **Pin taxonomy/lineage inputs** (ties to #778 snapshot-and-hold, #747). Today the taxonomy
  lane pulls "current" from NCBI FTP, so its input hash changes every run and never caches.
  Pin to the captured `ncbi-indexes/<date>/` snapshot so an unchanged-lineage build cache-hits
  the whole taxonomy lane. This is what makes "quarterly lineage, annual nt/nr" real: refresh
  the pin only when you intend to.
- **Cadence trigger modes** (start_index_generation lambda): a `refresh_scope` input --
  `full` (rebuild all), `nt_only`, `nr_only`, `lineage_only` -- that supplies the pinned
  (cached) inputs for the lanes NOT being refreshed, so call_cache skips them. With the lanes
  independent (lever 2), this is just "which lane's inputs did we bump."
- **Result**: an annual nt/nr rebuild reuses cached lineage; a quarterly lineage refresh
  reuses cached nt/nr; a core_nt-vs-full-nt A/B (#770) reuses the shared taxonomy lane for
  both arms. No monolith rebuild each time.

## How the levers compose

(2) makes each DB an independent, cacheable lane. (3) collapses the NR lane's long pole so
the fanned-out wall-clock keeps dropping. (4) makes unchanged lanes free on subsequent builds
and enables concurrent A/B builds. Net: first full build ~= NR-lane wall-clock (down from
serialized ~15h+ just for download); later scoped refreshes skip whole lanes.

## Sequencing (each gated on a green validation run)

1. **#799 download split** (built, held) -- validate: 3 concurrent download boxes, no OOD.
2. **Lever (2) fan-out** -- extend Parallel through compress+index; per-lane sub-WDLs +
   lambda IO-map + Assemble join. Validate: 3 lanes run concurrently, outputs assemble, AUPR
   >= 0.98 unchanged vs a linear build.
3. **Lever (3) NR sharding** -- FASTA-extract scatter first (no correctness risk), then
   CompressNR sharding ONLY if AUPR holds. Validate AUPR each step.
4. **Lever (4) cadence** -- pin taxonomy snapshot + refresh_scope modes. Validate: an
   nt_only refresh cache-hits the nr + lineage lanes.

## Non-negotiables

- FULL nt+nr (do not drop NR; #788 pending, assume both needed).
- AUPR >= 0.98 gate on every build that changes indexing/sharding/compression.
- Dev-only; apply via CI (Rosetta wall); nothing merges without its validation run.
