# Terraform state backend — bootstrap stack

This small, **standalone** stack creates the remote-state infrastructure that
every other Terraform stack in this repo depends on:

- **S3 bucket** `loteria-tf-state-<AWS_ACCOUNT_ID>` — versioned, SSE-S3 encrypted,
  all public access blocked, `prevent_destroy = true`.
- **DynamoDB table** `loteria-tf-locks` — `PAY_PER_REQUEST`, hash key `LockID`,
  used for state locking.

It intentionally uses **local state** (it is the thing that creates the remote
backend, so it can't depend on it). You run it **once** per account.

## Run once

```bash
cd terraform/bootstrap
terraform init
terraform apply -var="aws_account_id=<YOUR_12_DIGIT_ACCOUNT_ID>"
# region defaults to us-east-1; override with -var="aws_region=..."
```

Look up your account id with: `aws sts get-caller-identity --query Account --output text`.

## After apply

Copy the outputs into the main stack's backend config:

```bash
terraform output          # prints state_bucket_name and lock_table_name
cp ../backend.hcl.example ../backend.hcl
# edit ../backend.hcl: set bucket = state_bucket_name, dynamodb_table = lock_table_name
```

The main stack (`terraform/`, created in PR-006) then runs
`terraform init -backend-config=backend.hcl` to store its state remotely.
PR-004 migrates the existing `terraform-lottery/Prod` state into the same bucket
under the key `legacy/terraform.tfstate`.

## Scope

- Do **not** migrate any existing state here — that is PR-004.
- The local `terraform.tfstate` produced by this stack is small and gitignored.
  If you want it remote too, you can later add a backend block pointing at the
  very bucket it created and `terraform init -migrate-state`.
