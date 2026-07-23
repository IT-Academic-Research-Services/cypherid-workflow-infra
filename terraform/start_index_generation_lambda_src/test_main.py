"""Contract test for the fan-out start_index_generation lambda (platform-overhaul 800).

Verifies the SFN input matches the extended io-helper contract: one <STAGE>_WDL_URI per
sub-WDL, per-stage Input with only declared keys, the DAG STAGES_IO_MAP written to S3, no
undeclared keys leaking, and the provided_nr salvage override threading through.
"""
import json
import os
import sys
import types

captured = {"sfn_input": None, "put_objects": []}


class FakePaginator:
    def paginate(self, **kw):
        return [{"Contents": []}]  # no prior lineages / compressed dbs


class FakeS3:
    def get_paginator(self, name):
        return FakePaginator()

    def put_object(self, **kw):
        captured["put_objects"].append(kw)


class FakeSFN:
    def start_execution(self, **kw):
        captured["sfn_input"] = json.loads(kw["input"])
        captured["exec_name"] = kw["name"]


fake_boto3 = types.ModuleType("boto3")
fake_boto3.client = lambda svc: FakeSFN() if svc == "stepfunctions" else FakeS3()
sys.modules["boto3"] = fake_boto3

os.environ.update({
    "DEPLOYMENT_ENVIRONMENT": "dev",
    "INDEX_GENERATION_SFN_ARN": (
        "arn:aws:states:us-west-2:491013321714:stateMachine:idseq-swipe-dev-index-generation-wdl"
    ),
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
import main  # noqa: E402  -- imported only after boto3 is stubbed and env is set

_NR_SALVAGE = (
    "s3://seqtoid-public-references/ncbi-indexes-dev/2026-07-21-core-nt-s3/download/nr.fsa"
)
main.start_index_generation({
    "time": "2026-07-21T08:00:00Z",
    "index_generation": {"provided_nr": _NR_SALVAGE},
})

d = captured["sfn_input"]
print(json.dumps(d, indent=2))

_image = "491013321714.dkr.ecr.us-west-2.amazonaws.com/index-generation:v2.4.8"

# ---- one <STAGE>_WDL_URI per sub-WDL ----
expected_uri_keys = {
    "DOWNLOAD_TAXONOMY_WDL_URI", "DOWNLOAD_NT_WDL_URI", "DOWNLOAD_NR_WDL_URI",
    "COMPRESS_NT_WDL_URI", "COMPRESS_NR_WDL_URI",
    "INDEX_NT_WDL_URI", "INDEX_NR_WDL_URI", "INDEX_TAXONOMY_WDL_URI",
    "ASSEMBLE_WDL_URI",
}
assert set(d) == expected_uri_keys | {
    "STAGES_IO_MAP_JSON", "Input", "OutputPrefix",
    "DownloadEC2Memory", "CompressEC2Memory", "IndexSPOTMemory", "IndexEC2Memory",
}, f"top-level keys: {sorted(d)}"
assert d["DOWNLOAD_NR_WDL_URI"].endswith("index-generation-v2.4.8/download-nr.wdl")
assert d["INDEX_NT_WDL_URI"].endswith("index-generation-v2.4.8/index-nt.wdl")
assert d["ASSEMBLE_WDL_URI"].endswith("index-generation-v2.4.8/assemble.wdl")

# ---- per-stage inputs: only declared keys, no undeclared leakage ----
stages = {
    "DownloadTaxonomy", "DownloadNT", "DownloadNR",
    "CompressNT", "CompressNR", "IndexNT", "IndexNR", "IndexTaxonomy", "Assemble",
}
assert set(d["Input"]) == stages, f"stage set: {sorted(d['Input'])}"
for stage in stages:
    assert d["Input"][stage]["docker_image_id"] == _image
    for bad in ("write_to_db", "env", "s3_dir"):
        assert bad not in d["Input"][stage], f"{bad} leaked into {stage}"

# provided_nr salvage threaded into the NR download lane; NT lane defaults to full download
assert d["Input"]["DownloadNR"]["provided_nr"] == _NR_SALVAGE
assert "provided_nr" not in d["Input"]["DownloadNT"]
assert d["Input"]["DownloadNT"]["nt_database_type"] == "nt"
assert d["Input"]["IndexTaxonomy"]["index_name"] == "2026-07-21"

# ---- DAG io-map written to S3 + referenced ----
assert captured["put_objects"], "io-map put_object called"
iomap = json.loads(captured["put_objects"][0]["Body"].decode())
assert iomap["CompressNR"]["download_out_nr"] == "nr"
assert iomap["CompressNR"]["download_out_accession2taxid_pdb"] == "accession2taxid_pdb"
assert iomap["IndexNT"]["compress_out_nt"] == "nt"
assert iomap["Assemble"]["compress_out_nr"] == "nr"
assert iomap["Assemble"]["accession2taxid_prot"] == "accession2taxid_prot"
assert d["STAGES_IO_MAP_JSON"].endswith("2026-07-21/stage_io_map.json")

# ---- memory overrides pass through ----
assert d["DownloadEC2Memory"] == 14000
assert d["CompressEC2Memory"] == 380000
assert d["IndexSPOTMemory"] == 128000
assert d["IndexEC2Memory"] == 250000

print("\nALL ASSERTIONS PASSED")
