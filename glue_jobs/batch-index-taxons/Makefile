# Every environment-specific value below derives from a single ENV per target.
#
# SMP-1736: the deploy and trigger targets used to spell the bucket name, the Glue job name
# and the --profile as four independent hardcoded strings, so "staging-deploy" and
# "trigger-staging" named staging resources while authenticating with DEV credentials.
# Correcting only the resource name would have made that pairing genuinely work and pushed
# dev artifacts into another environment, so the credentials and the resource names are now
# tied to the same variable and cannot disagree:
#
#   ENV     -> PROFILE_<env>, the AWS CLI profile (overridable from the environment)
#   PROFILE -> the account id, read back via sts get-caller-identity through that SAME
#              profile, so the bucket suffix always names the account being authenticated to
#   ENV     -> bucket    idseq-<env>-heatmap-batch-jobs-<account id>
#   ENV     -> Glue job  idseq-<env>-batch-taxon-indexing
#
# The account suffix is not optional. The bucket is created by cypherid-web-infra
# terraform/envs/<env>/heatmap-optimization/main.tf as
# "idseq-${var.env}-heatmap-batch-jobs-${local.account_id}". The un-suffixed names this file
# used before are legacy CZI buckets that exist in neither UCSF account, so those targets
# could not have worked with any credentials.
#
# staging and prod each live in their own account and carry their own profile.
#
# sandbox has NO default, ON PURPOSE, and both sandbox targets fail closed as a result.
# Which AWS account backs the "sandbox" environment is genuinely unresolved (SMP-1749),
# because two different things are called "sandbox": a real sandbox AWS account
# (941377154785, profile idseq-support), and the per-PR preview-sandbox mechanism that
# spins up isolated environments INSIDE the dev account. The evidence points both ways:
#   - the bucket idseq-sandbox-heatmap-batch-jobs-941377154785 EXISTS, in the sandbox
#     account. The dev account has no sandbox-heatmap bucket at all.
#   - but cypherid-web-infra terraform/envs/sandbox/heatmap-optimization/main.tf builds
#     local.bucket_name from account_id = var.aws_accounts.idseq-dev, so the Glue job
#     READS the dev-suffixed name.
# Terraform and reality disagree and SMP-1749 decides which is wrong. environment.sandbox
# (EXPECT_AWS_ACCOUNT_ALIAS=seqtoid-dev) does not settle it -- it is one of the signals
# that conflates the two meanings. Defaulting to either account would push artifacts to a
# bucket the Glue job does not read, so this stays blank until SMP-1749 lands. Override it
# explicitly to deploy: make sandbox-deploy PROFILE_sandbox=idseq-support
PROFILE_sandbox ?=
PROFILE_staging ?= idseq-staging
PROFILE_prod ?= idseq-prod

# Printed when PROFILE_<env> resolves to nothing. sandbox gets its own text because its
# blank default is a deliberate stop, not an oversight.
PROFILE_HINT = "  Set it explicitly: make $@ PROFILE_$(ENV)=<aws cli profile>"
PROFILE_HINT_sandbox = \
	"  The sandbox account binding is UNRESOLVED (SMP-1749) -- do not guess it." \
	"  idseq-sandbox-heatmap-batch-jobs-941377154785 exists, in the sandbox account" \
	"  941377154785 (profile idseq-support), and the dev account has no sandbox-heatmap" \
	"  bucket at all. But cypherid-web-infra terraform/envs/sandbox/heatmap-optimization/main.tf" \
	"  computes local.bucket_name from account_id = var.aws_accounts.idseq-dev, so the Glue" \
	"  job READS the dev-suffixed name. Terraform and reality disagree; SMP-1749 settles it." \
	"  Picking whichever account makes this command succeed would put the artifacts where" \
	"  the Glue job does not look. Once SMP-1749 lands, pass the profile explicitly:" \
	"      make $@ PROFILE_sandbox=idseq-support"

# Default OpenSearch index generation each environment reindexes into.
INDEXES_sandbox ?= reindex-test
INDEXES_staging ?= reindex-test
INDEXES_prod ?= v5

PROFILE = $(PROFILE_$(ENV))
INDEXES = $(INDEXES_$(ENV))

build:
	rm -rf ./dist && mkdir ./dist
	cp ./main.py ./dist
	cp ./config.py ./dist
	cp ./job.py ./dist

# Shared by every <env>-deploy target. Resolves the account id through the same profile the
# upload authenticates with, and fails closed rather than uploading to a truncated name.
define deploy_release
@test -n "$(PROFILE)" || { echo "$@: no AWS CLI profile is configured for ENV=$(ENV)." 1>&2; printf '%s\n' $(or $(PROFILE_HINT_$(ENV)),$(PROFILE_HINT)) 1>&2; exit 1; }
account_id=$$(aws sts get-caller-identity --profile $(PROFILE) --query Account --output text); \
	test -n "$$account_id" || { echo "could not resolve the AWS account id for profile $(PROFILE)" 1>&2; exit 1; }; \
	aws s3 cp dist s3://idseq-$(ENV)-heatmap-batch-jobs-$$account_id/releases --recursive --profile $(PROFILE)
endef

# Shared by every trigger-<env> target.
define trigger_job
@test -n "$(PROFILE)" || { echo "$@: no AWS CLI profile is configured for ENV=$(ENV)." 1>&2; printf '%s\n' $(or $(PROFILE_HINT_$(ENV)),$(PROFILE_HINT)) 1>&2; exit 1; }
@test -n "$(INPUT_FILE)" || { echo "usage: INPUT_FILE=input_file_name make $@" 1>&2; exit 1; }
aws glue start-job-run \
	--job-name idseq-$(ENV)-batch-taxon-indexing \
	--profile $(PROFILE) \
	--arguments '{"--input_s3_path": "input_files/$(INPUT_FILE)", "--scored_taxon_counts_index_name": "scored_taxon_counts-$(INDEXES)", "--pipeline_runs_index_name": "pipeline_runs-$(INDEXES)"}'
endef

sandbox-deploy: ENV := sandbox
sandbox-deploy: build
	$(deploy_release)

staging-deploy: ENV := staging
staging-deploy: build
	$(deploy_release)

prod-deploy: ENV := prod
prod-deploy: build
	$(deploy_release)

trigger-sandbox: ENV := sandbox
trigger-sandbox:
	$(trigger_job)

trigger-staging: ENV := staging
trigger-staging:
	$(trigger_job)

trigger-prod: ENV := prod
trigger-prod:
	$(trigger_job)

# None of these produce a file of their own name; without this a stray "dist"-adjacent file
# would silently turn a deploy into a no-op.
.PHONY: build sandbox-deploy staging-deploy prod-deploy trigger-sandbox trigger-staging trigger-prod
