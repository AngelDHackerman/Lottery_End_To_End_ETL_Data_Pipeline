# PR-041 — Retiring `lottery-data-simple-prod`

**Fault A of the 2026-09-14 audit.** Every draw was written twice: once to the partitioned
bucket's Silver layer, once flat to `lottery-data-simple-prod`. Two copies of the same data
with one declared owner. This runbook covers the whole retirement, but its operational half
— the part with irreversible commands in it — is **PR-041.3, owner-run, and not to be
executed before the date in §4.**

| Sub-PR | What it did | State |
|---|---|---|
| **041.1** (#53) | Gated all **three** writes behind `enable_simple_bucket_writes`, flipped it to `false`. Deleted nothing. | **Applied 2026-09-20 22:31 UTC.** Bucket frozen at **347 objects**. |
| **041.2** (this PR) | Removed the write code, the job/env wiring, the IAM write grants, the `"simple"` key in `get_secrets()`, and **repointed the SageMaker read grant**. Deleted nothing. | Code merged; see §5 for the owner's manual follow-up. |
| **041.3** | Empties and disposes of the bucket. **Irreversible.** | **Not before 2026-10-20.** See §4. |

---

## 1. Inventory it one last time, and commit the snapshot

"What was in there" has to stay answerable after the bytes are gone.

```bash
aws s3 ls s3://lottery-data-simple-prod/ --recursive > /tmp/simple-final-listing.txt
wc -l /tmp/simple-final-listing.txt                     # must be 347 — see §4

aws s3api list-object-versions --bucket lottery-data-simple-prod \
  --query '{Versions:length(Versions),DeleteMarkers:length(DeleteMarkers),Bytes:sum(Versions[].Size)}'
```

`scripts/00_inventory_and_protect.sh` already produces the canonical snapshot format; the
041.1 evidence lives in `docs/inventory/2026-09-20-simple-bucket-readers.md` and should be
read before anything here is run. Commit the final listing beside it.

**Nothing in the bucket is unique.** Verified at 041.1: all 115 raw `.txt` and 116 Parquet
draws have a counterpart under the partitioned bucket's `raw/` and `silver/`
(`set(simple) - set(partitioned)` is empty for both). Deleting the bucket cannot lose data —
only a convenience copy.

## 2. PR-002's Deny policy blocks the delete, on purpose

The bucket carries `scripts/policies/lottery-data-simple-prod_protect.json`:

```json
"Effect": "Deny", "Principal": "*",
"Action": ["s3:DeleteBucket", "s3:DeleteObject*"],
"Condition": { "StringNotEquals": { "aws:PrincipalArn": "arn:aws:iam::913524903233:root" } }
```

Every principal **except the account root** is denied. `angel-adming` is not root, so the
CLI will fail with `AccessDenied` and the failure will look like a permissions bug rather
than the safety net it is — this is exactly what the gold-purge work ran into. Either
remove the policy for the duration or run as root. **Put it back if the bucket is kept.**

```bash
aws s3api get-bucket-policy --bucket lottery-data-simple-prod \
  --query Policy --output text > /tmp/simple-policy-backup.json   # back it up FIRST
aws s3api delete-bucket-policy --bucket lottery-data-simple-prod
```

## 3. Versioning is on, so deleting objects only writes delete markers

`aws s3 rm --recursive` leaves every byte — and every byte's bill — behind, under
noncurrent versions. A real purge deletes **versions *and* delete markers**.

Lift the pattern from `loteria.gold.purge_and_load._empty_prefix` rather than reinventing
it: it paginates `list_object_versions`, batches `delete_objects` with explicit
`VersionId`s, handles both `Versions` and `DeleteMarkers`, and raises rather than
under-deleting silently. The alternative, and the cheaper one to get right, is a lifecycle
rule that expires current and noncurrent versions and lets S3 do it:

```bash
aws s3api put-bucket-lifecycle-configuration --bucket lottery-data-simple-prod \
  --lifecycle-configuration '{"Rules":[{"ID":"expire-everything","Status":"Enabled",
    "Filter":{},"Expiration":{"Days":1},
    "NoncurrentVersionExpiration":{"NoncurrentDays":1},
    "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'
```

Note the lifecycle route still needs the Deny from §2 out of the way, and it is not
instant — S3 runs expiration asynchronously, typically within 24–48 h.

## 4. The abort condition — check this before deleting a byte

**Grace period: 2026-09-20 → at least 2026-10-20.** Four weekly runs fall inside it
(09-24, 10-01, 10-08, 10-15), which is the point: it is four chances for a reader nobody
knew about to notice its data has gone stale and say so. The 041.1 evidence is blind to
exactly that reader — **CloudTrail data events are not enabled for this bucket and S3
request metrics are not configured** — so the window buys with time what the evidence
cannot prove.

```bash
aws s3 ls s3://lottery-data-simple-prod/ --recursive | wc -l    # must still be 347
```

**If the count moved, stop.** A writer nobody knew about is still running; find it before
deleting anything.

## 5. `prevent_destroy` and the cheapest safe ending

`terraform/modules/storage/main.tf` sets `prevent_destroy = true` on
`aws_s3_bucket.lottery_simple`. Terraform will refuse to destroy it until that lifecycle
block is deliberately removed — another guard to take off on purpose, not by accident.

**Consider this first: keep the empty bucket.** Drop the lifecycle from §3 to expire
everything, leave a single `README` object explaining why it is empty and which PR emptied
it, and keep `prevent_destroy`. Storage cost goes to approximately zero without ever
running a destructive command against prod, and the bucket name stays taken — S3 names are
global, and a freed name is a name someone else can claim.

## 6. Manual follow-ups PR-041.2 could not make

### The Secrets Manager payload — **owner edit, still open**

`lottery_secret_prod_2` still contains `s3_bucket_simple_data_storage_prod_arn`.
**Terraform does not own the secret's contents** (only the secret is referenced, by name),
so no `apply` will remove it. `get_secrets()` stopped reading the key in PR-041.2 and
`tests/unit/test_common.py` pins that an extra key is ignored, so the edit is safe to make
at any time — and safe to forget, which is why it is written down here.

```bash
aws secretsmanager get-secret-value --secret-id lottery_secret_prod_2 \
  --query SecretString --output text | jq 'del(.s3_bucket_simple_data_storage_prod_arn)' \
  > /tmp/secret.json
# review /tmp/secret.json, then:
aws secretsmanager put-secret-value --secret-id lottery_secret_prod_2 \
  --secret-string file:///tmp/secret.json
shred -u /tmp/secret.json        # it holds the scrape.do token
```

Do this **after** 041.2 is deployed, not before: code that still read the key would fail at
import, which in the extractor's case means the weekly run dies before it starts.

### The SageMaker read grant — **done in 041.2, verify after the apply**

`lottery-sagemaker-s3-read-policy-prod`'s entire content used to be `s3:GetObject` +
`s3:ListBucket` on this bucket and nothing else. So the only consumer this architecture
ever contemplated was a notebook, pointed at exactly the bucket being retired — which is
also the honest answer to why the flat copies existed. 041.2 repoints it at `silver/` and
`gold/` in the partitioned bucket, where the data a notebook would want actually lives.

```bash
aws iam get-policy-version --policy-arn \
  arn:aws:iam::913524903233:policy/lottery-sagemaker-s3-read-policy-prod \
  --version-id "$(aws iam get-policy --policy-arn \
    arn:aws:iam::913524903233:policy/lottery-sagemaker-s3-read-policy-prod \
    --query Policy.DefaultVersionId --output text)" --query Document
```

Nothing is running today (two domains `InService`, zero apps, zero notebook instances), so
this cannot break a workload — but a role whose sole data permission points at a deleted
bucket is a trap for whoever next opens a notebook. Reading Silver/Gold through **Athena**
additionally needs a Lake Formation grant; this policy covers the direct S3 read.
