# IDseq Step Functions/WDL Interface

The Step Functions and WDL interfaces were written to provide abstraction layers in the IDseq pipeline that allow us to:

- Decouple the deployment and version control of our front-end, AWS-based infrastructure, and bioinformatics logic
- Allow pipelines to be run without any action or state in the front-end
- Allow pipelines to be upgraded while preserving full reproducibility of prior pipeline versions
- Provide a public, open-source pipeline that can be re-run and meaningfully reused outside our infrastructure
- Allow re-running piplelines in a variety of scenarios such as intermittent failures or configuration changes

To achieve these goals while relying on well-supported infrastructure, we use the following tools:

- AWS Step Functions to define the top level pipeline interface and to orchestrate provisioning, tracking, and
  de-provisioning of compute resources and pipeline runs (step function executions)
- WDL to describe the logic inside each pipeline stage
- miniWDL to isolate each pipeline step into a container and marshal its I/O
- Terraform to configure the Step Functions and other supporting infrastructure as code

There is one step function for each pipeline. The top level interface to the pipeline is the input to the step function,
passed to the [StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)
API.

The input to the [short-read-mngs](https://github.com/chanzuckerberg/czid-workflows/tree/main/short-read-mngs) pipeline
is a JSON object with the following fields:

- Required:
  ```
  {
    "Input": {
      "HostFilter": {
        "fastqs_0": "s3://idseq-samples-ENV/samples/PROJECT_ID/SAMPLE_ID/fastqs/SAMPLE_NAME_R1_LANE.fastq",
        "fastqs_1": "s3://idseq-samples-ENV/samples/PROJECT_ID/SAMPLE_ID/fastqs/SAMPLE_NAME_R2_LANE.fastq",
        "file_ext": "fastq",
        "nucleotide_type": "DNA",
        "host_genome": "human",
        "adapter_fasta": "s3://czid-public-references/adapter_sequences/illumina_TruSeq3-PE-2_NexteraPE-PE.fasta",
        "star_genome": "s3://czid-public-references/host_filter/human/2018-02-15-utc-1518652800-unixtime__2018-02-15-utc-1518652800-unixtime/human_STAR_genome.tar",
        "bowtie2_genome": "s3://czid-public-references/host_filter/human/2018-02-15-utc-1518652800-unixtime__2018-02-15-utc-1518652800-unixtime/human_bowtie2_genome.tar",
        "human_star_genome": "s3://czid-public-references/host_filter/human/2018-02-15-utc-1518652800-unixtime__2018-02-15-utc-1518652800-unixtime/human_STAR_genome.tar",
        "human_bowtie2_genome": "s3://czid-public-references/host_filter/human/2018-02-15-utc-1518652800-unixtime__2018-02-15-utc-1518652800-unixtime/human_bowtie2_genome.tar",
        "max_input_fragments": 9000,
        "max_subsample_fragments": 9000
      },
      "NonHostAlignment": {
        "index_version": "2020-04-20",
        "use_deuterostome_filter": true,
        "use_taxon_whitelist": false
      },
      "Postprocess": {
        "index_version": "2020-04-20",
        "use_deuterostome_filter": true,
        "use_taxon_whitelist": false
      },
      "Experimental": {
        "index_version": "2020-04-20",
        "file_ext": "fastq",
        "use_taxon_whitelist": false
      }
    },
    "OutputPrefix": "s3://idseq-samples-ENV/samples/PROJECT_ID/SAMPLE_ID/results",
    "HOST_FILTER_WDL_URI": "s3://idseq-workflows/v1/main/host_filter.wdl",
    "NON_HOST_ALIGNMENT_WDL_URI": "s3://idseq-workflows/v1/main/non_host_alignment.wdl",
    "POSTPROCESS_WDL_URI": "s3://idseq-workflows/v1/main/postprocess.wdl",
    "EXPERIMENTAL_WDL_URI": "s3://idseq-workflows/v1/main/experimental.wdl"
  }
  ```
  - `OutputPrefix` is the S3 prefix where pipeline output will be deposited (the output of the step function will
     reference all output elements)
  - `HOST_FILTER_WDL_URI` is the fully qualified S3 URI referencing the WDL file for the host filter stage
  - `NON_HOST_ALIGNMENT_WDL_URI` is the fully qualified S3 URI referencing the WDL file for the non-host alignment stage
  - `POSTPROCESS_WDL_URI` is the fully qualified S3 URI referencing the WDL file for the postprocess stage
  - `EXPERIMENTAL_WDL_URI` is the fully qualified S3 URI referencing the WDL file for the experimental stage
- Optional:
  - AWS Batch memory usage quotas (defaults defined in idseq/lambdas/sfn-io-helper-lambda/.chalice/config.json):
    - `HostFilterSPOTMemory`
    - `HostFilterEC2Memory`
    - `NonHostAlignmentSPOTMemory`
    - `NonHostAlignmentEC2Memory`
    - `PostprocessSPOTMemory`
    - `PostprocessEC2Memory`
    - `ExperimentalSPOTMemory`
    - `ExperimentalEC2Memory`

Given these inputs, the step function loads the appropriate pipeline WDLs and runs them. Each WDL runs in a separate
Batch job as configured in the pipeline metadata JSON. The `Input` object is given to the first WDL. The output of this
WDL is saved as a value under the `Output` key in the step function state, then passed as input to the next WDL, and so
on until the pipeline completes.

## Resolving step function execution outputs

Outputs are deposited in S3 in paths under `OutputPrefix`. The specific locations of the outputs are listed in the step
function output JSON object, which can be retrieved by running:
```
aws stepfunctions get-execution-history --execution-arn ARN | jq -r .events[-1].executionSucceededEventDetails.output | jq .Result
```

#### Resolving SFN outputs before the execution completes

The long-term solution for resolving SFN outputs while it's still running will be to implement a push notification bus
where tasks can send URIs of their outputs as soon as they become ready.

Until this is in place, we rely on the following convention to reconstruct the output path prefix for pipeline results:

* Assume we are executing the state machine `arn:aws:states:us-west-2:732052188396:stateMachine:SFN_NAME-SFN_VERSION`.
* Assume the `OutputPrefix` parameter is set to `s3://idseq-samples-staging/samples/518/19420/results`.
* Assume the WDL URIs are set to `s3://idseq-workflows/vWDL_VERSION/PIPELINE_NAME/STAGE_NAME.wdl`.
* Then the results will appear at the prefix
  `s3://idseq-samples-staging/samples/518/19420/results/SFN_NAME-SFN_VERSION/PIPELINE_NAME-WDL_VERSION/` (for example,
  `s3://idseq-samples-staging/samples/518/19420/results/idseq-staging-main-1/main-2/`.

## Invoking the workflow by starting the step function

* Retrieve or reconstruct the deployed Step Function ARN (for example, using `terraform output --json | jq -r
  .idseq.value.idseq_main_sfn_arn`).

* Start the step function using input formatted using the JSON template under "Required Inputs" above.

The helper script `run_sfn.py` provides a reference implementation that takes an environment name, project ID, sample
ID, and key input parameters such as host genome. It starts the step function execution, monitors it, prints out the
logs, and forwards the exit code.

`run_sfn.py` contains defaults to run the [main](https://github.com/chanzuckerberg/czid-workflows/tree/main/main)
pipeline, but it can also run any other pipelines in czid-workflows. The following invocation runs the
[single-wdl](terraform/sfn_templates/single-wdl-1.yml) SFN and gives it the workflow from
https://github.com/chanzuckerberg/czid-workflows/blob/main/phylotree/run.wdl, published to s3 at
s3://idseq-workflows/v0/phylotree/run.wdl using the tag `v0`, on the staging sample 19522 in project 532:
```
scripts/run_sfn.py --environment staging \
                   --project 532 \
                   --sample 19522 \
                   --sfn-name single-wdl \
                   --workflow-name phylotree \
                   --stages run \
                   --workflow-version 0 \
                   --sfn-input '{"Input": {"Run": {"message": "hello world"}}}'
```

**Tip**: When doing workflow development it can be helpful to run your branch of czid-workflows on arbitrary inputs. See the two sections below for instructions on how to do that. If you make a change and want to re-run, you can use the `--output-dir` flag so your new results will be in their own directory instead of overwriting previous results.

### Invoking the workflow with arbitrary inputs

It is convenient to be able to run workflows against existing projects and samples, like in the above example. However, when developing the pipeline you may want to run using arbitrary inputs. To do this, create a directory in s3 and upload your input FASTQ files to `s3://your-bucket/your-directory/fastqs`. You can only add one input per folder (one file if single or two files if paired). Ensure that your environment has permission to access the bucket. It is usually best to make your own directory in the samples bucket for whatever environment you want to run in. Once you've uploaded you can run the pipeline like so:

```
scripts/run_sfn.py --environment staging \
                   --sample-dir s3://your-bucket/your-directory \
                   --sfn-name single-wdl \
                   --workflow-name phylotree \
                   --stages run \
                   --workflow-version 0 \
                   --sfn-input '{"Input": {"Run": {"message": "hello world"}}}'
```

### Invoking the workflow for a branch of idseq-workflow

If you are developing new features in [czid-workflows](https://github.com/chanzuckerberg/czid-workflows) it may be helpful to run the step function against your development branch as if it was deployed. This is supported by the `run_sfn.py` helper script via the `--czid-workflows-branch` flag. To use this flag:

1. Push your branch to [czid-workflows](https://github.com/chanzuckerberg/czid-workflows)
1. Make sure you:
    - Have the appropriate AWS credentials for `idseq-dev` and `idseq-prod` (`idseq-prod` is needed regardless of environment for uploading WDL workflows)
    - Have docker installed
    - Python dependencies are up to date with `requirements-dev.txt`.
1. Source the appropriate workflows environment (probably `dev`): `source environment.dev`
1. Run `scripts/run_sfn.py` with the appropriate parameters, adding `--czid-workflows-branch your-branch-name`

**Notes**:

- Tip: Pull your workflow's docker image or build it locally before running to benefit from the docker build cache.
- If your docker image fails to build with this error: `E: Failed to fetch http://security.ubuntu.com/ubuntu/pool/main/c/curl/libcurl4_7.58.0-2ubuntu3.8_amd64.deb 404 Not Found [IP: 54.191.70.203 80`. Wait a few minutes for the server to come back online, navigate to `czid-workflows/your-workflow-name` in your local clone of [czid-workflows](https://github.com/chanzuckerberg/czid-workflows), and run `docker build --no-cache -t $DOCKER_IMAGE_ID .` where `$DOCKER_IMAGE_ID` is the docker image ID logged by the `run_sfn.py` script before the docker build in the form: `  building docker image: DOCKER_IMAGE_ID`.
- The `--workflow-version` flag will be ignored. Running the workflow for a branch is incompatible with running a workflow version.
- The `--stages` flag will be ignored. Running the workflow for a branch means using the stages from that branch so this flag makes no sense to use together with the `--czid-workflows-branch` flag.
- If you add a `docker_image_id` to the inputs of any of your stages it will be overwritten with the appropriate docker image ID for the branch of [czid-workflows](https://github.com/chanzuckerberg/czid-workflows) you passed in. This is because running the workflow for a branch means using the docker image from that branch so it is incompatible with passing in a custom docker image.

**How does it work?**

[czid-workflows](https://github.com/chanzuckerberg/czid-workflows) is the source of the WDL files defining the workflow and the docker image each workflow step is run on. This docker image also specifies the code from the `idseq_dag` library that is used by the workflow. Running the workflow for a branch means running using that branch's WDL files and using the docker image that would be built by that branch, which includes any `idseq_dag` code changes on that branch.

When you run the `run_sfn.py` script with the `--czid-workflows-branch` tag the script:

- Clones the repo at the head of the specified branch into a temporary directory
- Uploads the WDL files to the appropriate place in S3
- Pulls the docker image for the czid-workflows version specified by `--wdl-version` (defaults to latest version)
- Builds the docker image from the cloned repo, using the pulled docker image as the build cache
- Deletes the cloned git repository
- Pushes this docker image to the appropriate ECR repository with the appropriate tag
- Sets the workflow URIs and `docker_image_id`s in the step function input to the uploaded WDL files and docker image ID respectively
- Runs the step function with this input and print the logs until it terminates
- Deletes the uploaded WDL files
- Removes the branch image from ECR

## Reporting errors
### Raising errors in WDL tasks
To report an error with structured metadata (error name and details) from within a WDL task:
- Exit the shellcode of the task with a non-zero exit status.
- Print the following as the last line of the stderr stream:
  ```
  {"wdl_error_message": true, "error": "ErrorClassName", "cause": "details of the error"}
  ```
This will cause the step function to recognize the error name and cause, and raise it as described below.

### Picking up errors from SFN output
Workflow errors can originate at several levels, and are propagated through the call stack using a combination of
error handling logic in miniwdl and the step function helper Lambda. Any error originating in the workflow has a type
and message associated with it. For errors that originate in Python, the exception name and message are automatically
used as this type and message. Errors can originate in:

- WDL task code
- The WDL interpreter or executor
- The Batch job shellcode
- The Batch API
- A Lambda helper function
- The Step Functions API

Regardless of the origin, the error will propagate to a `FAILED` status for the step function execution. The last event
in the execution history will be a `ExecutionFailed` event, and its description will contain the following JSON:

    "executionFailedEventDetails": {
      "error": "SampleError",
      "cause": "{\"errorMessage\":\"Invalid fastq/fasta file\",\"errorType\":\"RuntimeError\",\"stackTrace\":[\"  File \\\"/var/task/app.py\\\", line 73, in handle_failure\\n    raise failure_type(cause)\\n\"]}"
    }

## Defining and deploying pipeline versions

Pipeline versions are embodied as static WDL files in the
[czid-workflows](https://github.com/chanzuckerberg/czid-workflows) repo. They are published to `s3://idseq-workflows`
from all git tags (releases) defined in that repo. To publish a new pipeline version, commit a new tag to the repo and
run `make publish` while in the idseq-prod account, then use those WDL file URLs as SFN input.

## Updating the SFN-WDL interface

The top level pipeline interface is defined by the I/O interface of the step function. The step functions are encoded
as YAML files in the [terraform/sfn_templates](terraform/sfn_templates) directory, and deployed via code in
[terraform/sfn.tf](terraform/sfn.tf). The name of the step function (like `idseq-dev-main-1`) ends in the major version,
which should be changed when the interface changes in breaking ways.
