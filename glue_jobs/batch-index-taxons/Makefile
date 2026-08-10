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
# sandbox deliberately maps to the dev profile: the sandbox environment lives IN the dev
# account (environment.sandbox sets EXPECT_AWS_ACCOUNT_ALIAS=seqtoid-dev, and the sandbox
# heatmap stack takes account_id = var.aws_accounts.idseq-dev). It is the "idseq-sandbox-"
# name prefix, not the account, that separates sandbox from dev. staging and prod are
# separate accounts and carry their own profiles.
PROFILE_sandbox ?= idseq-dev
PROFILE_staging ?= idseq-staging
PROFILE_prod ?= idseq-prod

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
@test -n "$(PROFILE)" || { echo "no AWS profile is configured for ENV=$(ENV)" 1>&2; exit 1; }
account_id=$$(aws sts get-caller-identity --profile $(PROFILE) --query Account --output text); \
	test -n "$$account_id" || { echo "could not resolve the AWS account id for profile $(PROFILE)" 1>&2; exit 1; }; \
	aws s3 cp dist s3://idseq-$(ENV)-heatmap-batch-jobs-$$account_id/releases --recursive --profile $(PROFILE)
endef

# Shared by every trigger-<env> target.
define trigger_job
@test -n "$(PROFILE)" || { echo "no AWS profile is configured for ENV=$(ENV)" 1>&2; exit 1; }
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
