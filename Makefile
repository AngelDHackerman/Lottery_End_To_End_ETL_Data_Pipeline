# Loteria Santa Lucia — task runner.
#
# Stubbed in PR-001, filled in by PR-039. Assumes an activated .venv (`pip install -e
# '.[dev]'`) and the variables in .envrc.example. First deploy into an account, in order:
#
#   make bootstrap   remote state bucket + lock table (once per account)
#   make secrets     the Secrets Manager secret the IAM module looks up by name
#   make deploy      build, terraform apply, upload the Glue artifacts
#
# That order has never been run from zero — the stack was built by importing a running
# pipeline (PR-004 onward). See roadmap.md PR-040.

.PHONY: bootstrap secrets lock lock-upgrade build tf-init deploy upload-glue test dq dq-sync destroy lint fmt tf-plan lineage-views uy-backfill uy-pilot uy-report uy-golden-urls uy-incremental uy-silver uy-dq uy-dq-sync uy-dq-lock uy-dq-lock-upgrade uy-dq-build

# Glue's three artifacts are the only deploy inputs Terraform does not upload (see
# scripts/build_glue_package.sh and build_dq_package.sh). Same default as those scripts.
CODE_BUCKET ?= lambda-code-zip-prod

# The bootstrap stack keeps LOCAL state (it creates the remote backend, so it cannot use
# it). terraform/bootstrap/terraform.tfstate is gitignored — lose it and this target tries
# to create a bucket that already exists.
bootstrap: ## Create the remote Terraform state backend (PR-003/PR-039)
	cd terraform/bootstrap && terraform init && \
	  terraform apply -var="aws_account_id=$$(aws sts get-caller-identity --query Account --output text)"
	@echo "Next: cp terraform/backend.hcl.example terraform/backend.hcl and fill in the bucket."

secrets: ## Create the pipeline secret in Secrets Manager; refuses if it exists (PR-039)
	bash scripts/seed_secrets.sh

# PR-046. The layer is the only build artifact that pip-installs anything, so it is the
# only one with a lock. Regenerating is deliberate on purpose: it bumps the layer hash, and
# that shows up as a real `terraform plan` diff which someone has to read and approve.
#
#   make lock          recompile from requirements/extractor.txt, keeping pins that still
#                      satisfy it (use after editing the input)
#   make lock-upgrade  recompile AND take upstream releases (use when you mean to bump)
lock: ## Recompile requirements/extractor.lock from its input (PR-046)
	pip-compile --generate-hashes --strip-extras \
	  --output-file requirements/extractor.lock requirements/extractor.txt

lock-upgrade: ## Same as `lock`, but allow transitive dependencies to move forward (PR-046)
	pip-compile --generate-hashes --strip-extras --upgrade \
	  --output-file requirements/extractor.lock requirements/extractor.txt

build: ## Build the lambda layer + code zip + the glue transformer + DQ artifacts (PR-019/PR-033)
	bash scripts/build_lambda_layer.sh
	bash scripts/build_lambda_function.sh
	bash scripts/build_glue_package.sh
	bash scripts/build_dq_package.sh

tf-init: ## terraform init the main stack against backend.hcl (PR-039)
	@test -f terraform/backend.hcl || { \
	  echo "terraform/backend.hcl is missing — cp terraform/backend.hcl.example terraform/backend.hcl"; \
	  exit 1; }
	cd terraform && terraform init -backend-config=backend.hcl -input=false

# `build` is a prerequisite, not a suggestion: filemd5/filebase64sha256 read the Lambda
# zips at PLAN time (PR-019), so an apply without a fresh build ships whatever zip was last
# left in terraform/. The build is reproducible (PR-046), so an unchanged tree plans clean.
#
# The upload runs AFTER the apply, and only if it succeeded — answering "no" at the prompt
# exits non-zero and make stops. Before this target, a `src/` change redeployed the Lambda
# through Terraform and silently left both Glue jobs on the old code.
deploy: build tf-init ## Build, terraform apply the main stack, upload the Glue artifacts (PR-039)
	cd terraform && terraform apply
	$(MAKE) upload-glue

# Separate target so it can be re-run alone. The three objects go together: the DQ script
# imports loteria.dq from the DQ zip, and a mismatch fails at import inside the job.
upload-glue: ## Upload the Glue transformer + DQ artifacts built by `make build` (PR-039)
	aws s3 cp dist/lottery_transformer.zip s3://$(CODE_BUCKET)/lottery_transformer.zip
	aws s3 cp dist/loteria_silver_dq.py s3://$(CODE_BUCKET)/loteria_silver_dq.py
	aws s3 cp dist/loteria_dq_lib.zip s3://$(CODE_BUCKET)/loteria_dq_lib.zip

# No --cov here: the coverage flags and the fail-under ratchet live in pyproject.toml's
# addopts (PR-029). Repeating them in this file would guarantee the two drift.
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

