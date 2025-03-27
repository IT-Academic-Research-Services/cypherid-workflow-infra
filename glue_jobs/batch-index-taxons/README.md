# Batch Index Taxons
This glue job is for loading or re-loading any number of taxons into ES. You might use this glue job when:
- you have made a change to the scored_taxon_counts mapping that adds a new field that must be computed/fetched from mySQL or elsewhere
- you want to pre-load some taxons into ES (not wait for a user to request a heatmap)

## Why Glue?
While glue is primarily associated with spark jobs, we are using the `Python Shell` execution mode that allows us to run a simple python script. Glue was selected because:
- it can run very long jobs (in case of very large indexing jobs)
- it is serverless (compute is provisioned for each job run automatically)
- it provides some dashboard to check the success of a job run and inspect it's logs

## How to use it
### Composing an input file
The input to the job is a JSON file of the following type:
```
{
    "job_params": {
        "background_ids": number[],
        "pipeline_run_ids": number[]
    }[],
    "concurrency": number,
    "skip": number[]
}
```
the `job_params` section allows you to provide a list of background_ids that are to be loaded for the given pipeline_run_ids. If you have some pipeline_run_ids that should have some backgrounds but not others, you will need to provide multiple objects in the job_params array. How you arrange your input file will not impact the runtime of the job. All input files get transformed into an array of `taxon-indexing-lambda` invocations that each take a single `background_id`, `pipeline_run_id` pair.

The `concurrency` parameter indicates how many concurrent batches you want to have running. E.g. if you specify a `concurrency` of `20`, the array of `job_params` will be split into 20 even-sized arrays. Each of those arrays will get their own python co-routine, making it so only 20 lambdas are executing at any given time.

The `skip` parameter is an array of numbers indicating how many `job_params` you want to skip for each batch. E.g. if the first number in the skip array is 5, the first batch will skip 5. An input file with a given `job_params` and `concurrency` runs deterministically (it will create the same batches each time). If there is a failure in one of the batches, it stops processing and waits for all other batches to complete. After all batches have completed, a report is logged including the number of successes in each batch. If any of the coroutines did not complete successfully, you will want to run again, but include the `skip` parameter in the input_file. You can compose the skip array by mapping the array of logged `batch_report` objects to the array of their `success_count` properties. 

Once you have composed your JSON file, upload it to the `idseq-{env}-heatmap-batch-jobs/input-files` S3 folder with a `YYYY-MM-DD_{optional description}.json` name.

### Starting a batch indexing job
You will trigger the glue job from your local machine using the make targets provided in this folder.
- for example if your file is named `2023-05-11_test02.json` and your environment is `sandbox` you start the job by running `INPUT_FILE=2023-05-11_test02.json make trigger-sandbox`
- it will often be the case that you want to target a fresh index that is not currently being used in production
    - to do this you will need to pass `--scored_taxon_counts_index_name` and `--scored_taxon_counts_index_name` to specify new index names to write to (it defaults to the current live indexes)
    - you will need to create the new indexes via the ES dev tools console before starting the glue job
- a successful trigger will output a `JobRunId` that can be matched with the running job in the console

### Monitoring job progress/success
- find the job in the AWS console
    - [idseq-sandbox-batch-taxon-indexing](https://us-west-2.console.aws.amazon.com/gluestudio/home?region=us-west-2#/editor/job/idseq-sandbox-batch-taxon-indexing/runs)
    - [idseq-staging-batch-taxon-indexing](https://us-west-2.console.aws.amazon.com/gluestudio/home?region=us-west-2#/editor/job/idseq-staging-batch-taxon-indexing/runs)
    - [idseq-prod-batch-taxon-indexing]()
- once the job is selected, in addition to the job status and runtime you will find links to the output logs and error logs in that job's details
- the error logs contain all logs including info level logs that were produced by the job
    - the job progress logs (and error logs) can be found here

# Deployment of the Glue Job
Since this is an admin utility, for simplicity's sake there is no CI/CD. You use the make targets provided in the Makefile to deploy from your local.