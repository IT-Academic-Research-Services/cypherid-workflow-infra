# type: ignore

from chalice import Chalice
import os
import logging
import json
import pymysql
from datetime import datetime
from opensearchpy import OpenSearch
from chalicelib import queries, config, schemas
from aws_lambda_powertools.utilities.validation import validate

app = Chalice(app_name="taxon-indexing-lambda")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_ES_BATCHSIZE = 1000

if "AWS_CHALICE_CLI_MODE" not in os.environ:
    params = config.get_parameters()
    es = OpenSearch(params["es_host"], timeout=120)


def handler(event, context):
    """Lambda entry point for local runs"""
    return index_taxons(event, context)


@app.lambda_function()
def index_taxons(event, context):
    """
    Read all taxon_counts for the given pipeline_run_id and then write the results to ElasticSearch
    """
    validate(event=event, schema=schemas.INPUT)

    pipeline_run_id = event["pipeline_run_id"]
    background_id = event["background_id"]
    es_batchsize = event.get("es_batchsize", DEFAULT_ES_BATCHSIZE)
    scored_taxon_counts_index_name = event.get(
        "scored_taxon_counts_index_name", "scored_taxon_counts"
    )
    pipeline_runs_index_name = event.get("pipeline_runs_index_name", "pipeline_runs")

    create_pipeline_run(pipeline_run_id, background_id, pipeline_runs_index_name)
    if "LOCAL_MODE" in os.environ:
        # in local mode, passing a password parameter (even None)
        # will cause the connection to fail
        conn = pymysql.connect(
            host=params["mysql_host"],
            port=int(params["mysql_port"]),
            user=params["mysql_username"],
            db=params["mysql_db"],
            connect_timeout=10,
        )
    else:
        conn = pymysql.connect(
            host=params["mysql_host"],
            port=int(params["mysql_port"]),
            user=params["mysql_username"],
            passwd=params["mysql_password"],
            db=params["mysql_db"],
            ssl={"enable_tls": True},
            connect_timeout=10,
        )

    with conn.cursor(pymysql.cursors.SSDictCursor) as cursor:
        cursor.execute(queries.get_contigs_by_pipeline_run_id_query(pipeline_run_id))

        contig_data = package_contigs(yield_all_records(cursor, batchsize=1000))

        cursor.execute(
            queries.get_scored_taxon_counts_query(pipeline_run_id, background_id)
        )
        for batch in batch_es_index_bodies(
            package_metrics(
                # the highest number of taxon_counts for a given pipeline_run_id
                # appears to top out at around 60k and more commonly tops out at
                # 20k, so all results should fit in memory just fine.
                yield_all_records(cursor),
                contig_data,
            ),
            scored_taxon_counts_index_name,
            batchsize=es_batchsize,
        ):
            bulk_index_taxon_metrics(batch)

    # refresh the index so that all written records are available to search before returning
    response = es.indices.refresh(index=scored_taxon_counts_index_name)
    logger.info(response)
    complete_pipeline_run(pipeline_run_id, background_id, pipeline_runs_index_name)

    conn.close()

    return {
        "success": True,
        "params": {
            "pipeline_run_id": pipeline_run_id,
            "background_id": background_id,
            "es_batchsize": es_batchsize,
        },
    }


def package_contigs(sql_results):
    """
    Return the number of contigs that were found for each
    pipeline/taxon/count_type combination.
    Adapted from https://github.com/chanzuckerberg/czid-web-private/blob/
    d12952/app/models/pipeline_run.rb#L1751-L1779
    """

    taxid_and_count_types = [
        ("species_taxid_nt", "NT"),
        ("species_taxid_nr", "NR"),
        ("species_taxid_merged_nt_nr", "merged_NT_NR"),
        ("genus_taxid_nt", "NT"),
        ("genus_taxid_nr", "NR"),
        ("genus_taxid_merged_nt_nr", "merged_NT_NR"),
    ]

    summary_dict = {}
    for row in sql_results:
        for taxid_type, count_type in taxid_and_count_types:
            taxid = row[taxid_type]
            if taxid:
                summary_dict.setdefault(taxid, {}).setdefault(count_type, 0)
                summary_dict[taxid][count_type] += 1

    return summary_dict


def yield_all_records(cursor, batchsize=None):
    """
    Fetch records from the cursor and then yield rows individually
    """
    if not batchsize:
        yield from cursor.fetchall()
    else:
        while True:
            batch = cursor.fetchmany(batchsize)
            if not batch or len(batch) == 0:
                break
            yield from batch


