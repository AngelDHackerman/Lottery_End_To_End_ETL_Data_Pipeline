# PR-019 — Lambda layer for the extractor's dependencies

Splits the extractor's single fat deployment zip along the deps/code seam:
`requests` + `beautifulsoup4` move into a Lambda **layer**, and the function zip carries
`src/loteria/` and nothing else.

No application code changes. This is packaging only — but the function's code and its
imports now arrive from two different places, so a partial deploy breaks the weekly run.
Read "Deploy order" before applying.

## What changed

| Was | Now |
|---|---|
| `scripts/build_lambda_package.sh` (deps + code in one zip) | `scripts/build_lambda_layer.sh` + `scripts/build_lambda_function.sh` |
| `lambda_package.zip` ≈ 900 KB | `lambda_package.zip` ≈ **16 KB** + `lambda_layer.zip` ≈ **888 KB** |
| deps resolved from `/var/task` | deps resolved from `/opt/python/lib/python3.12/site-packages` |

New Terraform in `modules/etl-lambda`: `aws_s3_object.lambda_layer` and
`aws_lambda_layer_version.loteria_deps`, attached via `layers = [...]` on the function.
New root var `lambda_layer_zip_path` (default `lambda_layer.zip`, gitignored).

Acceptance (roadmap): function zip < 5 MB → **16 KB**. ✅

## Terminology, because it bites

There is **one layer**, not two. The code is *not* a layer — it is the function's own
deployment package. Two artifacts; only one of them is a "layer".

## The layout is load-bearing

The layer zip must be `python/lib/python3.12/site-packages/<deps>`. Lambda mounts layers
at `/opt`, and **only** `/opt/python` and `/opt/python/lib/python3.12/site-packages` are
on the runtime's `sys.path`. A wrong nesting mounts cleanly and then fails every import
at runtime — there is no deploy-time error to catch it.

Verified locally by mirroring the runtime's path:

```bash
python3 -c "
import sys, zipfile
zipfile.ZipFile('terraform/lambda_layer.zip').extractall('/tmp/opt')
zipfile.ZipFile('terraform/lambda_package.zip').extractall('/tmp/task')
sys.path[:0] = ['/tmp/opt/python/lib/python3.12/site-packages', '/tmp/task']
import requests, bs4; print(requests.__version__, bs4.__version__)
"
```

## Build host: why Linux x86_64

