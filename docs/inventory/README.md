# Inventory snapshots — Phase 0 safety belt

This folder holds **point-in-time snapshots** of the two production data buckets,
captured by [`scripts/00_inventory_and_protect.sh`](../../scripts/00_inventory_and_protect.sh)
(roadmap **PR-002**). Each file is named `<bucket>_<UTC_DATE>.txt` and records the
object count and total bytes in the bucket at that moment.

**Why they exist:** before any Terraform refactor or `terraform import` touches the
real buckets (`lottery-partitioned-storage-prod`, `lottery-data-simple-prod`), we
want provable evidence of what was in them — so that if anything ever looks off, we
can compare against a known-good baseline and demonstrate that no historical raw
lottery data was lost. They are committed to git on purpose: they are the audit
trail for the "never lose the data" guarantee in `DoD.md` §Phase 0.

The script also (a) enables **S3 Versioning** and (b) applies a **deny-delete bucket
policy** (every principal except the account root is denied `s3:DeleteBucket` /
`s3:DeleteObject*`). The applied policy JSON for each bucket lives under
[`scripts/policies/`](../../scripts/policies/). To lift the protection later, an
admin can replace the bucket policy (the policy does **not** deny `s3:PutBucketPolicy`).

Object Lock is intentionally **not** enabled here — it can only be turned on at
bucket creation and will be handled in a later, deliberate PR.
