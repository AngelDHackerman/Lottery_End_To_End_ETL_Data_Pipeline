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

.PHONY: bootstrap secrets lock lock-upgrade build tf-init deploy upload-glue test dq dq-sync destroy lint fmt tf-plan lineage-views uy-backfill uy-pilot uy-report uy-golden-urls uy-properties uy-incremental uy-silver uy-reconcile uy-estadisticas uy-dq uy-gold-local uy-gold-build uy-dq-sync uy-dq-lock uy-dq-lock-upgrade uy-dq-build uy-dq-run uy-bronze-sync uy-bronze-check uy-manifest-migrate uy-manifest-check uy-fetch-lock uy-fetch-build uy-fetch-check uy-fetch-probe uy-fetch-incremental uy-silver-pending uy-silver-lock uy-silver-image uy-silver-local uy-silver-push uy-silver-invoke uy-silver-backfill uy-silver-reconcile uy-sfn-run uy-catalog-sync uy-tf-init uy-tf-plan uy-deploy

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

uy-properties: ## Every rule over the whole local bronze, in memory; fails only on quarantine (UY-027.2; no requests)
	PYTHONPATH=src python -m sorteos.uy.properties

UY_SILVER ?= data/uy/silver
UY_YEARS ?=

# UY-043.3.2: the nightly run moved to the cloud (lottery-uy-pipeline-prod, 23:30 Montevideo).
# The local manifest.sqlite is frozen as a backup since 2026-10-31; a local run would fetch into
# it, never into DynamoDB, and the two would drift (owner, UY-043.3 2a). UY_LOCAL=1 is the way
# back for a deliberate local run. uy-silver, uy-reconcile and uy-dq stay as they were.
uy-incremental: ## LOCAL daily run, off since UY-043.3.2 (the cloud runs it): needs UY_LOCAL=1 (UY-027.1)
	@test -n "$(UY_LOCAL)" || { \
	  echo "The nightly run lives in the cloud since UY-043.3.2: make uy-sfn-run starts it by hand."; \
	  echo "A local run writes to the frozen data/uy/manifest.sqlite, not to DynamoDB. UY_LOCAL=1 to do it anyway."; \
	  exit 1; }
	PYTHONPATH=src python -m sorteos.uy.incremental --silver $(UY_SILVER)

uy-silver: ## Rewrite local UY silver from bronze: every year, or UY_YEARS=2016 / 2014-2016,2026 (UY-027.1; no requests)
	PYTHONPATH=src python -m sorteos.uy.build_silver --silver $(UY_SILVER) $(if $(UY_YEARS),--years $(UY_YEARS))

uy-reconcile: ## Reconcile local UY silver: calendar, draw_gaps, draw number, quarantine, the site's counts (UY-030; read-only)
	PYTHONPATH=src python -m sorteos.uy.reconcile --silver $(UY_SILVER)

uy-estadisticas: ## Ask ver_estadisticas for the site's own counts, into bronze, and compare (UY-030.2; ~12 POSTs)
	PYTHONPATH=src python -m sorteos.uy.estadisticas --silver $(UY_SILVER)

uy-dq: ## Validate local UY silver against its Great Expectations suites (UY-026; read-only)
	PYTHONPATH=src python -m sorteos.uy.dq.runner --silver $(UY_SILVER)

# UY-032 / UY-044.2: gold is SQL written once, for Athena (sql/uy/gold/), and run here as it is
# with DuckDB over the local silver. From a worktree, point UY_SILVER at the main tree's.
UY_GOLD ?= data/uy/gold
uy-gold-local: ## Build local UY gold with DuckDB from sql/uy/gold/ and print expected vs observed (UY-044.2; no AWS)
	python scripts/uy_gold_local.py --silver $(UY_SILVER) --out $(UY_GOLD)

# UY-042.1: local bronze to S3 (P15: uy/raw/ + the path under data/uy/bronze/). These two DO
# touch AWS, with whatever AWS_PROFILE is set. From a worktree, point UY_BRONZE at the main
# tree's data/uy/bronze. No --delete: S3 is about to be the copy that outlives the disk, and
# the bucket's Deny (PR-002) refuses deletes anyway. *.tmp is a write that did not finish.
# Run uy-bronze-check first: before the upload it is the dry run (how many files S3 lacks).
UY_BRONZE ?= data/uy/bronze
UY_BUCKET ?= lottery-partitioned-storage-prod

