"""Contract test for the multi-stage start_index_generation lambda (CZID-774).
Verifies the SFN input matches the deployed SWIPE io-helper contract:
per-stage Input has only declared sub-WDL keys, STAGES_IO_MAP_JSON is emitted,
and no undeclared keys (write_to_db/env/s3_dir) leak into any stage.
"""
import json, os, sys, types

# stub boto3 before importing the handler
captured = {"sfn_input": None, "put_objects": []}

class FakePaginator:
    def paginate(self, **kw): return [{"Contents": []}]  # no prior lineages
class FakeS3:
    def get_paginator(self, name): return FakePaginator()
    def put_object(self, **kw): captured["put_objects"].append(kw)
class FakeSFN:
    def start_execution(self, **kw): captured["sfn_input"] = json.loads(kw["input"]); captured["exec_name"] = kw["name"]

fake_boto3 = types.ModuleType("boto3")
fake_boto3.client = lambda svc: FakeSFN() if svc == "stepfunctions" else FakeS3()
sys.modules["boto3"] = fake_boto3

os.environ.update({
    "DEPLOYMENT_ENVIRONMENT": "dev",
    "INDEX_GENERATION_SFN_ARN": "arn:aws:states:us-west-2:491013321714:stateMachine:idseq-swipe-dev-index-generation-wdl",
    "INDEX_GENERATION_WORKFLOW_VERSION": "v2.4.8",
    "AWS_REGION": "us-west-2",
    "AWS_ACCOUNT_ID": "491013321714",
    "BUCKET": "seqtoid-public-references",
    "S3_WORKFLOWS_BUCKET": "seqtoid-workflows-dev-491013321714",
    "DOWNLOAD_MEMORY": "14000", "COMPRESS_MEMORY": "380000",
    "INDEX_SPOT_MEMORY": "128000", "INDEX_EC2_MEMORY": "250000",
})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main
main.start_index_generation({"time": "2026-07-21T08:00:00Z"})

d = captured["sfn_input"]
print(json.dumps(d, indent=2))
# assertions
assert set(d) == {"DOWNLOAD_WDL_URI","COMPRESS_WDL_URI","INDEX_WDL_URI","STAGES_IO_MAP_JSON","Input","OutputPrefix","DownloadEC2Memory","CompressEC2Memory","IndexSPOTMemory","IndexEC2Memory"}, "top-level keys"
assert d["DOWNLOAD_WDL_URI"].endswith("index-generation-v2.4.8/download.wdl")
assert d["INDEX_WDL_URI"].endswith("index-generation-v2.4.8/index.wdl")
# per-stage inputs carry ONLY declared keys, NO undeclared keys
assert d["Input"]["Download"] == {"docker_image_id": "491013321714.dkr.ecr.us-west-2.amazonaws.com/index-generation:v2.4.8"}
assert d["Input"]["Compress"] == {"docker_image_id": "491013321714.dkr.ecr.us-west-2.amazonaws.com/index-generation:v2.4.8"}
assert set(d["Input"]["Index"]) == {"docker_image_id","index_name"}, "Index keys (no previous_lineages since none prior)"
assert d["Input"]["Index"]["index_name"] == "2026-07-21"
for stage in ("Download","Compress","Index"):
    for bad in ("write_to_db","env","s3_dir"):
        assert bad not in d["Input"][stage], f"{bad} leaked into {stage}"
assert d["DownloadEC2Memory"]==14000 and d["CompressEC2Memory"]==380000 and d["IndexSPOTMemory"]==128000 and d["IndexEC2Memory"]==250000
# io-map written to S3 + referenced
assert captured["put_objects"], "io-map put_object called"
iomap = json.loads(captured["put_objects"][0]["Body"].decode())
assert iomap["Compress"]["download_out_nt"]=="nt" and iomap["Index"]["compress_out_taxdump"]=="taxdump"
assert d["STAGES_IO_MAP_JSON"].endswith("2026-07-21/stage_io_map.json")
print("\nALL ASSERTIONS PASSED")
