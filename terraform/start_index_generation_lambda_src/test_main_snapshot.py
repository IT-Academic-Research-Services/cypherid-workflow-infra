"""Default DB snapshot pin tests for start_index_generation.

Exercises DEFAULT_DB_SNAPSHOT_PREFIX: a normal run points the download + taxonomy lanes at a
pinned S3 snapshot (skip the ~7.4h NCBI fetch); live_ncbi_refresh=true forces live NCBI (the
annual gate); explicit provided_* and scoped compressed-reuse take precedence over the
snapshot; an empty prefix preserves live-NCBI behavior. No AWS.
"""
import json
import os
import sys
import types

captured = {"sfn_input": None, "put_objects": []}

_PRIOR = "ncbi-indexes-dev/2026-07-09/index-generation-2"
_PRIOR_KEYS = [
    f"{_PRIOR}/nt_compressed.fa",
    f"{_PRIOR}/nr_compressed.fa",
    f"{_PRIOR}/versioned-taxid-lineages.csv.gz",
]


class FakePaginator:
    def paginate(self, **kw):
        return [{"Contents": [{"Key": k} for k in _PRIOR_KEYS]}]


class FakeS3:
    def get_paginator(self, name):
        return FakePaginator()

    def put_object(self, **kw):
        captured["put_objects"].append(kw)


class FakeSFN:
    def start_execution(self, **kw):
        captured["sfn_input"] = json.loads(kw["input"])


fake_boto3 = types.ModuleType("boto3")
fake_boto3.client = lambda svc: FakeSFN() if svc == "stepfunctions" else FakeS3()
sys.modules["boto3"] = fake_boto3

os.environ.update({
    "DEPLOYMENT_ENVIRONMENT": "dev",
    "INDEX_GENERATION_SFN_ARN":
        "arn:aws:states:us-west-2:491013321714:stateMachine:idseq-swipe-dev-index-generation-wdl",
    "INDEX_GENERATION_WORKFLOW_VERSION": "v2.4.8",
    "AWS_REGION": "us-west-2",
    "AWS_ACCOUNT_ID": "491013321714",
    "BUCKET": "seqtoid-public-references",
    "S3_WORKFLOWS_BUCKET": "seqtoid-workflows-dev-491013321714",
    "DOWNLOAD_MEMORY": "14000",
    "COMPRESS_NR_MEMORY": "1450000",
    "COMPRESS_NT_MEMORY": "380000",
    "INDEX_SPOT_MEMORY": "128000",
    "INDEX_EC2_MEMORY": "250000",
})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main  # noqa: E402

_BASE = "s3://seqtoid-public-references"
_SNAP = "ncbi-indexes-dev/db-snapshots/2026-07-09"
_SNAP_URI = f"{_BASE}/{_SNAP}"


def run(snapshot_prefix=None, ig=None):
    if snapshot_prefix is None:
        os.environ.pop("DEFAULT_DB_SNAPSHOT_PREFIX", None)
    else:
        os.environ["DEFAULT_DB_SNAPSHOT_PREFIX"] = snapshot_prefix
    captured["sfn_input"] = None
    main.start_index_generation({"time": "2026-07-23T08:00:00Z", "index_generation": ig or {}})
    return captured["sfn_input"]["Input"]


# ---- no prefix (default): live NCBI, unchanged behavior ----
inp = run(None)
assert "provided_nt" not in inp["DownloadNT"], "no snapshot: NT must download live"
assert "provided_nr" not in inp["DownloadNR"], "no snapshot: NR must download live"
assert "provided_taxdump" not in inp["DownloadTaxonomy"], "no snapshot: taxonomy live"

# ---- snapshot set (normal run): all three lanes read the snapshot, skip download ----
inp = run(_SNAP)
assert inp["DownloadNT"]["provided_nt"] == f"{_SNAP_URI}/nt.fsa.gz", inp["DownloadNT"]
assert inp["DownloadNR"]["provided_nr"] == f"{_SNAP_URI}/nr.fsa.gz", inp["DownloadNR"]
assert inp["DownloadTaxonomy"]["provided_taxdump"] == f"{_SNAP_URI}/taxdump.tar.gz"
assert inp["DownloadTaxonomy"]["provided_accession2taxid_prot"] == \
    f"{_SNAP_URI}/prot.accession2taxid.FULL.gz"
# compression still runs from the snapshot fasta (this is not a compressed-artifact reuse)
assert "skip_nuc_compression" not in inp["CompressNT"]
assert "skip_protein_compression" not in inp["CompressNR"]

# ---- core_nt: the nt snapshot filename tracks nt_database_type ----
inp = run(_SNAP, {"nt_database_type": "core_nt"})
assert inp["DownloadNT"]["provided_nt"] == f"{_SNAP_URI}/core_nt.fsa.gz", inp["DownloadNT"]