uy-bronze-sync: ## Upload local UY bronze to s3://$(UY_BUCKET)/uy/raw/, then check it (UY-042.1; writes to S3)
	@test -d $(UY_BRONZE)/country=uy || { echo "$(UY_BRONZE) has no country=uy/ — set UY_BRONZE"; exit 1; }
	aws s3 sync $(UY_BRONZE)/ s3://$(UY_BUCKET)/uy/raw/ --exclude '*.tmp' --only-show-errors
	$(MAKE) uy-bronze-check

uy-bronze-check: ## Every local bronze file is in S3 with the same size and MD5 (UY-042.1; read-only)
	PYTHONPATH=src python -m sorteos.uy.bronze_sync --root $(UY_BRONZE) --bucket $(UY_BUCKET)

# UY-042.2: the manifest to DynamoDB (D28, P16), once. Writes with whatever AWS_PROFILE is set;
# from a worktree, point UY_MANIFEST at the main tree's data/uy/manifest.sqlite. Safe to run
# again (it writes only what is missing or differs) and it refuses once the cloud is ahead.
UY_MANIFEST_TABLE ?= lottery-uy-manifest-prod

uy-manifest-migrate: ## Copy $(UY_MANIFEST) to DynamoDB and prove it item by item (UY-042.2; writes to DynamoDB)
	PYTHONPATH=src python -m sorteos.uy.manifest_migrate --sqlite $(UY_MANIFEST) --table $(UY_MANIFEST_TABLE)

uy-manifest-check: ## Prove the DynamoDB manifest equals $(UY_MANIFEST), item by item and through the interface (UY-042.2; read-only)
	PYTHONPATH=src python -m sorteos.uy.manifest_migrate --sqlite $(UY_MANIFEST) --table $(UY_MANIFEST_TABLE) --check

# UY-042.3: the fetch Lambda (D29). The lock pins everything with hashes and is constrained by
# requirements/extractor.lock, so a bump there needs `make uy-fetch-lock` here too (CI says so).
# The zip must exist before `make uy-tf-plan`, which builds it; it is byte-identical for the
# same lock and code, so an unchanged tree never redeploys the function.
UY_FETCH_FUNCTION ?= lottery-uy-fetch-prod

uy-fetch-lock: ## Recompile requirements/uy-fetch.lock from uy-fetch.txt (UY-042.3)
	pip-compile --generate-hashes --strip-extras \
	  --output-file requirements/uy-fetch.lock requirements/uy-fetch.txt

uy-fetch-build: ## Build dist/uy/uy_fetch.zip: sorteos + the lock, for python3.12 x86_64 (UY-042.3; no AWS)
	bash scripts/build_uy_fetch_package.sh

# UY-043.2.1: #156 deployed a zip whose handler could not be imported (pyarrow). This runs the
# handler's code from the zip with only the zip, the stdlib and boto3; uy-tf-plan needs it.
uy-fetch-check: uy-fetch-build ## Import and run the fetch Lambda's code from its zip, with only what Lambda has (UY-043.2.1; no AWS)
	python scripts/uy_fetch_smoke.py dist/uy/uy_fetch.zip

# D26: asks the site for the newest draw of each source FROM THE LAMBDA and compares the bytes
# with the manifest. Writes nothing. Fails if the Lambda errors or any key did not answer 200.
uy-fetch-probe: ## Invoke the fetch Lambda in probe mode: does the site answer it without a proxy? (UY-042.3; read-only)
	@mkdir -p dist/uy
	@aws lambda invoke --function-name $(UY_FETCH_FUNCTION) --cli-binary-format raw-in-base64-out \
	  --cli-read-timeout 330 --payload '{"mode": "probe"}' dist/uy/probe.json \
	  --query FunctionError --output text | grep -qx None \
	  || { cat dist/uy/probe.json; echo; echo "The fetch Lambda failed (see above)"; exit 1; }
	@python -m json.tool dist/uy/probe.json
	@python -c "import json, sys; sys.exit(0 if json.load(open('dist/uy/probe.json'))['ok'] else 1)"