**Build the layer on Linux x86_64. WSL2 counts — it is a real Linux kernel.** Native
Windows and macOS do not, and the distinction is easy to miss ("it works on my Windows
machine" usually means "it works in my WSL shell").

`pip` resolves wheels by tags matching the **machine running pip**, not the deploy
target. `--target` changes *where* packages land, not *which* wheels are downloaded.
What this layer actually pulls:

| Package | Wheel tag |
|---|---|
| requests, beautifulsoup4, certifi, idna, urllib3, soupsieve, typing_extensions | `py3-none-any` |
| charset_normalizer | `cp312-cp312-manylinux_2_17_x86_64` |

Seven of eight are pure Python and build identically from any host. **`charset_normalizer`
is the only compiled dependency**, shipping three `.so` files (~490 KB, mypyc-compiled).

### The failure is silent, not loud

A macOS-built layer does **not** break. Verified by renaming the `.so` files to darwin
names and importing on Linux: `charset_normalizer` imports fine, falls back to `cd.py`,
and encoding detection still works. The wheel ships the pure-python sources *alongside*
the compiled ones, so Python's import machinery skips the non-matching binary.

So the real cost of building on the wrong host is **degradation, not failure**:
`charset_normalizer` runs interpreted instead of mypyc-compiled, and the layer carries
dead `.so` weight. Nothing errors, nothing logs. That is arguably worse than a crash —
an `ImportError` you would catch on the first invoke.

`compatible_architectures = ["x86_64"]` therefore documents intent and keeps this layer
off arm64 functions; it is not what prevents a breakage.

### If the build ever leaves a Linux x86_64 host

Force target-platform resolution rather than host resolution:

```bash
pip install -r requirements/extractor.txt --target "$SITE_PACKAGES" \
  --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12
```

Not done here — see "Out of scope".

`boto3` stays out of both artifacts — the Python 3.12 runtime ships it. That is why
`requirements/extractor.txt` lists only `beautifulsoup4` and `requests`.

## Layer versions are immutable

You don't update a layer; you publish a new version. Changing
`requirements/extractor.txt` → new `source_code_hash` → `aws_lambda_layer_version`
publishes `:N+1` and the function is repointed at the new ARN.

`lifecycle { create_before_destroy = true }` is deliberate: Terraform's default
destroy-then-create order would delete the version the live function still references
before publishing the replacement. With CBD, the new version is published and the
function repointed first.

Consequence: **old versions are deleted** once nothing references them (no
`skip_destroy`). That's intentional — the S3 object is versioned and the zip is
reproducible from a pinned requirements file, so there's nothing to recover.

## Deploy order

Both artifact paths are read at plan time by `filemd5` / `filebase64sha256`. If the files
are missing, **the plan fails** — it does not silently skip them. So build first.

```bash
# 1. Build everything. Terraform manages both Lambda artifacts; it does NOT manage the
#    Glue zip (unchanged by this PR, but `make build` rebuilds it too).
make build
#    -> terraform/lambda_layer.zip     (python/lib/python3.12/site-packages/)
#    -> terraform/lambda_package.zip   (loteria/ only)
#    -> dist/lottery_transformer.zip   (unchanged)

# 2. Apply.
cd terraform && terraform plan
terraform apply
```

Expected plan: **2 to add, 2 to change, 0 to destroy**

- add `aws_s3_object.lambda_layer` (new object)
- add `aws_lambda_layer_version.loteria_deps` (version 1)
- change `aws_s3_object.lambda_package` (etag — the zip got much smaller)
- change `aws_lambda_function.extractor_lambda` (`source_code_hash` + `layers`)

The function's code and layer attachment update in the same
`UpdateFunctionCode`/`UpdateFunctionConfiguration` pair. If the apply dies *between*
them, the function has thin code and no layer → `Runtime.ImportModuleError` on the next
invoke. Re-running `terraform apply` fixes it. The weekly EventBridge trigger fires
Monday, so apply with room to verify.

## Smoke test (owner runs this — roadmap step 5)

```bash
# Confirm the layer is attached and note the version
aws lambda get-function-configuration --function-name lottery-extractor-prod \
  --query '{Layers:Layers[].Arn,CodeSize:CodeSize}' --output table

# Force a cold start (a config update discards warm sandboxes), then invoke
aws lambda invoke --function-name lottery-extractor-prod \
  --cli-binary-format raw-in-base64-out \
  --payload '{"lottery_number": null}' /tmp/out.json && cat /tmp/out.json

# Cold-start duration — roadmap asks for < 3s. Read Init Duration from the REPORT line.
aws logs filter-log-events --log-group-name /aws/lambda/lottery-extractor-prod \
  --start-time $(( ($(date +%s) - 600) * 1000 )) \
  --filter-pattern '"Init Duration"' \
  --query 'events[-1].message' --output text
```

Record the `Init Duration` in the PR description. **Layers are not inherently faster** —
they're fetched and mounted at init like package contents. The bar here is "no
regression", not "an improvement".

Failure modes:

- `Runtime.ImportModuleError: No module named 'requests'` → the layer isn't attached, or
  its internal layout is wrong. Check `get-function-configuration` for the layer ARN,
  then `unzip -l terraform/lambda_layer.zip | head` for the `python/lib/...` prefix.
- `Unable to import module 'loteria/extractor/lambda_handler'` → the code zip is stale.
  Re-run `make build` and re-apply.

## Rollback

Revert the commit and re-run `make build` + `terraform apply`. The old script rebuilds
the fat zip, the function drops `layers`, and the layer version is deleted. Nothing is
destroyed but the layer itself; no data is touched.

## Out of scope

- The function zip still ships `loteria/transformer/` and `loteria/parser/`, which only
  the Glue job uses. Harmless at 16 KB, and pruning it would re-couple the build to the
  package layout PR-016 just settled.
- `requirements/extractor.txt` is installed with a plain `pip install --target`, same as
  the old script, so the build is host-sensitive (see "Build host" above). Pinning
  `--platform manylinux2014_x86_64 --only-binary=:all:` would make it reproducible from
  any machine, but it is a behavior change and this PR is a packaging move. It stops
  mattering once the build runs in CI on Linux x86_64 (**PR-034**) — that is the right
  moment to decide, since CI makes the host constant instead of "whatever the owner is
  sitting at".
