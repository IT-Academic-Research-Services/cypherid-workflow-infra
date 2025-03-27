<!-- START -->
----

> **FOR CZIF USE ONLY. This repo belongs to [CZIF](https://wiki.czi.team/display/CZIF2/CZIF+2.0+Home). You should only use this repo for Foundation work. Contact [CZIFHelp@chanzuckerberg.com](mailto:CZIFHelp@chanzuckerberg.com) with questions.**

----
<!-- END -->
# idseq

This is the central repository for IDseq infrastructure and service deployment instrumentation. The IDseq webapp
([idseq-web](https://github.com/chanzuckerberg/idseq-web-private)) and public-facing components that can be reasonably
expected to be reused outside the project, such as the [IDseq CLI](https://github.com/chanzuckerberg/idseq-cli-v2),
are managed in separate repos. WDL files, which embody the logic that goes into the pipeline steps (but not the
configuration of the infrastructure that the pipeline runs on), are in a separate, public repo,
[czid-workflows](https://github.com/chanzuckerberg/czid-workflows).

# CI/CD
We use GitHub Actions for CI/CD.

* Lint and unit tests run on GitHub from jobs in `.github/workflows/sfn-wdl-ci.yml` (triggered on every commit).
* Integration tests run on GitHub from jobs in `.github/workflows/sfn-wdl-ci.yml`, and use mock servers to emulate AWS.
* Deployments and system tests run from jobs in `.github/workflows/sfn-wdl-cd.yml`. These jobs use self-hosted GitHub
  Actions runners. They are triggered when a new GitHub deployment is created using `scripts/create_deployment.sh`.
* Releases (promotions of code from main->staging, or staging->prod) run on GitHub from `.github/workflows/release.yml`.
* Periodic scheduled benchmarks run on our self-hosted runners from `.github/workflows/benchmark.yml`.

## Release and deployment process

### Automated scheduled releases

Follow these steps to do a scheduled release from `staging` to `prod` and from `main` to `staging`: 
1. Launch the [release workflow](https://github.com/chanzuckerberg/idseq/actions/workflows/release.yml) from `staging` branch and use `scheduled` as reason for the release.
2. Launch the [release workflow](https://github.com/chanzuckerberg/idseq/actions/workflows/release.yml) from `main` branch and use `scheduled` as reason for the release.

If you run into issues, check the "Details" section below.

### Details

* The `main` branch is the development branch; it is used to deploy to the *dev* deployment environment.
  * Developers may temporarily take over *dev* for testing and deploy from branches of their choosing after announcing
    on the #proj-idseq-ops channel.
* *Releases* to *staging* happen by overwriting the staging branch with the contents of the main branch, e.g.:
  * `git checkout main`
  * `git pull`
  * `git checkout -B staging`
  * `git push --force origin staging`
* *Releases* to *prod* happen by overwriting the prod branch with the contents of the staging branch, e.g.:
  * `git checkout staging`
  * `git pull`
  * `git checkout -B prod`
  * `git push --force origin prod`
* A *release* (update) to a branch should be followed as soon as possible by a *deployment* from that branch
* Deployments to the staging deployment environment should only happen from the staging branch
* Deployments to the prod deployment environment should only happen from the prod branch
* Releases and deployments happen either automatically or manually.
  * *Automatic releases* are triggered by launching the *Release* workflow in
  https://github.com/chanzuckerberg/idseq/actions (click "Release" then "Run workflow"). An automatic release can only
  happen from the *main* branch (to release code to staging) or from the *staging* branch (to release code to prod), and
  immediately triggers an *automatic deployment*.
  * Regularly scheduled releases consist of releasing current `staging` to `prod` and current `main` to `staging`. Remember to release `staging` to `prod` before releasing `main` to `staging` otherwise you will release `main` straight to `prod`. In practice this means first run the above automatic release with the `staging` branch, then the `main` branch.
  * *Manual releases* happen by running the [release.sh](./scripts/release.sh) script, and trigger an
    *automatic deployment* as well.
  * *Manual deployments* are required if an automatic deployment fails. To perform a manual deployment:
    * Check out the branch to deploy from (main, staging or prod).
    * Make sure the branch is updated properly (either release first following the instructions above, or update the contents of the branch with `git pull`).
    * Install dependencies as described in https://github.com/chanzuckerberg/idseq/tree/main/scripts/init_ci_runner.sh
      * If you have an M1 chip, you may have to install `hashicorp/template` separately with:
        ```
        brew install kreuzwerker/taps/m1-terraform-provider-helper
        m1-terraform-provider-helper activate
        m1-terraform-provider-helper install hashicorp/template -v v2.2.0
        ```
    * Run the deployment 

      to deploy to prod, run the following commands:

      ```
      git checkout prod
      virtualenv --python=python3 venv
      source venv/bin/activate
      pip3 install -r requirements-dev.txt
      export AWS_PROFILE=idseq-prod
      source environment.prod # make sure no errors are printed by this command
      make deploy
      ```

      for staging:

      ```
      git checkout staging
      virtualenv --python=python3 venv
      source venv/bin/activate
      pip3 install -r requirements-dev.txt
      export AWS_PROFILE=idseq-dev
      source environment.staging # make sure no errors are printed by this command
      make deploy
      ```

    The most common reason for an automatic deployment failure is insufficient IAM permissions granted by the ci-cd
    policy (see *IAM permissions for CI/CD runner* below).
  * *Patch releases* (sometimes referred to as "hotfixes" or "release fixes") are necessary when only a specific diff
    needs to be applied to code in staging or prod without releasing all changes/going through a full release cycle.
    Patch releases must follow the following process:
    * The patch commit is merged into the main branch using the standard feature branch/PR process.
    * The resulting commit on main is cherry-picked to the staging branch, either directly or via PR.
    * A new staging deployment is created using the [create_deployment.sh](./scripts/create_deployment.sh) script.
      * If the resulting automatic deployment fails, follow the *manual deployment* process above.
    * The fix is tested on staging to ensure that it works as intended.
    * The resulting commit on staging is cherry-picked to the prod branch, either directly or via PR.
    * A new prod deployment is created using the same process as for staging.
  * If you are having trouble performing release or deployment operations or want to do them in a different manner, chat
    with the team in the #proj-idseq-ops channel.

### Releasing code in *czid-workflows*
* Releases in the czid-workflows repo are managed using a separate mechanism that is decoupled from the
  dev-staging-prod cycle described above. There are multiple workflows (currently, short-read-mngs and
  consensus-genome). Workflow releases are triggered by launching the *Release* workflow in
  https://github.com/chanzuckerberg/czid-workflows/actions (click "Release a WDL workflow" then "Run workflow"). The
  automatic release process creates a git tag of the form WORKFLOW-NAME-v1.2.3 where v1.2.3 refers to the semantic
  versioning formatted version of the workflow. The automatic release process then triggers a
  *wdl environment deployment in the idseq repo*.

* Deployments in the czid-workflows repo are made automatically by a GitHub action that is triggered by the
  *wdl environment deployment*. This action runs `idseq/scripts/publish_wdl_workflows.sh`:
  * This script builds the Dockerfile bundled with the workflow (at `czid-workflows/WORKFLOW-NAME/Dockerfile`),
    uploading the resulting Docker image to ECR as `idseq-WORKFLOW-NAME:v1.2.3`.
  * The script then uploads the WDL files for the workflow to `s3://idseq-workflows/WORKFLOW-NAME-v1.2.3/*.wdl`, where
    they can be used by SFN-WDL. To use the deployed workflow WDLs, idseq-web has to specify the full S3 path to that
    version. To update the default version of the workflow used by idseq-web, configure it via the admin settings page

### Versioning and user-visible versions
The reason czid-workflows releases are decoupled from service/infra releases is that we aim to support multiple
workflow versions simultaneously (where possible), i.e. the user may elect to (re)run an older version of the workflow,
unlike webapp/infra releases which follow a continuous delivery model (only the latest release is supported). We also
aim to keep idseq-workflow WDLs portable (runnable without the rest of idseq), so scientists using IDseq can reproduce
their results and collaborate with us.

IDseq displays pipeline (workflow) versions to the user as a representation of feature improvements, bug fixes, and
reproducibility of analyses. The czid-workflows release tag (WORKFLOW-NAME-v1.2.3) represents to the user the version
of idseq algorithms that processed their data.

The step function version is not presented to the user and is not important for reproducibility or feature purposes. The
step function is treated as a piece of idseq infrastructure that is optional for the purpose of reproducing workflow
results. The interface between the step function and the WDL workflow is expected to be stable and to be an
implementation detail of the idseq infrastructure.

* *swipe*
 * [swipe](https://github.com/chanzuckerberg/swipe) contains much of our pipeline running terraform infrastructure as well
   as a docker image containing the version of miniwdl we are using as well as some plugins. Swipe is deployed by adding
   a git tag for a particular version which also triggers a build of a tagged docker image stored in github. The version
   of swipe in use is set in `terraform/swipe.tf`.
* *idseq-dag (legacy pipeline codebase)*
 * The idseq-dag codebase has been migrated to be bundled within the czid-workflows repo
   (https://github.com/chanzuckerberg/czid-workflows/tree/main/lib/idseq-dag), so idseq-dag is no longer
   independently versioned. To update idseq-dag code, commit changes to the repo, then follow the *czid-workflows*
   release process above to generate and deploy a release tag like short-read-mngs-v1.2.3.

## Deploying a self-hosted GitHub Actions CI/CD runner

This repo manages a launch template that can be used to create GitHub Actions CI/CD runners for our other repositories.
To deploy a GitHub Actions CI/CD runner complete the following steps, replacing `YOUR_GITHUB_REPO` with your repository's
name, not including `chanzuckerberg` (this is done intentionally to avoid accidental use of this template for repositories
outside our organization):

* Go to https://github.com/chanzuckerberg/YOUR_GITHUB_REPO/settings/actions and click "Add new runner"
* Copy the access token from the "Configure" step
* Go to https://console.aws.amazon.com/secretsmanager and add a secret `idseq/(dev|prod)/YOUR_GITHUB_REPO/github_runner_token` containing
  the access token, or run `echo -n ACCESS_TOKEN_VALUE | aegea secrets put idseq/(dev|prod)/YOUR_GITHUB_REPO/github_runner_token`
* Go to https://console.aws.amazon.com/ec2/home#LaunchTemplates and search for "ci-cd" to locate the CI/CD LT
* Launch a new instance using this launch template, replacing `YOUR_GITHUB_REPO` in the `Name` and `github-repo` tags with your repository's name.
* Check back at https://github.com/chanzuckerberg/idseq/settings/actions to verify the self-hosted runner came up
  * If the runner did not come up, log in to the instance and check `/var/log/cloud-init-output.log` for errors

If you are deploying a self hosted GitHub Actions CI/CD runner for this repository specifically:

* Create a test deployment by running `scripts/create_deployment.sh`
* Go to https://github.com/chanzuckerberg/idseq/actions and check that the deployment workflow completed successfully

Otherwise, test your runner in a way appropriate for your repository.

### IAM permissions for CI/CD runner
The CI/CD runner gets its IAM permissions from a combination of policies attached to its IAM role, including managed
policies in `terraform/ci-cd.tf` and the policy in `terraform/iam_policy_templates/ci_cd.json`. For
complex Terraform changes, these permissions may not be sufficient, and you may have to redeploy (`make deploy`) using
your own poweruser privileges before CD starts working again.

### Fixing idseq-web-private runner error `no space left on device`

* `build_dev` corresponds to the instance `idseq-web-ci-cd` in the `idseq-dev` account.
* `build_prod` corresponds to the instance `idseq-web-ci-cd` in the `idseq-prod` account.
* You can verify the instance IDs on [GitHub Settings](https://github.com/chanzuckerberg/idseq-web-private/settings/actions).

#### Method 1: Docker prune

Note: You need to retrieve these .pem files from `s3://idseq-secrets` or `s3://idseq-prod-secrets` in the respective accounts.

1. Connect to the CI-CD instance. Ex:
    * build_dev: `aegea ssh -i ~/.ssh/idseq-dev.pem ubuntu@idseq-web-ci-cd` (formerly idseq-dev-ci-cd)
    * build_prod: `AWS_PROFILE=idseq-prod aegea ssh -i ~/.ssh/idseq-prod.pem ubuntu@idseq-web-ci-cd`

1. Prune the Docker images to free up space. Ex: `sudo docker image prune -a` or similar.

#### Method 2: EBS volume expansion

You can expand the mounted EBS volume without downtime.

1. Find the block device attached to `idseq-web-ci-cd` via EC2 console or CLI.
1. [Expand the volume size](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/requesting-ebs-volume-modifications.html).
1. [Expand the partition and file system size](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html).

#### Method 3: Restart the EC2 instances

1. If needed, terminate the existing `idseq-web-ci-cd` instance.
1. Follow the first steps from `Deploying the self-hosted GitHub Actions CI/CD runner` above until you reach the launch template selection.
1. Select the `dev` or `prod` launch template. Ex: `idseq-dev-ci-cd2020...`
1. Under `Resource tags`, change `Name` to `idseq-web-ci-cd`.
1. Expand `Advanced details`. Expand `User data` at the bottom.
1. In `User data`, replace `https://github.com/chanzuckerberg/idseq` with `https://github.com/chanzuckerberg/idseq-web-private`.
1. Click `Launch instance from template`.
1. Make sure the instance self-registers on [GitHub](https://github.com/chanzuckerberg/idseq-web-private/settings/actions/). If the runner did not come up, log in to the instance and check `/var/log/cloud-init-output.log` for errors.
1. Set the appropriate label `idseq-dev` or `idseq-prod`.
1. Restart your GitHub Actions workflow to verify they're working. They should show up as `Active` on the settings page.

### Got permission denied while trying to connect to the Docker daemon socket

In the GitHub Actions logs, you might see: `Got permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Post http://%2Fvar%2Frun%2Fdocker.sock/v1.24/auth: dial unix /var/run/docker.sock: connect: permission denied`

Try this:
1. SSH into the CI-CD instance (see above).
1. `cd /opt/actions-runner`
1. `sudo ./svc.sh stop`
1. `sudo ./svc.sh start`
1. `sudo ./svc.sh status`
1. See if there are any errors and debug from there.

If this occurs at instance startup:
1. Try `sudo usermod -aG docker root`. GitHub Runner runs with root.
1. Make sure `docker run hello-world` can work within `sudo -i`
