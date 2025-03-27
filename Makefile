SHELL=/bin/bash -o pipefail

ifndef DEPLOYMENT_ENVIRONMENT
$(error Please run "source environment" in the repo root directory before running make commands)
endif

deploy: package-lambdas templates init-tf
	@if [[ $(DEPLOYMENT_ENVIRONMENT) == staging && $$(git symbolic-ref --short HEAD) != staging ]]; then echo Please deploy staging from the staging branch; exit 1; fi
	@if [[ $(DEPLOYMENT_ENVIRONMENT) == prod && $$(git symbolic-ref --short HEAD) != prod ]]; then echo Please deploy prod from the prod branch; exit 1; fi
	terraform apply

# NOTE: moto errors on creating ssm parameters that begin with aws or ssm
deploy-mock: templates package-lambdas
	aws ssm put-parameter --name /mock-aws/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id --value ami-12345678 --type String --endpoint-url http://localhost:9000
	(cd test; rm -rf .terraform* terraform.tfstate; unset TF_CLI_ARGS_init; terraform init; terraform apply --auto-approve)

plan: package-lambdas templates init-tf
	terraform plan

templates:
	for sfn_tpl in terraform/sfn_templates/*.yml; do yq . $$sfn_tpl > $${sfn_tpl/.yml/.json}; done
	if [[ $(DEPLOYMENT_ENVIRONMENT) == test ]]; then sed -i '/Memory/ d' terraform/sfn_templates/*.json; fi

$(TFSTATE_FILE):
	terraform state pull > $(TFSTATE_FILE)

init-tf:
	-rm -f $(TF_DATA_DIR)/*.tfstate
	mkdir -p $(TF_DATA_DIR)
	jq -n ".region=\"us-west-2\" | .bucket=env.TF_S3_BUCKET | .key=env.APP_NAME+env.DEPLOYMENT_ENVIRONMENT" > $(TF_DATA_DIR)/aws_config.json
	terraform init

package-lambdas:
	python3 scripts/package_lambda.py

build-local-lambda-images: clean package-lambdas
	docker build -f ./local-base-images/Dockerfile.python-base -t indexing-lambda:local ./terraform/modules/taxon-indexing
	docker build -f ./local-base-images/Dockerfile.node-base -t concurrency-lambda:local ./terraform/modules/taxon-indexing-concurrency-manager
	docker build -f ./local-base-images/Dockerfile.python-base -t eviction-lambda:local ./terraform/modules/taxon-indexing-eviction

lint:
	flake8 .
	statelint
	find . -name '*.py' | grep -v '^./scripts' | grep -v '.venv' | xargs -n 1 mypy --check-untyped-defs --no-strict-optional

test:
	python3 -m unittest discover --start-directory test --top-level-directory . --verbose

test-one:
	python3 -m unittest --verbose $(path)

system-test:
	test/system_test.py --verbose

clean:
	git clean -fx .terraform.* test/.terraform.* terraform/chalice.tf.json terraform/modules/*/chalice.tf.json terraform/modules/*/*deployment.zip *-lambda/.chalice/deployments
	rm -rf taxon-indexing-lambda/concurrency-manager/node_modules

.PHONY: deploy deploy-mock plan templates init-tf package-lambdas lint clean
