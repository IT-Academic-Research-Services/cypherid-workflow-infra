# type: ignore

INPUT = {
    "$schema": "http://json-schema.org/draft-07/schema",
    "$id": "http://czid.org/taxon-indexing-event.json",
    "type": "object",
    "title": "Taxon indexing event schema",
    "required": ["pipeline_run_id", "background_id"],
    "properties": {
        "pipeline_run_id": {
            "$id": "#/properties/pipeline_run_id",
            "type": "number",
            "title": "The pipeline_run_id",
        },
        "background_id": {
            "$id": "#/properties/background_id",
            "type": "number",
            "title": "The background_id",
        },
        "es_batchsize": {
            "$id": "#/properties/es_batchsize",
            "type": "number",
            "title": "The batchsize used for ES writes",
        },
        "scored_taxon_counts_index_name": {
            "$id": "#/properties/scored_taxon_counts_index_name",
            "type": "string",
            "title": "The index to use for scored taxon counts",
        },
        "pipeline_runs_index_name": {
            "$id": "#/properties/pipeline_runs_index_name",
            "type": "string",
            "title": "The index to use for pipeline runs",
        },
        "es_host": {
            "$id": "#/properties/es_host",
            "type": "string",
            "title": "Override OpenSearch host to index into",
            "description": (
                "Target OpenSearch endpoint for this invocation. When set (e.g. a preview "
                "sandbox passing its own HEATMAP_ES_ADDRESS = the sandbox domain), the Lambda "
                "writes into that domain instead of its own DEPLOYMENT_ENVIRONMENT-configured "
                "host. Omitted for dev/staging/prod, which fall back to the configured host."
            ),
        },
    },
}
