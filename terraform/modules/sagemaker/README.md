# Module: `sagemaker`

SageMaker Studio domain for EDA notebooks. **Opt-in** — the root caller wraps it in
`count = var.enable_sagemaker ? 1 : 0` (default `false`), so a fresh cloner deploys no
SageMaker (it's the most expensive idle piece of the stack).

**Status:** migrated in **PR-015** from `terraform-lottery/Prod/sagemaker.tf`. The
deployed prod domain is imported only if the owner enables the module; see
`docs/runbooks/PR-015-sagemaker-and-legacy-teardown.md` for both paths (manage vs.
leave unmanaged).

## Enabling

```bash
cd terraform
terraform apply -var=enable_sagemaker=true -target=module.sagemaker
# or: make sagemaker
```

Set `enable_sagemaker = true` in your gitignored `terraform.tfvars` to make it stick for
plain `terraform plan/apply` runs.

## Known limitation

The `lottery-analyst` user profile stays **unmanaged**: `aws_sagemaker_user_profile`
import fails with `arn: invalid prefix` on aws provider v5.x (provider read-back bug,
known since PR-004). The commented resource in `main.tf` documents it.

## Inputs / outputs

- Inputs: `vpc_id`, `subnet_ids`, `security_group_id` (from `module.network`),
  `sagemaker_execution_role_arn` (from `module.iam`), `environment`.
- Outputs: `domain_id`, `domain_arn`.
