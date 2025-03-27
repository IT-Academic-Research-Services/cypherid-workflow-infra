### Debugging

```
Error: Unsupported Terraform Core version

  on main.tf line 2, in terraform:
  2:   required_version = ">= 0.x.x"

This configuration does not support Terraform version 0.x.x. To proceed,
either choose another supported Terraform version or update this version
constraint. Version constraints are normally set for good reason, so updating
the constraint may lead to other errors or unexpected behavior.

make: *** [init-tf] Error 1
```
- Check your local version with `terraform -v`. If it's older than `required_version`, just upgrade (`brew upgrade terraform` or however you installed it).

```
Error: Failed to query available provider packages

Could not retrieve the list of available versions for provider hashicorp/aws: locked provider registry.terraform.io/hashicorp/aws
x.x.0 does not match configured version constraint ~> x.x; must use terraform init -upgrade to allow selection of new versions
```
- Try deleting `.terraform.dev`, `.terraform.staging`, `.terraform.prod`, `.terraform.lock.hcl` and trying again. This should select for the latest versions.

```
Terraform v0.x.x is already installed
Initializing modules...
Initializing the backend...
Error: Failed to decode current backend config
The backend configuration created by the most recent run of "terraform init"
could not be decoded: unsupported attribute "lock_table". The configuration
may have been initialized by an earlier version that used an incompatible
configuration structure. Run "terraform init -reconfigure" to force
re-initialization of the backend.
make: *** [init] Error 1
```
- Try `make run CMD="init -reconfigure"`

```
Error: InvalidLaunchTemplateName.AlreadyExistsException: Launch template name already in use.
    status code: 400, request id: e41ca4bb-f79a-485f-aea1-2fdd33069720

  with module.idseq.aws_launch_template.idseq_batch_main,
  on terraform/batch_queue.tf line 65, in resource "aws_launch_template" "idseq_batch_main":
  65: resource "aws_launch_template" "idseq_batch_main" {
```
- The above is an example but could apply to any Launch Template.
- If the name is already generated with a user data hash (i.e. changing when relevant content changes), then the name conflict is likely benign.
  - You can find the conflicting names in the TF plan output. Try deleting the Launch Templates manually from AWS Console and then re-applying.


#### Indentation:
- Be careful about indentation when reading the backtraces.
- Just an example below: the `cloudwatch-alerting` line is only related to the version contraint warning. The SQS error is actually unrelated.

```
Warning: Version constraints inside provider configuration blocks are deprecated

  on terraform/modules/cloudwatch-alerting/chalice.tf.json line 77, in provider.template:
  77:       "version": "~> 2"

Error: AccessDenied: Access to the resource https://sqs.us-west-2.amazonaws.com/ is denied.
	status code: 403, request id: 98aca68e-247d-5a35-b9ff-ffbd774cef7e
```