# UY-043.2: the nightly fetch, by hand until the Scheduler of UY-043.3. UY_DRY_RUN=1 asks the
# site and writes nothing (the report says what would change); a real run writes bronze, the
# manifest and the years PENDING#silver hands to `make uy-silver-pending`.
uy-fetch-incremental: ## Invoke the fetch Lambda in incremental mode; writes bronze + manifest unless UY_DRY_RUN=1 (UY-043.2)
	@mkdir -p dist/uy
	@aws lambda invoke --function-name $(UY_FETCH_FUNCTION) --cli-binary-format raw-in-base64-out \
	  --cli-read-timeout 960 \
	  --payload '{"mode": "incremental"$(if $(UY_DRY_RUN),$(comma) "dry_run": true)}' \
	  dist/uy/fetch.json --query FunctionError --output text | grep -qx None \
	  || { cat dist/uy/fetch.json; echo; echo "The fetch Lambda failed (see above)"; exit 1; }
	@python -m json.tool dist/uy/fetch.json

# UY-042.4.1: the silver Lambda image (D29). Its tag is a hash of its inputs, not of the image
# (docker builds are not reproducible), so an unchanged tree has the same tag: uy-silver-push
# finds it in ECR and pushes nothing, and uy-tf-plan sees no change. Needs Docker (with buildx).
# --provenance=false: buildx would otherwise push an image index with an attestation, and
# Lambda only accepts a plain image manifest.
UY_SILVER_TAG = $(shell python3 scripts/uy_silver_tag.py)
UY_SILVER_REPO ?= lottery-uy-silver-prod
UY_SILVER_FUNCTION ?= lottery-uy-silver-prod
UY_SILVER_LOCAL ?= lottery-uy-silver
UY_YEAR ?= 2011
DOCKER ?= docker
comma := ,

uy-silver-lock: ## Recompile requirements/uy-silver.lock from uy-silver.txt (UY-042.4.1; slow: pyarrow's wheels)
	pip-compile --generate-hashes --strip-extras \
	  --output-file requirements/uy-silver.lock requirements/uy-silver.txt

uy-silver-image: ## Build the silver image locally as lottery-uy-silver:<content tag> (UY-042.4.1; no AWS)
	bash scripts/build_uy_silver_context.sh >/dev/null
	$(DOCKER) buildx build --platform linux/amd64 --provenance=false --load \
	  -f docker/uy-silver/Dockerfile -t $(UY_SILVER_LOCAL):$(UY_SILVER_TAG) build/uy-silver-context

# The image under Lambda's own emulator (it ships in the base image), against the REAL table
# and bucket, as a dry run: it reads bronze, the manifest and uy/silver/, builds UY_YEAR and
# uploads nothing. The credentials go in as environment variables, never on the command line.
uy-silver-local: uy-silver-image ## Run the image locally on UY_YEAR as a dry run against AWS (UY-042.4.1; read-only)
	@mkdir -p dist/uy
	@eval "$$(aws configure export-credentials --format env)" && \
	  $(DOCKER) run -d --rm --name uy-silver-local -p 9000:8080 \
	    -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
	    -e AWS_DEFAULT_REGION=us-east-1 -e AWS_LAMBDA_FUNCTION_TIMEOUT=900 \
	    -e AWS_LAMBDA_FUNCTION_MEMORY_SIZE=2048 \
	    -e MANIFEST_TABLE=lottery-uy-manifest-prod -e SILVER_BUCKET=$(UY_BUCKET) \
	    -e SILVER_PREFIX=uy/silver/ -e BRONZE_PREFIX=uy/raw/ \
	    $(UY_SILVER_LOCAL):$(UY_SILVER_TAG) >/dev/null
	@sleep 2; curl -sS -X POST http://localhost:9000/2015-03-31/functions/function/invocations \
	  -d '{"years": [$(UY_YEAR)], "dry_run": true}' -o dist/uy/silver-local.json; \
	  status=$$?; $(DOCKER) stop uy-silver-local >/dev/null; test $$status -eq 0
	@python -m json.tool dist/uy/silver-local.json

