# cypherid-workflow-infra — onboarding guide

> Current-state, junior-engineer-friendly onboarding for **this** repo. Part of
> the documentation epic (#394); tracked as #397. It describes what is actually
> in the repo today — not a target state. When in doubt, the files it points at
> are the source of truth.
>
> Naming note: the platform is being renamed **idseq/czid → seqtoid**. The prose
> uses "seqtoid", but the code, AWS resource names, and module names still use
> the legacy `idseq-*` convention (see the top of the root `README.md`). Both are
> correct; treat them as synonyms while reading.

---

## Overview

This is the **Terraform/AWS infrastructure** for the seqtoid bioinformatics
**pipeline / workflow execution** plane. It provisions the compute and glue that
run the metagenomics pipeline — it does **not** contain the pipeline logic (WDL
lives in the public [`czid-workflows`](https://github.com/chanzuckerberg/czid-workflows)
repo) and it does **not** contain the web app (`idseq-web`).

What it provisions (all in `us-west-2`):

| Area | What it is | Where |
| --- | --- | --- |
| **swipe** | The Step-Functions + AWS Batch workflow engine that runs WDL pipeline steps. Vendored external module. | `terraform/swipe.tf` |
| **Batch compute** | Batch compute environments, job queues, job definitions, and the Batch VPC/subnets. | `terraform/batch_*.tf` |
| **Alignment** | Scalable Batch alignment fleets (e.g. `diamond`, `minimap2`). | `terraform/alignment.tf`, `terraform/modules/scalable-alignment-batch` |
| **Index generation** | EC2/Batch machinery that builds the taxonomy/reference indexes. | `terraform/index-generation.tf`, `terraform/start_index_generation_lambda_src` |
| **Lambdas** | Chalice-packaged lambdas (SFN I/O helper, taxon indexing + concurrency + eviction, pipeline-monitor restarter, CloudWatch alerting). | `lambdas/`, `terraform/modules/*` |
| **Buckets / ECR / KMS** | S3 buckets (+ access logs), ECR repos, KMS keys. | `terraform/buckets.tf`, `terraform/ecr.tf`, `terraform/kms.tf` |
| **Observability** | CloudWatch dashboards + alerting lambda. | `terraform/cloudwatch-*.tf` |
| **CI/CD infra** | Self-hosted runner user-data and CI/CD IAM. | `terraform/ci-cd.tf` |

State is stored in an **S3 backend** with **native S3 state locking**
(`use_lockfile = true`, no DynamoDB table) — see `main.tf`.

---

## Repo layout

```
.
├── main.tf                  # root module: backend (s3), aws provider, module "idseq" -> ./terraform, output
├── versions.tf              # SSOT for required_version + aws provider constraint (CZID-169)
├── variables.tf (generated) # written by `source environment` from EXPORT_ENV_VARS_TO_TF (do not hand-edit)
├── environment              # the base env script: sourced to set DEPLOYMENT_ENVIRONMENT, account checks, TF_* vars
├── environment.{dev,staging,prod,sandbox,test}  # per-env wrappers that set the env + expected account alias
├── Makefile                 # deploy / plan / package-lambdas / templates / check / test targets
├── bin/check                # local mirror of CI gates (`make check`)
├── .python-version (3.12)   # lambda + tooling python
├── .terraform-version (1.15.7)
│
├── terraform/               # the actual infra (this is module "idseq")
│   ├── *.tf                 # swipe, batch, alignment, index-generation, buckets, ecr, kms, cloudwatch, ci-cd, idseq
│   ├── modules/             # per-lambda + alignment modules (chalice.tf.json is generated into these)
│   ├── sfn_templates/       # Step Functions state machines as .yml (rendered to .json by `make templates`)
│   ├── iam_policy_templates/, cloudwatch_dashboard_templates/
│   └── start_index_generation_lambda_src/
│
├── lambdas/                 # lambda SOURCE code (built into terraform/modules/* by the codegen)
│   ├── Dockerfile           # default builder: python:3.12 + `chalice package --pkg-format terraform`
│   ├── run_lambda_tests.sh  # the lambda unit-test harness (CI: lambda-tests.yml)
│   ├── sfn-io-helper/, taxon-indexing/, taxon-indexing-concurrency-manager/,
│   ├── taxon-indexing-eviction/, pipeline-monitor-restarter/, cloudwatch-alerting/
│   └── <each>/.chalice/config.json + policy-template.json + requirements.txt
│
├── scripts/package_lambda.py   # the codegen driver (chalice -> chalice.tf.json + deployment.zip)
├── local-base-images/          # base Dockerfiles for building lambda images locally
├── glue_jobs/                  # AWS Glue job source (batch-index-taxons)
├── test/                       # moto/localstack mock stack + python unit tests
├── docs/                       # this guide + WORKFLOW-VERSIONING.md
└── .github/workflows/          # CI (see "CI gates" below)
```

The root `README.md`, `MAINTENANCE.md`, `Interface.md`, `Security.md`, and
`lambdas/README.md` cover release process, maintenance, and how to author a new
lambda in depth. This guide is the map; those are the deep dives.

---

## The lambda codegen coupling (read this before running any terraform)

**Terraform in this repo cannot `init`/`validate`/`plan`/`apply` from a clean
checkout.** Several `terraform/modules/*` reference a generated file,
`chalice.tf.json`, that is **not committed** — it is a build artifact. You must
generate it first:

```bash
source environment.test      # or environment.dev, etc. — sets DEPLOYMENT_ENVIRONMENT
make package-lambdas         # runs scripts/package_lambda.py
```

`make package-lambdas` → `scripts/package_lambda.py` does, per lambda:

1. Reads `lambdas/<name>/.chalice/config.json`; templates
   `policy-template.json` → `.chalice/policy-<env>.json` (substituting env vars
   like `AWS_ACCOUNT_ID`, `AWS_DEFAULT_REGION`, `DEPLOYMENT_ENVIRONMENT`).
2. **Builds a Docker image** (`lambdas/Dockerfile`, `FROM python:3.12`) that runs
   `chalice package --pkg-format terraform` to emit the module.
3. `docker cp`s the artifacts out of the container into `terraform/modules/<name>/`:
   - `chalice.tf.json` — the generated Terraform (JSON, but referenceable HCL) for the lambda + its resources
   - `deployment.zip` — the lambda code bundle
4. **Patches `chalice.tf.json`**: deletes chalice's hardcoded
   `terraform.required_version`, and (in `test`) drops `aws_lambda_permission`
   (moto doesn't support it).

Because the generated modules are consumed by `terraform init`, **every**
terraform-invoking Make target lists `package-lambdas` as a prerequisite
(`deploy`, `plan`), and CI runs it as a `prepare` step before validate/security.

### Version coupling — why this bit historically hurt (#443 → #446)

Chalice's generated `chalice.tf.json` **pins the AWS provider to `< 5`**. The
repo needs AWS provider **5.x** (it targets the `python3.12` lambda runtime),
which chalice's old codegen did not know about — this was the #443 pain point.
The fix (per #446):

- The repo is on **chalice `~=1.33`** and **AWS provider `~> 5.31`**
  (`versions.tf`: `5.31` "knows the python3.12 lambda runtime the chalice
  codegen now emits").
- `scripts/package_lambda.py` relaxes chalice's `< 5` pin so terraform's
  provider-version **intersection** allows the `~> 5.31` pin to win.

Practical consequences:

- **Docker is required** to run terraform locally (the codegen builds an image).
- The generated files are **transient** — `.gitignore`'d, never committed;
  `make clean` removes them (`terraform/modules/*/chalice.tf.json`,
  `*deployment.zip`).
- The committed `.terraform.lock.hcl` is **not** generated on Apple Silicon —
  the vendored swipe module's `hashicorp/template` provider has no
  `darwin_arm64` build. The lockfile is generated/committed by the
  `terraform-lock.yml` workflow (linux/amd64), and `validate` only *gates* on it
  (fails if it drifts). See `docs/WORKFLOW-VERSIONING.md`.

---

## Environments & stacks

There is **one** Terraform root module (`./terraform`, wired in via `main.tf`).
Environments are selected at runtime by **sourcing an environment script**, not
by separate stack directories.

| Env | Script | Expected AWS account alias | Notes |
| --- | --- | --- | --- |
| `dev` | `environment.dev` | `seqtoid-dev` | default dev environment |
| `staging` | `environment.staging` | (per script) | released from `staging` branch |
| `prod` | `environment.prod` | (per script) | released from `prod`/`main` branch; deploy guarded |
| `sandbox` | `environment.sandbox` | (per script) | experimentation |
| `test` | `environment.test` | `idseq-local` | **no live AWS** — moto/localstack mock (`test/`), used by CI |

What sourcing an environment does (`environment`):

- sets `DEPLOYMENT_ENVIRONMENT`, `APP_NAME=idseq`, `TF_DATA_DIR=.terraform.<env>`;
- for non-`test`, calls `aws sts get-caller-identity` / `list-account-aliases`
  and **aborts if the account alias doesn't match** the expected one (guards
  against deploying to the wrong account; override with
  `EXPECT_AWS_ACCOUNT_ALIAS`);
- resolves the S3 backend bucket (`tfstate-<account>-test` for dev/sandbox,
  `tfstate-<account>` otherwise) and sets `TF_CLI_ARGS_init` / `TF_CLI_ARGS_output`;
- **generates `terraform/variables.tf`** from `EXPORT_ENV_VARS_TO_TF` — so
  `variables.tf` is a build product; do not hand-edit it.

`test` is special: it uses **local state**, mock SSM params, and the `test/`
stack (moto server). The `templates` target strips `Memory` from SFN templates
in `test` because moto can't model it.

---

## CI gates (`.github/workflows/`)

All the no-AWS gates run automatically on PRs/pushes. The AWS-touching ones
(`plan`, `deploy`) are `workflow_dispatch`-only until GitHub Environments + OIDC
roles are fully wired (CZID-81/26).

| Workflow | Gate | Runs | Notes |
| --- | --- | --- | --- |
| `validate.yml` | **terraform-ci** (fmt + init + validate) | auto (PR/push) | thin caller of the SSOT reusable `thorvath-slower/seqtoid-ci-workflows/.github/workflows/terraform-ci.yml@v1`; runs `make package-lambdas` (codegen) as `prepare`, then `terraform validate` with `-backend=false`; also `check_lockfile: true` (fails on lockfile drift) |
| `check.yml` | **flake8** (python lint) | auto (PR/push) | uses the modernized flake8 action in `thorvath-slower/seqtoid-ci-workflows@v1` |
| `security.yml` | **checkov / tflint / trivy / gitleaks** | auto (PR/push/merge_group) | calls the shared reusable `thorvath-slower/ci-workflows`; **checkov is a hard gate** (`checkov_soft_fail: false`) against `.checkov.baseline` (~50 inherited findings accepted, CZID-264 — gate on **NEW** findings only); runs codegen as `prepare` so scanners see the full config |
| `lambda-tests.yml` | **Lambda unit tests** | auto (PR/push) | `bash lambdas/run_lambda_tests.sh` — pure pytest-mock unit tests, no live AWS; builds a clean venv per lambda (CZID-344) |
| `actionlint.yml` | GitHub Actions workflow lint | auto | |
| `plan_only.yml` / `plan_call.yml` | `terraform plan` | **manual** (dispatch) | assumes an AWS OIDC role; posts a plan summary |
| `deploy.yml` | `make deploy` (`terraform apply`) | **manual** (dispatch) | gated by the GitHub **Environment** (prod requires reviewer approval, C4); OIDC into `role/gha-seqtoid` |
| `terraform-lock.yml` | regenerate + commit `.terraform.lock.hcl` | **manual** | linux/amd64 only (arm64 can't build the template provider) |
| `publish-workflows.yml` | publishes reusable workflows | — | |

**Run the gates locally before pushing** (local == CI, CZID-311):

```bash
make check     # -> bin/check: terraform fmt + flake8 + codegen/validate + trivy/tflint/gitleaks
```

`make check` is the one Make target exempt from the "source environment first"
guard; it sources `environment.test` itself for the codegen/validate step and
**skips-with-a-note** any scanner you don't have installed
(`brew install terraform trivy tflint gitleaks`).

---

## How to make a change (gated-PR flow)

1. **Branch off `integration`** (the working trunk for this fork):
   ```bash
   git fetch origin
   git checkout -B <ticket>-<short-desc> origin/integration
   ```
2. Make your change. Keep PRs **small and single-concern** (project doctrine).
3. **Validate locally** (needs Docker for the codegen):
   ```bash
   source environment.test
   make package-lambdas        # generate chalice.tf.json + deployment.zip
   make check                  # fmt + lint + validate + scanners
   ```
   To see a plan against a real account instead:
   ```bash
   source environment.dev
   make plan                   # package-lambdas + templates + init + terraform plan
   ```
4. Push and open a **gated PR into `integration`** — do **not** self-merge; the
   CI gates above must be green and the change reviewed/signed off.
5. Reference the ticket in the commit + PR body.

Deploys are **not** part of the PR flow — they run manually via `deploy.yml`
(dispatch), OIDC-authenticated, gated by the GitHub Environment. Never
`terraform apply` by hand outside that flow.

---

## Runbook / gotchas

- **`Please run "source environment"` from make** → you didn't source an
  environment. Run `source environment.dev` (or `.test`, etc.) first. Only
  `make check` is exempt.
- **Terraform can't find `chalice.tf.json` / a module fails to init** → run
  `make package-lambdas` first. It's a generated artifact, not committed.
- **`make package-lambdas` needs Docker running** — it builds a `python:3.12`
  image per lambda. No Docker = no codegen = no terraform.
- **AWS provider version-constraint conflicts (`must use terraform init -upgrade`,
  `< 5` vs `~> 5.31`)** → this is the chalice-pin issue. Confirm you're on the
  current `versions.tf` (`aws ~> 5.31`) and re-run `make package-lambdas` so the
  patched `chalice.tf.json` (relaxed to `< 6`) is regenerated. Deleting
  `.terraform.<env>` + `.terraform.lock.hcl` and re-initing clears stale caches
  (see `terraform/README.md` Debugging).
- **Lockfile drift fails `validate`** → do **not** try to regenerate
  `.terraform.lock.hcl` on Apple Silicon (the swipe `template` provider has no
  arm64 build). Run the `terraform-lock` workflow (dispatch) to regenerate +
  commit it on linux/amd64.
- **"wrong AWS account" abort on `source environment.<env>`** → the account
  alias didn't match the expected one. That's the safety net working; only set
  `EXPECT_AWS_ACCOUNT_ALIAS` if you genuinely mean to target a different account.
- **`variables.tf` shows up modified in git** → it's generated by
  `source environment` from `EXPORT_ENV_VARS_TO_TF`. Don't commit incidental
  churn to it; don't hand-edit it.
- **New checkov/trivy finding fails `security.yml`** → the gate hard-fails on
  findings **not** in `.checkov.baseline` / `.trivyignore`. Fix the finding, or
  (if it's genuinely inherited/accepted) add it to the baseline deliberately —
  don't blanket-skip.
- **`test` env behaves differently** → it uses local state + moto mocks; SFN
  `Memory` is stripped and `aws_lambda_permission` is dropped from generated
  modules because moto can't model them. Real behavior only shows on a real
  account plan.

---

## Where to go next

- `README.md` — release/deployment process, branch model (main→staging→prod).
- `MAINTENANCE.md` — routine maintenance.
- `lambdas/README.md` — authoring a new lambda (chalice and non-chalice).
- `docs/WORKFLOW-VERSIONING.md` — the reusable-workflow pinning + lockfile story.
- `terraform/README.md` — terraform-level debugging.
- `Interface.md` / `Security.md` — the pipeline interface and security posture.
