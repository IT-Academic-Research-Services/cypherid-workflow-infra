"""Lever 4 (802) tests for start_index_generation: refresh_scope + taxonomy snapshot pin.

Stubs S3 to expose a prior run's compressed artifacts so the scoped-refresh reuse path is
exercised, then checks the per-stage Inputs the lambda builds for each mode. No AWS.
"""
import json
import os
import sys
import types

captured = {"sfn_input": None, "put_objects": []}

_PRIOR = "ncbi-indexes-dev/2026-07-09/index-generation-2"
# A smoke-test directory that sorts ABOVE every real dated index run. This is the exact shape
# that poisoned the prepared full-run input: 386-byte synthetic artifacts under a non-dated
# sibling prefix won on lexicographic order. Nothing under it may ever be selected.
_SMOKE = "ncbi-indexes-dev/smoketest-graviton/be3e4378c/download"
_PRIOR_KEYS = [
    f"{_PRIOR}/nt_compressed.fa",
    f"{_PRIOR}/nr_compressed.fa",
    f"{_PRIOR}/versioned-taxid-lineages.csv.gz",
    f"{_SMOKE}/nt_compressed.fa",
    f"{_SMOKE}/nr_compressed.fa",
    f"{_SMOKE}/versioned-taxid-lineages.csv.gz",
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
    "COMPRESS_MEMORY": "380000",
    "INDEX_SPOT_MEMORY": "128000",
    "INDEX_EC2_MEMORY": "250000",
})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main  # noqa: E402

_BASE = "s3://seqtoid-public-references"
_PRIOR_NT = f"{_BASE}/{_PRIOR}/nt_compressed.fa"
_PRIOR_NR = f"{_BASE}/{_PRIOR}/nr_compressed.fa"


def run(scope=None, extra=None):
    ig = {}
    if scope:
        ig["refresh_scope"] = scope
    if extra:
        ig.update(extra)
    captured["sfn_input"] = None
    main.start_index_generation({"time": "2026-07-23T08:00:00Z", "index_generation": ig})
    return captured["sfn_input"]["Input"]


# ---- full (default): a full rebuild, NEVER seeded, NO scope-driven reuse skip ----
# Seeded compression emits the delta only and nothing recombines seed + delta, so an
# auto-seeded "full" run silently produces an incomplete index. The lambda must never inject
# previous_*_compressed into a compress lane, even though a prior run exists in the listing.
inp = run("full")
assert "provided_nt" not in inp["DownloadNT"], "full: NT must download, not reuse"
assert "provided_nr" not in inp["DownloadNR"], "full: NR must download, not reuse"
assert "skip_nuc_compression" not in inp["CompressNT"]
assert "skip_protein_compression" not in inp["CompressNR"]
assert "previous_nt_compressed" not in inp["CompressNT"], "full: must NOT seed compression"
assert "previous_nr_compressed" not in inp["CompressNR"], "full: must NOT seed compression"
assert inp["CompressNT"] == {"docker_image_id": inp["CompressNT"]["docker_image_id"]}
assert inp["CompressNR"] == {"docker_image_id": inp["CompressNR"]["docker_image_id"]}

# ---- nt_only: NT builds fully; NR reuses prior + skips compression ----
inp = run("nt_only")
assert "provided_nt" not in inp["DownloadNT"], "nt_only: NT in scope, full build"
assert "skip_nuc_compression" not in inp["CompressNT"]
assert inp["DownloadNR"]["provided_nr"] == _PRIOR_NR, "nt_only: NR reuses prior compressed"
assert inp["CompressNR"]["skip_protein_compression"] is True

# ---- nr_only: mirror image ----
inp = run("nr_only")
assert "provided_nr" not in inp["DownloadNR"]
assert "skip_protein_compression" not in inp["CompressNR"]
assert inp["DownloadNT"]["provided_nt"] == _PRIOR_NT
assert inp["CompressNT"]["skip_nuc_compression"] is True

# ---- lineage_only: both DB lanes reuse prior + skip; taxonomy rebuilds ----
inp = run("lineage_only")
assert inp["DownloadNT"]["provided_nt"] == _PRIOR_NT
assert inp["DownloadNR"]["provided_nr"] == _PRIOR_NR
assert inp["CompressNT"]["skip_nuc_compression"] is True
assert inp["CompressNR"]["skip_protein_compression"] is True

# ---- taxonomy snapshot pin: five sources point at the snapshot, not NCBI ----
inp = run("full", {"taxonomy_snapshot_prefix": "ncbi-indexes-dev/taxonomy-snapshots/2026-07-09"})
dt = inp["DownloadTaxonomy"]
snap = f"{_BASE}/ncbi-indexes-dev/taxonomy-snapshots/2026-07-09"
assert dt["provided_taxdump"] == f"{snap}/taxdump.tar.gz"
assert dt["provided_accession2taxid_prot"] == f"{snap}/prot.accession2taxid.FULL.gz"
assert dt["provided_accession2taxid_nucl_gb"] == f"{snap}/nucl_gb.accession2taxid.gz"

# ---- snapshot prefix given as a full s3:// URI ----
inp = run("full", {"taxonomy_snapshot_prefix": "s3://other-bucket/snap/2026-07-09/"})
assert inp["DownloadTaxonomy"]["provided_taxdump"] == "s3://other-bucket/snap/2026-07-09/taxdump.tar.gz"

# ---- explicit skip override wins over scope default ----
inp = run("nr_only", {"skip_nuc_compression": False})
assert inp["CompressNT"]["skip_nuc_compression"] is False, "explicit override must win"

# ---- prior-run discovery ignores non-dated (smoke-test) prefixes ----
# _SMOKE sorts above _PRIOR, so if the scan were still unrestricted these would resolve to the
# smoke-test artifacts and a scoped refresh would reuse a 386-byte synthetic file as the whole
# database. Every consumer of the discovered priors must land on the real dated run.
inp = run("lineage_only")
assert _SMOKE not in inp["DownloadNT"]["provided_nt"], "must not reuse a smoke-test artifact"
assert _SMOKE not in inp["DownloadNR"]["provided_nr"], "must not reuse a smoke-test artifact"
assert inp["DownloadNT"]["provided_nt"] == _PRIOR_NT
assert inp["DownloadNR"]["provided_nr"] == _PRIOR_NR
assert _SMOKE not in inp["IndexTaxonomy"]["previous_lineages"]
assert inp["IndexTaxonomy"]["previous_lineages"].endswith(
    f"{_PRIOR}/versioned-taxid-lineages.csv.gz"
)

# ---- invalid scope rejected ----
try:
    run("nt_and_nr")
    raise SystemExit("FAIL: invalid refresh_scope was accepted")
except ValueError as e:
    assert "refresh_scope must be one of" in str(e)

print("ALL LEVER-4 ASSERTIONS PASSED")