# ---- annual gate: live_ncbi_refresh=true bypasses the snapshot entirely ----
inp = run(_SNAP, {"live_ncbi_refresh": True})
assert "provided_nt" not in inp["DownloadNT"], "live_ncbi_refresh: NT must fetch live"
assert "provided_nr" not in inp["DownloadNR"], "live_ncbi_refresh: NR must fetch live"
assert "provided_taxdump" not in inp["DownloadTaxonomy"], "live_ncbi_refresh: taxonomy live"

# ---- explicit provided_* wins over the snapshot default ----
inp = run(_SNAP, {"provided_nt": "s3://x/my_nt.fsa"})
assert inp["DownloadNT"]["provided_nt"] == "s3://x/my_nt.fsa", "explicit provided_nt must win"
assert inp["DownloadNR"]["provided_nr"] == f"{_SNAP_URI}/nr.fsa.gz", "nr still snapshot"

# ---- explicit taxonomy_snapshot_prefix wins over the DB snapshot default for taxonomy ----
inp = run(_SNAP, {"taxonomy_snapshot_prefix": "s3://other/tax/"})
assert inp["DownloadTaxonomy"]["provided_taxdump"] == "s3://other/tax/taxdump.tar.gz"
# db lanes still take the DB snapshot
assert inp["DownloadNT"]["provided_nt"] == f"{_SNAP_URI}/nt.fsa.gz"

# ---- scoped compressed reuse beats the snapshot for an out-of-scope DB ----
# nr_only: NR in scope -> snapshot raw; NT out of scope -> reuse prior COMPRESSED + skip compress.
inp = run(_SNAP, {"refresh_scope": "nr_only"})
assert inp["DownloadNT"]["provided_nt"] == f"{_BASE}/{_PRIOR}/nt_compressed.fa", \
    "out-of-scope NT must reuse compressed, not snapshot"
assert inp["CompressNT"]["skip_nuc_compression"] is True
assert inp["DownloadNR"]["provided_nr"] == f"{_SNAP_URI}/nr.fsa.gz", "in-scope NR uses snapshot"
assert "skip_protein_compression" not in inp["CompressNR"]

# ---- snapshot prefix given as a bare key (not s3://) resolves under the references bucket ----
inp = run("ncbi-indexes-dev/db-snapshots/2026-07-09")
assert inp["DownloadNR"]["provided_nr"] == f"{_BASE}/{_SNAP}/nr.fsa.gz"

# ==== DEFAULT_REFRESH_SCOPE (reuse-as-default) ====
_PRIOR_NT_C = f"{_BASE}/{_PRIOR}/nt_compressed.fa"
_PRIOR_NR_C = f"{_BASE}/{_PRIOR}/nr_compressed.fa"


def run_scope(default_scope=None, ig=None, snapshot=None):
    if default_scope is None:
        os.environ.pop("DEFAULT_REFRESH_SCOPE", None)
    else:
        os.environ["DEFAULT_REFRESH_SCOPE"] = default_scope
    if snapshot is None:
        os.environ.pop("DEFAULT_DB_SNAPSHOT_PREFIX", None)
    else:
        os.environ["DEFAULT_DB_SNAPSHOT_PREFIX"] = snapshot
    captured["sfn_input"] = None
    main.start_index_generation({"time": "2026-07-23T08:00:00Z", "index_generation": ig or {}})
    return captured["sfn_input"]["Input"]


# default scope full (unset env): full rebuild, no reuse
inp = run_scope(None)
assert "provided_nt" not in inp["DownloadNT"] and "provided_nr" not in inp["DownloadNR"]
assert "skip_nuc_compression" not in inp["CompressNT"]

# env default lineage_only: BOTH DBs reuse prior compressed + skip compression by default
inp = run_scope("lineage_only")
assert inp["DownloadNT"]["provided_nt"] == _PRIOR_NT_C, inp["DownloadNT"]
assert inp["DownloadNR"]["provided_nr"] == _PRIOR_NR_C
assert inp["CompressNT"]["skip_nuc_compression"] is True
assert inp["CompressNR"]["skip_protein_compression"] is True

# explicit event refresh_scope wins over the env default
inp = run_scope("lineage_only", {"refresh_scope": "full"})
assert "provided_nt" not in inp["DownloadNT"], "explicit full must override env default"
assert "skip_nuc_compression" not in inp["CompressNT"]

# live_ncbi_refresh forces full even if the env default is a reuse scope (annual gate)
inp = run_scope("lineage_only", {"live_ncbi_refresh": True})
assert "provided_nt" not in inp["DownloadNT"], "live_ncbi_refresh must force full rebuild"
assert "provided_nr" not in inp["DownloadNR"]
assert "skip_nuc_compression" not in inp["CompressNT"]

# reset env so nothing leaks
os.environ.pop("DEFAULT_REFRESH_SCOPE", None)
os.environ.pop("DEFAULT_DB_SNAPSHOT_PREFIX", None)

print("ALL SNAPSHOT ASSERTIONS PASSED")