uy-silver-push: ## Build and push the silver image to ECR, unless its tag is already there (UY-042.4.1; writes to ECR)
	@if aws ecr describe-images --repository-name $(UY_SILVER_REPO) \
	     --image-ids imageTag=$(UY_SILVER_TAG) >/dev/null 2>&1; then \
	  echo "$(UY_SILVER_REPO):$(UY_SILVER_TAG) is already in ECR: nothing to push"; \
	else \
	  set -e; \
	  uri=$$(aws ecr describe-repositories --repository-names $(UY_SILVER_REPO) \
	    --query 'repositories[0].repositoryUri' --output text); \
	  aws ecr get-login-password | $(DOCKER) login --username AWS --password-stdin "$${uri%%/*}"; \
	  $(MAKE) uy-silver-image; \
	  $(DOCKER) tag $(UY_SILVER_LOCAL):$(UY_SILVER_TAG) "$$uri:$(UY_SILVER_TAG)"; \
	  $(DOCKER) push "$$uri:$(UY_SILVER_TAG)"; \
	fi

# D18's measurement: one year in the deployed Lambda. It WRITES that year (and the reference
# tables) to uy/silver/ unless UY_DRY_RUN=1.
UY_DRY_RUN ?=
uy-silver-invoke: ## Invoke the silver Lambda on UY_YEAR; writes to uy/silver/ unless UY_DRY_RUN=1 (UY-042.4.1)
	@mkdir -p dist/uy
	@aws lambda invoke --function-name $(UY_SILVER_FUNCTION) --cli-binary-format raw-in-base64-out \
	  --cli-read-timeout 960 \
	  --payload '{"years": [$(UY_YEAR)]$(if $(UY_DRY_RUN),$(comma) "dry_run": true)}' \
	  dist/uy/silver.json --query FunctionError --output text | grep -qx None \
	  || { cat dist/uy/silver.json; echo; echo "The silver Lambda failed (see above)"; exit 1; }
	@python -m json.tool dist/uy/silver.json

uy-silver-pending: ## Invoke the silver Lambda on the years in PENDING#silver, then draw_gaps; UY_DRY_RUN=1 writes nothing (UY-043.2)
	@mkdir -p dist/uy
	@aws lambda invoke --function-name $(UY_SILVER_FUNCTION) --cli-binary-format raw-in-base64-out \
	  --cli-read-timeout 960 \
	  --payload '{"pending": true, "finalize": true$(if $(UY_DRY_RUN),$(comma) "dry_run": true)}' \
	  dist/uy/silver-pending.json --query FunctionError --output text | grep -qx None \
	  || { cat dist/uy/silver-pending.json; echo; echo "The silver Lambda failed (see above)"; exit 1; }
	@python -m json.tool dist/uy/silver-pending.json
	@python -c "import json, sys; sys.exit(0 if json.load(open('dist/uy/silver-pending.json'))['ok'] else 1)"

# UY-042.4.2: all of UY silver in the cloud, then the proof. The backfill invokes the silver
# Lambda once per year, in order (owner, 1a), and finalize last; the first error stops it. The
# reconciliation builds local silver NOW into a temporary folder (owner, 2a; data/uy/silver is
# not touched) and compares every table row by row with uy/silver/, ingested_at and run_id
# aside. Run both on the same day: draw_gaps depends on today's date in Uruguay. From a
# worktree, point UY_ROOT at the main tree's data/uy (manifest.sqlite + bronze).
UY_ROOT ?= data/uy

# UY-044.3: the gold Lambda by hand, outside the state machine. A REAL build: it writes a new
# generation under uy/gold/ and swaps the six tables onto it (there is no dry run of gold).
UY_GOLD_FUNCTION ?= lottery-uy-gold-prod
uy-gold-build: ## Invoke the gold Lambda once: build, count, swap and retire the six UY gold tables (UY-044.3; writes uy/gold/)
	@mkdir -p dist/uy
	@aws lambda invoke --function-name $(UY_GOLD_FUNCTION) --cli-binary-format raw-in-base64-out \
	  --cli-read-timeout 200 \
	  --payload '{"run_id": "manual-$(shell date -u +%Y%m%dT%H%M%SZ)"}' \
	  dist/uy/gold-build.json --query FunctionError --output text | grep -qx None \
	  || { cat dist/uy/gold-build.json; echo; echo "The gold Lambda failed (see above)"; exit 1; }
	@python -m json.tool dist/uy/gold-build.json

# UY-043.3.1: the nightly state machine, started by hand. A real run since UY-043.3.2, when the
# local incremental was switched off (one writer on the manifest, G4); UY_DRY_RUN=1 asks the site
# and writes nothing. The Scheduler starts the same thing every night at 23:30 Montevideo.
uy-sfn-run: ## Run the UY state machine once and wait: a REAL run, or UY_DRY_RUN=1 (UY-043.3.1, UY-043.3.2)
	python scripts/uy_sfn_run.py $(if $(UY_DRY_RUN),--dry-run,--real)