# Belt and braces: the data buckets and the state bucket carry prevent_destroy, so a full
# destroy fails at plan time anyway. This guard is for everything that does not.
destroy: ## Tear down the main stack; refuses unless CONFIRM=YES (PR-039)
	@test "$(CONFIRM)" = "YES" || { \
	  echo "Refusing: this destroys the production pipeline. Re-run with CONFIRM=YES."; \
	  exit 1; }
	$(MAKE) tf-init
	cd terraform && terraform destroy

# The same three commands CI's lint job runs (.github/workflows/ci.yml), so a green
# `make lint` means a green lint job.
lint: ## Lint python + terraform, exactly as CI does (PR-039)
	ruff check .
	ruff format --check .
	terraform fmt -check -recursive terraform/

fmt: ## Format python + terraform (PR-039)
	ruff format .
	terraform fmt -recursive terraform/

# Builds first for the same reason `deploy` does: a plan against stale zips shows a diff
# that is not this change's.
tf-plan: build tf-init ## Build, then terraform plan the main stack into terraform/tfplan (PR-039)
	cd terraform && terraform plan -out=tfplan

# PR-045.2. NOT part of `deploy`: the two views are created once and CREATE OR REPLACE is
# only interesting when the SQL in sql/lineage/ changes. Wiring them into the weekly Step
# Function would add two states to the pipeline to recreate, every Thursday, metadata that
# has not moved. Re-run this after editing the SQL, or to restore a view dropped by hand.
#
# ⚠️ It needs the Silver tables to carry the lineage columns, which is the Terraform half of
# PR-045.2 — run it AFTER that apply, or the CREATE fails on a column Athena cannot see.
lineage-views: ## Create/replace the Silver lineage views in Athena (PR-045.2)
	bash scripts/create_lineage_views.sh

# ---------------------------------------------------------------------------------------
# Uruguay extension — LOCAL ONLY during the beta (roadmap-uruguay.md). Nothing below touches
# AWS. Raw pages land in data/uy/bronze/ and the manifest in data/uy/manifest.sqlite, both
# gitignored. Every target can be stopped and re-run: the manifest skips what is final.
# PYTHONPATH=src because the package is not installed ([tool.uv] package = false).
# ---------------------------------------------------------------------------------------
UY_START ?= 2006-08-01
UY_END ?= today
UY_SOURCES ?= resultados,extractos
UY_MANIFEST ?= data/uy/manifest.sqlite

uy-pilot: ## One year (2016, crosses the layout change) — validates before the full run
	PYTHONPATH=src python -m sorteos.uy.backfill --start 2016-01-01 --end 2016-12-31 --sources $(UY_SOURCES)

uy-backfill: ## Full raw backfill to local bronze (several hours at 1 req/s; resumable)
	PYTHONPATH=src python -m sorteos.uy.backfill --start $(UY_START) --end $(UY_END) --sources $(UY_SOURCES)

uy-report: ## Manifest summary: states per source and the date span of each
	PYTHONPATH=src python -m sorteos.uy.backfill --report

uy-golden-urls: ## Every URL in the manifest must come out of the YAML again (UY-020; read-only)
	PYTHONPATH=src python scripts/uy_golden_urls.py $(UY_MANIFEST)

UY_SILVER ?= data/uy/silver
UY_YEARS ?=

uy-incremental: ## Daily run: last 7 days + every open key, all four sources, then silver for the years touched (UY-027.1)
	PYTHONPATH=src python -m sorteos.uy.incremental --silver $(UY_SILVER)

uy-silver: ## Rewrite local UY silver from bronze: every year, or UY_YEARS=2016 / 2014-2016,2026 (UY-027.1; no requests)
	PYTHONPATH=src python -m sorteos.uy.build_silver --silver $(UY_SILVER) $(if $(UY_YEARS),--years $(UY_YEARS))

uy-dq: ## Validate local UY silver against its Great Expectations suites (UY-026; read-only)
	PYTHONPATH=src python -m sorteos.uy.dq.runner --silver $(UY_SILVER)

uy-dq-sync: ## Regenerate qa/uy/expectations/ from src/sorteos/uy/dq/suites.py (UY-026)
	PYTHONPATH=src python -m sorteos.uy.dq.runner --sync-suites

# UY-026.2: the DQ job's dependencies for AWS Glue 5.0 (Python 3.11), as one zip of wheels.
# The lock is resolved for Glue's target, not for the Python running it, so any 3.12 works.
uy-dq-lock: ## Recompile requirements/uy-dq.lock + uy-dq-glue-base.lock, keeping current pins (UY-026.2)
	python scripts/uy_dq_lock.py

uy-dq-lock-upgrade: ## Same as uy-dq-lock, but let the pins move forward (UY-026.2)
	python scripts/uy_dq_lock.py --upgrade

uy-dq-build: ## Build dist/uy/uy_dq.gluewheels.zip from the lock + the sorteos wheel (UY-026.2; no AWS)
	bash scripts/build_uy_dq_package.sh
