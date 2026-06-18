# Maintenance register — cypherid-workflow-infra

**Purpose.** A complete inventory of what in this repo is kept current automatically
(SSOT version files + Renovate) versus what a human must maintain by hand, with the
exact file path and in-file location of each. If it's in the "human-maintained" table,
nothing will remind you — so this list is how we avoid silently drifting.

> ⚠️ **Renovate is configured (`renovate.json`) but the GitHub app is not enabled yet
> (CZID-212).** Until it is, *everything* below is effectively human-maintained. The
> "Automated" table describes the intended steady state once the app is on.

> ℹ️ **Layout note.** This is a single flat root OpenTofu module (not a multi-stack
> `_shared/`-prefixed layout). There is no `_shared/versions.tf`, no per-stack `key`s,
> no `tofu-ci-skip.txt`, and no `terraform_remote_state` anywhere. The SSOT for providers
> is the root `versions.tf` (declares only `aws`); `test/versions.tf` is a symlink to it.

## A. Human-maintained (Renovate / SSOT cannot track these)

| # | Item | Where (path → location in file) | Why it's manual | How to update |
|---|------|--------------------------------|-----------------|---------------|
| A1 | OpenTofu `required_version` floor | `versions.tf` → `terraform { required_version = ">= 1.10" }` | Renovate bumps provider constraints, not the core `required_version`; the floor encodes a feature requirement (native S3 `use_lockfile` locking) | Edit by hand when a new core feature is needed; keep `.opentofu-version` (B1) at or above it |
| A2 | Local-path module sources | `terraform/idseq.tf` (lines 12,16,20,24,31), `terraform/alignment.tf` (lines 20,55), `terraform/cloudwatch-alerting.tf` (line 3), `main.tf` (`module "idseq" source = "./terraform"`), `test/mock.tf` (`source = "../terraform"`) | Renovate cannot version-bump a local relative path | No version maintenance; keep paths valid when modules move |
| A3 | S3 backend config (injected at init, not in HCL) | `main.tf` → `terraform { backend "s3" { region/use_lockfile } }`; bucket + key supplied via `TF_CLI_ARGS_init` / `TF_S3_BUCKET=tfstate-$AWS_ACCOUNT_ID[-test]` in `environment` (lines ~48–52) | Backend bucket/key are computed in the `environment` shell shim, not committed HCL, so Renovate/SSOT never see them | Maintain in `environment` per env; the per-env `aws_config.json` is generated/local, not committed |
| A4 | Per-environment account aliases & owner | `environment.dev` (`EXPECT_AWS_ACCOUNT_ALIAS=seqtoid-dev`), `environment.staging` (`seqtoid-staging`), `environment.prod` (`idseq-prod`), `environment.sandbox` (`cypherid-dev`); `OWNER=…` in `environment` | Hardcoded org/account identifiers and owner | Hand-edit when accounts/owners change |
| A5 | Hardcoded AWS account IDs / ARNs | `.github/workflows/deploy.yml` line 31 (`role-to-assume: arn:aws:iam::941377154785:role/gha-seqtoid` — load-bearing OIDC role); `scripts/simple_run_sfn.py` lines 21–23; `scripts/run_sfn.py` line 251; `scripts/generate_host_genome.py` line 240; commented IDs in `terraform/buckets.tf` / `terraform/batch_queue.tf` | Literal account numbers / ARNs in workflow + Python; no datasource | Hand-edit on any account migration |
| A6 | Lambda IAM policy templates | `lambdas/*/.chalice/policy-test.json`, `lambdas/*/policy-template.json`, `terraform/iam_policy_templates/*.json` | Bespoke IAM JSON with placeholders / resource ARNs | Hand-edit when permissions/resources change |
| A7 | Provider **list membership** | `versions.tf` → `required_providers { aws }` (only `aws` declared) | Renovate bumps the *constraint* of listed providers (B2), but adding/removing a provider is a human edit | Add the `required_providers` entry by hand when a new provider is introduced |
| A8 | Transitive niche providers kept OUT of `versions.tf` | `hashicorp/template` (2.2.0), `archive`, `null` — visible only in `.terraform.lock.hcl`, pulled transitively from `github.com/chanzuckerberg/swipe` | Deprecated `template` has no `darwin_arm64` build (see `validate.yml` header); intentionally not surfaced so the root constraint stays AWS-only | Re-lock if swipe stops needing them; otherwise leave unmanaged |
| A9 | Lambda Docker base images (not digest-pinned) | `lambdas/Dockerfile` line 3 (`FROM python:3.8`), `lambdas/taxon-indexing-concurrency-manager/Dockerfile` line 1 (`FROM node:18`), `local-base-images/Dockerfile.python-base` line 1, `local-base-images/Dockerfile.node-base` line 1 | Bare floating major tags; `pinDigests:true` *would* pin them once Renovate runs, but major tags won't auto-advance | Bump base tags by hand until Renovate is confirmed live (then verify it pinned digests) |
| A10 | CI workflow logic | `.github/workflows/validate.yml` (the `make package-lambdas` codegen step, lockfile-drift gate, the `insteadOf ssh→https` swipe shim); `environment` (generates `terraform/variables.tf`) | Bespoke build orchestration | Hand-edit when the build process changes |
| A11 | Provider lockfile platform set | `.terraform.lock.hcl`; relock command (per `validate.yml`): `tofu providers lock -platform=linux_amd64 -platform=darwin_amd64` | The *platform list* is a human decision; Renovate updates hashes but not which platforms you lock for | Re-run `tofu providers lock` with the intended `-platform` flags; CI gate enforces it's committed & current |
| A12 | Python version pin | `.python-version` → `3.9` (consumed by `check.yml` `setup-python` via `python-version-file`) | No Renovate manager is configured for `.python-version` (the only custom manager targets `.opentofu-version`) | Hand-edit; note lambda runtimes (`python:3.8` images) lag this |

