# WDL Workflow Versioning & Publication (#335 / feature 20021)

How seqtoid WDL pipelines are versioned, published, promoted, and selected at run time.

## 1. Versioning scheme (already in place — documented here as SSOT)

- **One semantic version per workflow**, expressed as a **git tag** `WORKFLOW_NAME-vX.Y.Z`
  in the workflows repo (e.g. `short-read-mngs-v8.3.11`, `consensus-genome-v3.5.5`). The monorepo is
  **not** versioned as a whole — each workflow advances independently. (~14 such tags exist today.)
- The `version 1.1` inside `.wdl` files is the **WDL language spec** version — unrelated to the app version.
- A published version is an **immutable triple**: the git tag + a Docker image + the WDL/JSON bundle in S3.

## 2. What "publish" produces

`scripts/publish_wdl_workflows.sh WORKFLOW_NAME-vX.Y.Z` (or the **Publish WDL Workflow Version** GitHub
Action) builds + uploads, for that tag:

| Artifact | Location |
|---|---|
| Docker image | `${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${WORKFLOW_NAME}:vX.Y.Z` |
| WDL / JSON / `.wdl.zip` | `s3://seqtoid-workflows-${ENV}-${ACCOUNT}/${WORKFLOW_NAME}-vX.Y.Z/...` |

## 3. The bucket migration this change lands (the #335 fix)

**Before:** the publish script hardcoded the legacy **single shared, public** bucket `s3://idseq-workflows`
and gated on the `idseq-prod` account — leftover from before the per-env bucket refactor (20032).

**After:** it targets the **per-environment, private** bucket
`seqtoid-workflows-${DEPLOYMENT_ENVIRONMENT}-${AWS_ACCOUNT_ID}` (defined in `terraform/buckets.tf`), which
**blocks all public access**. Consequently:
- the **`--acl public-read` was dropped** — it would be *rejected* by the per-env buckets' public-access
  block. Consumers read via account-root IAM (how the Step Functions / miniwdl dispatch already fetches).
- the `idseq-prod` account gate is replaced by a **`head-bucket` existence check** — each environment
  publishes into its own account's bucket.

## 4. ⚠️ Consumer cutover — NOT done in this change (needs coordination)

The **producer** (this script/action) now writes to per-env buckets, but several **consumers still read the
legacy `idseq-workflows`** path. Flipping only the producer would break dispatch, so this PR intentionally
stops at the producer + the design. The coordinated cutover (its own reviewed PR + an env-by-env rollout) is:

- [ ] `scripts/run_sfn.py` — S3 WDL/stage-io URIs (`s3://idseq-workflows/...`)
- [ ] `scripts/simple_run_sfn.py` — hardcoded `idseq-workflows`
- [ ] `lambdas/sfn-io-helper/chalicelib/stage_io.py` — image/uri construction
- [ ] **seqtoid-web** — any `s3://idseq-workflows` references in dispatch services / AppConfig seeds
- [ ] Backfill: re-publish current versions into each per-env bucket before flipping readers
- [ ] Then retire the legacy `idseq-workflows` bucket

## 5. Version selection at run time (already implemented in seqtoid-web)

1. **Per-project override** — `ProjectWorkflowVersion` (a project can pin a specific version).
2. **Environment default** — `AppConfig` key `"<workflow_name>-version"` (e.g. `short-read-mngs-version` → `8.3.11`).
3. The chosen version is recorded on each run (`WorkflowRun.wdl_version`) and rendered as the tag
   `"<workflow>-v<version>"` to resolve the S3 bundle + ECR image.

> `run_sfn.py` has a fallback that queries the GitHub tags API for the latest version when none is given —
> fine for ad-hoc runs, but production dispatch should always pin via AppConfig, never the floating latest.

## 6. Promotion (dev → staging → prod)

A released version is promoted by **publishing it into each environment** and then **activating** it there:

1. Tag the workflow (`WORKFLOW_NAME-vX.Y.Z`) in the workflows repo.
2. Run **Publish WDL Workflow Version** for `environment: dev` → validate.
3. Repeat for `staging`, then `prod` (each publishes into that env's bucket + ECR).
4. **Activate** by setting `AppConfig["<workflow>-version"]` in that environment (today a manual/admin step
   — automating it is a follow-up below).

## 7. Immutability

The per-env buckets have **versioning enabled**. A published `WORKFLOW_NAME-vX.Y.Z/` prefix should be treated
as **write-once** — never overwrite a released version; cut a new tag instead. (Future hardening: S3 Object
Lock / a republish guard on existing version prefixes.)

## 8. Follow-ups (tracked under #335)

- The **consumer cutover** in §4 (the coordinated reader migration).
- **Clone source rebrand:** the publish script still clones `chanzuckerberg/czid-workflows`; move to the
  `seqtoid-workflows` fork once it carries the tags + Dockerfiles.
- **Automate activation:** set the `AppConfig` version as part of promotion instead of a manual DB edit.
