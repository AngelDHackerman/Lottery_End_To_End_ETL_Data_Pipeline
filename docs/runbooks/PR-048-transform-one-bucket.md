# PR-048 — `transform()` reads one bucket and writes another

**Filed in PR-030 (2026-08) as a "latent smell, out of scope for a test PR".** Held until the
2026-10-08 run had verified 044/045, because it redeploys the transformer.

---

## 1. The defect

`transform(bucket_name, …)` listed raw files, downloaded them, checked idempotency and wrote
quarantine using its `bucket_name` argument. But it uploaded the two Silver Parquets to the
**module global** `partitioned_bucket`:

```python
upload_file_to_s3(sorteos_local_path, partitioned_bucket, partitioned_sorteos_key)
upload_file_to_s3(premios_local_path, partitioned_bucket, partitioned_premios_key)
```

Production agreed only by coincidence. `main()` used `global partitioned_bucket` to
overwrite the global with the `--PARTITIONED_BUCKET` job argument, then passed that same
value as `bucket_name`. Any other caller (a test, a backfill, a second environment) read
from one bucket and wrote Silver into another, with no error. The idempotency check then
listed the bucket that never received the output, so a second run rewrote every sorteo.

The test fixture had been working around it since PR-030. Its comment said: *"transform()
reads from its `bucket_name` argument but WRITES to these module globals. Set them
explicitly."*

## 2. The fix

- **`transform()` writes to `bucket_name`.** One bucket in both directions: raw, Silver and
  quarantine. The function no longer reads the global at all.
- **`main()` resolves the bucket into a local:** `bucket = args.get("PARTITIONED_BUCKET") or
  partitioned_bucket`, then passes it. No more `global` statement. The overwrite was the only
  thing keeping the read and the write in the same bucket, and it is gone along with the
  dependency on it.
- **The global stays, as `main()`'s fallback only.** Removing it would mean removing the
  transformer's import-time `get_secrets()` call and its Secrets Manager grant. That is a
  separate change with its own IAM diff.

**Production behaviour is identical.** The job's `--PARTITIONED_BUCKET` is
`lottery-partitioned-storage-prod` (read from the live job definition 2026-10-09). The
2026-10-08 run logged that value in `"Starting Glue Job"` and wrote 3138's Silver there.
Before and after, both the read and the write go to that bucket. What changes is that
nothing outside `main()` can split them.

## 3. Tests

`TestOneBucketBothWays` uses the two moto buckets the suite already creates, and points the
global at the **other** one on purpose:

| Test | Asserts |
|---|---|
| `test_silver_lands_in_the_bucket_passed_in_not_the_global` | Silver is under `bucket_name`; the global's bucket stays empty |
| `test_a_second_bucket_is_self_contained` | raw in bucket B → Silver in bucket B, the production-named bucket untouched (the backfill case) |
| `test_idempotency_reads_the_same_bucket_it_writes` | a second run over bucket B leaves the Parquet's ETag and LastModified unchanged |

**Mutation-checked:** with the two uploads put back on `partitioned_bucket`, all three
fail and the other 42 pass. The two entry-point tests that asserted `main()` *mutates* the
global were rewritten to assert the opposite: the argument reaches `transform()` and the
global stays what the secret said. An empty argument still falls back to the secret.

510 tests, ruff clean.

## 4. Apply

```bash
make deploy
```

Plan measured read-only on 2026-10-09 after `make build`: **`0 to add, 3 to change, 0 to
destroy`**, all of it the known churn:

- `aws_s3_object.lambda_package` + `aws_lambda_function.extractor_lambda`:
  `lambda_package.zip` ships all of `loteria/`, so a transformer change redeploys the
  extractor too.
- `aws_lambda_function.gold_purge`: the deferred `archive_file` phantom.

**The change that matters is not in the plan.** The Glue zip is uploaded by `make
upload-glue`, the third step of `make deploy`, and Terraform does not manage it. If only
`terraform apply` runs, the plan looks clean and the transformer stays on the old code. A
`destroy` on anything means STOP.

## 5. Verify

```bash
# 1. The deployed Glue zip carries the fix (the zip, not its timestamp, is the proof).
aws s3 cp --quiet s3://lambda-code-zip-prod/lottery_transformer.zip /tmp/t.zip
unzip -p /tmp/t.zip loteria/transformer/transformer.py \
  | grep -n "upload_file_to_s3(.*bucket_name\|bucket = args.get"
# expect: both uploads on bucket_name, and main()'s local `bucket`
```

Then the scheduled run of **Thursday 2026-10-15** (sorteo 3139, drawn Saturday 10-10)
verifies it end to end:

```bash
aws s3 ls --recursive s3://lottery-partitioned-storage-prod/silver/ | grep "sorteo=3139"
# expect: sorteos.parquet and premios.parquet, written during that run
```

The run is also PR-047's first scheduled run after its deploy. They touch different stages
(the state machine's extractor retry vs the transformer's write), so a failure would still
point at one of them.

## 6. Rollback

`git revert` + `make deploy`. Nothing stored changes: the bucket is the same before and
after.