uy-silver-backfill: ## Rebuild all UY silver in the cloud, one Lambda invocation per year, then draw_gaps (UY-042.4.2; writes uy/silver/)
	PYTHONPATH=src python -m sorteos.uy.silver_backfill --function $(UY_SILVER_FUNCTION) \
	  --table $(UY_MANIFEST_TABLE) $(if $(UY_YEARS),--years $(UY_YEARS))

uy-silver-reconcile: ## Build local silver now and compare it row by row with uy/silver/ in S3 (UY-042.4.2; read-only)
	PYTHONPATH=src python -m sorteos.uy.silver_compare --root $(UY_ROOT) --bucket $(UY_BUCKET)

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

# UY-043.4: the gate's Glue job, by hand. It only reads uy/silver/. The nightly pipeline runs
# the same job as its last step, and the job runs one at a time: not for 23:30 Montevideo.
UY_DQ_TIMEOUT ?=
uy-dq-run: ## Run the silver DQ Glue job once, wait, print its verdict and its start-up time (UY-043.4; read-only)
	python scripts/uy_dq_run.py $(if $(UY_DQ_TIMEOUT),--timeout $(UY_DQ_TIMEOUT))

# The catalog's tables come from the silver writer's own schemas, through a committed JSON that
# Terraform reads. CI fails if the JSON is stale (tests/unit/sorteos/test_uy_catalog.py).
uy-catalog-sync: ## Regenerate terraform/uy/silver_tables.json from sorteos.core.silver (UY-044.1; no AWS)
	python scripts/uy_catalog_schema.py

# UY-041.1: the Uruguay stack, terraform/uy/, with its own state (uy/terraform.tfstate). It
# never shares an init with the main stack: terraform/backend.hcl names main/terraform.tfstate,
# and a stack initialised against that state would plan to destroy every Santa Lucía resource.
# So the key goes on the command line, last (it overrides any file), and a backend.hcl that
# mentions main/ is refused outright.
uy-tf-init: ## terraform init the UY stack (terraform/uy/) against its own state key (UY-041.1)
	@test -f terraform/uy/backend.hcl || { \
	  echo "terraform/uy/backend.hcl is missing — cp terraform/uy/backend.hcl.example terraform/uy/backend.hcl"; \
	  exit 1; }
	@! grep -q 'main/' terraform/uy/backend.hcl || { \
	  echo "terraform/uy/backend.hcl names the main stack's state; remove its key line"; \
	  exit 1; }
	cd terraform/uy && terraform init -backend-config=backend.hcl \
	  -backend-config=key=uy/terraform.tfstate -reconfigure -input=false

# The plan is saved and checked before anyone can apply it: this stack only ever adds UY
# resources (roadmap Fase 5), so any destroy or replace in it stops here, before review.
uy-tf-plan: uy-tf-init uy-fetch-check uy-dq-build ## Plan the UY stack into terraform/uy/tfplan; fails on any destroy or replace (UY-041.1)
	@aws ecr describe-images --repository-name $(UY_SILVER_REPO) --image-ids imageTag=$(UY_SILVER_TAG) \
	  >/dev/null 2>&1 || { echo "$(UY_SILVER_REPO):$(UY_SILVER_TAG) is not in ECR — run make uy-silver-push first"; exit 1; }
	python scripts/uy_catalog_schema.py --check
	cd terraform/uy && terraform plan -var silver_image_tag=$(UY_SILVER_TAG) -out=tfplan
	terraform -chdir=terraform/uy show -json tfplan | python scripts/uy_sfn_validate.py
	@! terraform -chdir=terraform/uy show -no-color tfplan | grep -E 'will be destroyed|must be replaced' || { \
	  echo "The UY plan destroys or replaces something: not applying it. Review terraform/uy/tfplan."; \
	  exit 1; }

# Applies exactly the plan `make uy-tf-plan` printed and checked. Terraform refuses it if the
# state moved since, so a stale plan never applies.
uy-deploy: ## Apply terraform/uy/tfplan from `make uy-tf-plan` (UY-041.1)
	@test -f terraform/uy/tfplan || { echo "No terraform/uy/tfplan — run make uy-tf-plan first"; exit 1; }
	cd terraform/uy && terraform apply tfplan
