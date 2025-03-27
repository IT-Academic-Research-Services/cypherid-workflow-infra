# CZID Infrastructure Security

If you have found a security issue in CZID, or need help, please notify security@czid.org and join
#proj-id-security on the CZI Slack.

This document describes the key elements of the CZID application infrastructure security model.

## Background: Algorithms in CZID workflow infrastructure

The CZID workflow infrastructure processes structured, untrusted DNA/RNA sequence data and associated structured
metadata using a suite of research-grade algorithms which have not been deliberately hardened against malicious input.
We rely on input sanitization, filename parameterization and quoting to protect against basic input string manipulation
attacks, but unknown vulnerabilities in the pipeline of algorithms that we use to analyze the data may be exploitable
to gain shell access to the containers running WDL workflow tasks. To limit the damage from such attacks, we employ
need-based least-privilege access control, defense in depth and compartmentalization of workflow infrastructure.

## AWS account separation

CZID development activities are operated out of the `idseq-dev` AWS account. CZID production activities are operated
out of the `idseq-prod` AWS account.

* Data hosted in the `idseq-prod` account can be used in `idseq-dev`, but data hosted in `idseq-dev` cannot be used in
  `idseq-prod`.
* `idseq-dev` processes can only have at most read-only access to `idseq-prod`. (This applies only to CZID service
  data, like reference indexes, Docker images and workflow (wdl) files as needed; the default is no access across the
  accounts).
* All user (sample) data is treated as confidential to CZID users and may never leave `idseq-prod`. It may only be
  accessed by on-call operators when needed to debug operations issues, or by scientists when authorized by a user in
  a support request. An *individual attribution instance* must be used to access user data as described in
  https://czi.quip.com/ymxaAeuo0Fql/Individual-Attribution-Instances.

The above rules are required to prevent compromised assets in `idseq-dev` from being used to compromise `idseq-prod`.

## Infrastructure-as-code (IaC)

CZID service infrastructure is managed as code wherever possible, using Terraform (the Terraform code for computational
genomics workflow infrastructure resides in this repo; Terraform code for other CZID services is in
https://github.com/chanzuckerberg/idseq-infra). Use of IaC allows us to securely redeploy and rotate assets when needed,
reducing the risk of supply chain compromise/persistent threats in our infrastructure.

*Recommended reading:*
[Terraform Recommended Practices](https://www.terraform.io/docs/cloud/guides/recommended-practices/index.html)

## Credential management

When calling AWS service APIs, CZID services use role credentials instead of persistent IAM user API keys. This allows
the role credentials to be rotated frequently, minimizing the timeframe in which any stolen credential can be used.

We rely on AWS services for service-to-service communications and developer/operator actions as much as possible; for
example, we use AWS Batch queues instead of SSH to dispatch pipeline sub-jobs, and AWS Systems Manager instead of direct
SSH connections to log in to instances when needed for development or operations.

API keys for other services such as Slack, Segment, Sentry, etc. reside in [AWS Secrets
Manager](https://aws.amazon.com/secrets-manager/). This allows access to these secrets to be scoped to specific IAM
roles, and the secrets can be rotated easily.

*Recommended reading:*
[AWS Secrets Manager Best Practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)

## Least privilege role-based IAM access control

CZID service roles mentioned above have need-based IAM policies restricting their access. Source code for these
policies can be found in [terraform/iam_policy_templates](terraform/iam_policy_templates) in this
repo, or using [this search](https://github.com/chanzuckerberg/idseq-infra/search?q=aws_iam_policy_document) in
idseq-infra.

Specific aspects of this privilege separation include:

- czid-web has write access only to the samples bucket for its deployment environment (and the aegea ECS execute
  utility bucket); it only has read access to the samples, references, benchmarks, and workflows buckets.
- The permissioning of the pipeline is mostly handled via policies defined in the
  [swipe](https://github.com/chanzuckerberg/swipe) repository

*Recommended reading:*
[Security best practices in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

## Containerization of workflow tasks

Pipeline algorithms in CZID run in AWS Batch jobs. These jobs run in unprivileged Docker containers on EC2 ECS
container instances. In the future, we plan to further scope down the access control policies for these jobs as follows:

- Jobs have access to only their own sample-specific path within the samples bucket. (This requires replacing the AWS
  Batch-managed job IAM role policy, which cannot be parameterized by the sample ID, with temporary STS credentials
  with [inline session policies](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html) managed by the
  [helper Lambda](https://github.com/chanzuckerberg/idseq/tree/main/lambdas/sfn-io-helper)).
- Using [miniwdl](https://github.com/chanzuckerberg/miniwdl)-administered access control, individual algorithms' WDL
  tasks are forbidden to perform any I/O outside the [SFN-WDL task interface](Interface.md).
- [Command helpers](https://github.com/chanzuckerberg/czid-workflows/blob/main/lib/idseq-dag/idseq_dag/util/command_patterns.py)
  in the legacy idseq-dag codebase are retired and replaced with a complete ban on user-supplied strings in
  shell-interpretable commands.

## Webapp

### No handling of user credentials

CZID uses Auth0 to manage user credentials. This avoids the security risks associated with handling user passwords.

## Questions for code review and architecture improvements
- If a latent injection vulnerability were to exist in the webapp, does it result in read-only SQL access, per-row SQL
  write access, admin SQL access (drop tables), or infra/backup write access (delete snapshots)?
- If a latent injection vulnerability were to exist in the SFN-WDL code or the workflows it runs, does it result in
  read-only S3 access to just the given sample and reference data, read-only S3 access to all samples, read-write S3
  access to all samples, or infra/backup write access (delete bucket)?
- Are there periodic tests for disaster recovery from S3 versioning/RDS snapshots?
- Are there periodic tests or manual audits of IAM policies in effect in the production AWS account (not just the
  Terraform files encoding these policies, but whether the service roles actually have the intended access scope
  restrictions)?
