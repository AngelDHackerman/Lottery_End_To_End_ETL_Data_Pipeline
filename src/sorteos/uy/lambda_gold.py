"""The UY gold Lambda (UY-044.3; D33): the six tables of sql/uy/gold/, built and swapped whole.

    {"run_id": "<execution name>"}        build, check, swap, retire
    {"run_id": "...", "dry_run": true}    refused: a dry run writes nothing (owner, UY-044.3 4a)

The state machine calls it after ValidateSilver, so gold is never built on a silver the GX gate
rejected, and skips it in a dry run. Everything it does is ``sorteos.core.gold.Builder``; this
module only reads the environment and the SQL that travels in the zip.

Its zip holds this file, ``core/gold.py``, the package ``__init__``s and ``sql/uy/gold/``
(terraform/uy/gold.tf): no dependency but boto3, which the runtime brings.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sorteos.core import gold

KEEP_PREVIOUS = 1  # the live generation plus one to roll back to (owner, UY-044.3 3a)
# In the zip the SQL sits beside the package: <root>/sorteos/uy/lambda_gold.py and
# <root>/sql/uy/gold/. In the repo it is two levels further up; GOLD_SQL_DIR overrides both.
_ZIP_SQL = Path(__file__).resolve().parents[2] / "sql" / "uy" / "gold"
_REPO_SQL = Path(__file__).resolve().parents[3] / "sql" / "uy" / "gold"


def sql_dir() -> Path:
    if os.environ.get("GOLD_SQL_DIR"):
        return Path(os.environ["GOLD_SQL_DIR"])
    return _ZIP_SQL if _ZIP_SQL.is_dir() else _REPO_SQL


def target() -> gold.Target:
    return gold.Target(
        database=os.environ["GOLD_DATABASE"],
        workgroup=os.environ["GOLD_WORKGROUP"],
        bucket=os.environ["GOLD_BUCKET"],
        prefix=os.environ["GOLD_PREFIX"],
    )


def handler(event: dict, context: object = None, *, clients: dict | None = None) -> dict:
    event = event or {}
    if event.get("dry_run") is not False and "dry_run" in event:
        raise gold.GoldError("gold has no dry run: it would write. The state machine skips it.")
    run_id = event.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise gold.GoldError('the event needs {"run_id": "<execution name>"}')
    if clients is None:
        import boto3

        clients = {name: boto3.client(name) for name in ("athena", "glue", "s3")}
    builder = gold.Builder(target=target(), **clients)
    report = builder.run(gold.load_queries(sql_dir()), run_id=run_id, keep_previous=KEEP_PREVIOUS)
    # One line in the function's log group. No logging setup: touching the root logger here
    # would change it for whoever imports this module (the tests found that).
    print(json.dumps({"gold": report}, default=str))
    return report
