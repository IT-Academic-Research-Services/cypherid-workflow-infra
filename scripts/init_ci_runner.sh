# This script is sourced by GitHub Actions.

set -a
AWS_DEFAULT_REGION=us-west-2
AWS_DEFAULT_OUTPUT=json
DEBIAN_FRONTEND=noninteractive
TERRAFORM_VERSION=1.3.0
GH_CLI_VERSION=1.7.0
LC_ALL=C.UTF-8
LANG=C.UTF-8
TF_CLI_ARGS_apply="--auto-approve"
set +a

source /etc/profile
sudo apt-get -qq update
sudo apt-get -qq install -o=Dpkg::Use-Pty=0 --yes jq build-essential python3-dev virtualenv zip unzip httpie git shellcheck ruby
sudo gem install --quiet statelint
curl -OLs https://github.com/cli/cli/releases/download/v${GH_CLI_VERSION}/gh_${GH_CLI_VERSION}_linux_amd64.deb
sudo dpkg -i gh_${GH_CLI_VERSION}_linux_amd64.deb
curl -OLs https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip
sudo unzip -o terraform_${TERRAFORM_VERSION}_linux_amd64.zip -d /usr/local/bin
virtualenv --python=python3 .venv
source .venv/bin/activate
if [[ -d ~/.cache ]]; then sudo chown -R $(whoami) ~/.cache; fi
pip install -r requirements-dev.txt

set -x

source environment