def package_metrics(sql_results, contig_data):
    """
    Reduce the per-counttype MySQL rows into per-taxon objects for ES
    """
    current_tax_id = None
    packaged_taxon = None
    # sql_results are sorted by tax_id, so we can just iterate through them
    for row in sql_results:
        # if we're starting a new taxon, yield the previous one
        # and then start a new one
        if current_tax_id and current_tax_id != row["tax_id"]:
            yield packaged_taxon
            packaged_taxon = None

        # construct the metric list entry for this row
        metric_list_entry = {
            "count_type": row["count_type"],
            "counts": row["counts"],
            "stdev": row["stdev"],
            "mean": row["mean"],
            "stdev_mass_normalized": row["stdev_mass_normalized"],
            "mean_mass_normalized": row["mean_mass_normalized"],
            "percent_identity": row["percent_identity"],
            "e_value": row["e_value"],
            "rpm": row["rpm"],
            "zscore": row["zscore"],
            "alignment_length": row["alignment_length"],
            "contigs": contig_data.get(row["tax_id"], {}).get(row["count_type"], 0),
        }
        # if we're starting a new taxon, create the taxon object with the metric entry
        if packaged_taxon is None:
            current_tax_id = row["tax_id"]
            packaged_taxon = {
                "pipeline_run_id": row["pipeline_run_id"],
                "tax_id": row["tax_id"],
                "background_id": row["background_id"],
                "tax_level": row["tax_level"],
                "genus_taxid": row["genus_taxid"],
                "family_taxid": row["family_taxid"],
                "superkingdom_taxid": row["superkingdom_taxid"],
                "name": row["name"],
                "common_name": row["common_name"],
                "genus_name": row["genus_name"],
                "is_phage": row["is_phage"],
                "metric_list": [metric_list_entry],
            }
        # if the taxon already exists, append the metric entry to the list
        else:
            current_tax_id = row["tax_id"]
            packaged_taxon["metric_list"].append(metric_list_entry)
    if packaged_taxon:
        yield packaged_taxon


def index_taxon_metrics(taxon_metrics, index_name):
    """
    Write a single taxon to ES
    """
    response = es.index(index=index_name, body=taxon_metrics)
    logger.info(response)


def bulk_index_taxon_metrics(batch):
    """
    Write a batch of taxons to ES
    """
    if batch:
        response = es.bulk(batch)
        if response["errors"]:
            errors = [
                item["index"]["error"]
                for item in response["items"]
                if "error" in item["index"]
            ]
            error_count = len(errors)
            logger.info(response)
            raise Exception(
                f"Bulk write failed {error_count} times. Error example: ",
                json.dumps(errors[0]),
            )
        logger.info(response)


def create_pipeline_run(pipeline_run_id, background_id, index_name):
    """
    Create/overwrite the pipeline_runs index record
    for the given pipeline so that we can track the
    completeness of the scored_taxon_counts writes
    """
    response = es.index(
        index=index_name,
        body={
            "pipeline_run_id": pipeline_run_id,
            "background_id": background_id,
            "is_complete": False,
            "created_at": datetime.now().isoformat(),
        },
        id=f"{pipeline_run_id}_{background_id}",
        refresh=True,
    )
    logger.info(response)


def complete_pipeline_run(pipeline_run_id, background_id, index_name):
    """
    Update the pipeline_run index record to indicate
    that all scored_taxon_count records were
    successfully written
    """
    response = es.update(
        index=index_name,
        body={"doc": {"is_complete": True}},
        id=f"{pipeline_run_id}_{background_id}",
        retry_on_conflict=3,
        refresh=True,
    )
    logger.info(response)


def batch_es_index_bodies(taxon_metrics_list, index_name, batchsize):
    """
    Batch taxons for more efficient ES bulk writes
    """
    count = 0
    bulk_body = ""
    for taxon_metrics in taxon_metrics_list:
        es_id = (
            f'{taxon_metrics["tax_id"]}'
            f'_{taxon_metrics["tax_level"]}'
            f'_{taxon_metrics["pipeline_run_id"]}'
            f'_{taxon_metrics["background_id"]}'
        )
        bulk_body += (
            f'{{"index": ' f'{{"_index": "{index_name}", "_id":"{es_id}" }}}} \n'
        )
        bulk_body += json.dumps(taxon_metrics, separators=(",", ":")) + "\n"
        count += 1
        if count == batchsize:
            yield bulk_body
            bulk_body = ""
            count = 0
    yield bulk_body