## B. Automated — SSOT version files + Renovate

| # | Item | Where (path → location in file) | Maintained by |
|---|------|--------------------------------|---------------|
| B1 | OpenTofu CLI version (SSOT) | `.opentofu-version` → `1.12.1`; consumed by `validate.yml`/`plan_call.yml` via `tofu_version_file` | Renovate custom regex manager (`renovate.json`, `depName opentofu/opentofu`, github-releases) |
| B2 | AWS provider version constraint (SSOT) | `versions.tf` → `required_providers { aws = { version = "~> 4.54" } }`; symlinked `test/versions.tf` | Renovate `terraform` manager (grouped "terraform providers"); lockfile re-locked & CI-gated |
| B3 | External `?ref=`-pinned module — swipe | `terraform/swipe.tf` line 2 → `source = "github.com/chanzuckerberg/swipe?ref=v1.4.9"` | Renovate `terraform` manager (grouped "terraform providers") |
| B4 | GitHub Actions `uses:` pins | `.github/workflows/*.yml` (`actions/checkout@v6`, `actions/cache@v5`, `setup-python@v6`, `opentofu/setup-opentofu@v2`, `aws-actions/configure-aws-credentials@v6.1.0`, `thorvath-slower/flake8-action@v2`, …) | Renovate `github-actions` manager (grouped "github actions") |
| B5 | Lambda base-image digests | the four Dockerfiles in A9 | Renovate `dockerfile` manager (grouped "docker base images") with `pinDigests:true` — once the app is live (currently unpinned, see A9) |
| B6 | pip deps | `requirements-dev.txt`; `lambdas/*/requirements.txt` (cloudwatch-alerting, pipeline-monitor-restarter, sfn-io-helper, taxon-indexing, taxon-indexing-eviction) | Renovate `pip_requirements` manager (grouped "pip deps") |
| B7 | npm deps | `lambdas/taxon-indexing-concurrency-manager/package.json` + `package-lock.json` | Renovate `npm` manager (grouped "npm deps") |
| B8 | Vulnerability bumps | repo-wide | Renovate `vulnerabilityAlerts.enabled: true` |

## When you add something, update the register

Add a new module, backend wiring, hardcoded account/ARN, provider, base image, Action,
or requirements file → add a row here in the same shape. If a human has to remember to
bump it, it belongs in **table A**; if Renovate (or an SSOT version file) covers it, put
it in **table B** with the manager named. The `thorvath-slower/flake8-action@v2` ref is a
moving tag, not a SHA — its content is rolled out by moving the tag in that repo (CZID-204).
