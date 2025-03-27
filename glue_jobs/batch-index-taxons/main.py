import config
import job
import logging

log = logging.getLogger()


def configure_logger():
    global_logger = logging.getLogger()
    global_logger.setLevel(level=logging.INFO)
    fh = logging.StreamHandler()
    fh_formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(module)s:%(lineno)d]  %(message)s"
    )
    fh.setFormatter(fh_formatter)
    global_logger.addHandler(fh)


def main():
    log.info("Loading input file from s3")
    input_file = config.load_json_from_s3(
        config.params["input_s3_bucket"], config.params["input_s3_path"]
    )
    # TODO validate input json

    # flatten input json into list of job params
    job_params = [
        {"pipeline_run_id": pipeline_run_id, "background_id": background_id}
        for record in input_file["job_params"]
        for pipeline_run_id in record["pipeline_run_ids"]
        for background_id in record["background_ids"]
    ]

    skip = []
    if "skip" in input_file:
        log.info("Skipping inputs: %s", input_file["skip"])
        skip = input_file["skip"]

    concurrency = 50
    if "concurrency" in input_file:
        log.info("Concurrency: %s", input_file["concurrency"])
        concurrency = input_file["concurrency"]

    index_names = {
        "scored_taxon_counts_index_name": config.params[
            "scored_taxon_counts_index_name"
        ],
        "pipeline_runs_index_name": config.params["pipeline_runs_index_name"],
    }

    log.info("Running job with %s inputs", len(job_params) - sum(skip))
    reports = job.parallel_runs(job_params, skip, index_names, concurrency)
    for report in reports:
        if report["error_response"]:
            raise Exception("Job failed: %s", reports)
    log.info("Job finished successfully: %s", reports)


config.init()
configure_logger()
main()
