# Loteria Santa Lucia — task runner.
# Targets are stubs for now (PR-001) and get filled in by later PRs.
# See roadmap.md PR-039 for the final implementations.

.PHONY: bootstrap secrets build deploy test dq dq-sync destroy lint fmt tf-plan sagemaker

bootstrap: ## Create the remote Terraform state backend (PR-003/PR-039)
	@echo "TODO(PR-039): cd terraform/bootstrap && terraform init && terraform apply"

secrets: ## Seed Secrets Manager from prompts (PR-039)
	@echo "TODO(PR-039): bash scripts/seed_secrets.sh"

build: ## Build the lambda layer + code zip + the glue transformer + DQ artifacts (PR-019/PR-033)
	bash scripts/build_lambda_layer.sh
	bash scripts/build_lambda_function.sh
	bash scripts/build_glue_package.sh
	bash scripts/build_dq_package.sh

deploy: ## terraform apply the main stack (PR-039)
	@echo "TODO(PR-039): cd terraform && terraform init && terraform apply"

test: ## Run the test suite with coverage (PR-029/PR-039)
	pytest -v

# PR-032. Reads Silver from S3 and exits non-zero if an expectation fails. PR-033 runs the
# same `loteria.dq` code inside the Step Function (via the Glue job built by
# scripts/build_dq_package.sh), so a red `make dq` locally means a red gate in production —
# this is the cheap way to check before an apply. Needs AWS credentials and
# PARTITIONED_BUCKET:
#   make dq PARTITIONED_BUCKET=lottery-partitioned-storage-prod
dq: ## Validate the Silver layer against its Great Expectations suites (PR-032)
	python scripts/run_dq.py

dq-sync: ## Regenerate qa/great_expectations/ from src/loteria/dq/suites.py (PR-032)
	python scripts/run_dq.py --sync-suites

destroy: ## Tear down the stack (guarded; PR-039)
	@echo "TODO(PR-039): refuse unless CONFIRM=YES"

lint: ## Lint python + terraform (PR-039)
	@echo "TODO(PR-039): ruff check && terraform fmt -check"

fmt: ## Format python + terraform (PR-039)
	@echo "TODO(PR-039): ruff format && terraform fmt -recursive"

tf-plan: ## terraform plan the main stack (PR-039)
	@echo "TODO(PR-039): cd terraform && terraform plan -out=tfplan"

sagemaker: ## Apply the optional SageMaker module (opt-in, see terraform/modules/sagemaker)
	cd terraform && terraform apply -var=enable_sagemaker=true -target=module.sagemaker
