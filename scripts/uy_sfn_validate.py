"""Validate the UY state machine's rendered definition against AWS before apply (UY-043.3.1).

    terraform -chdir=terraform/uy show -json tfplan | python scripts/uy_sfn_validate.py
    # or: make uy-tf-plan, which runs it on every plan

Terraform renders the definition (pipeline.asl.json.tftpl) but never checks it: a bad JSONPath
or a misspelt intrinsic only fails at CreateStateMachine/UpdateStateMachine, half-way through
an apply. Master learnt it the hard way (the crawler-polling PR), so this reads every
aws_sfn_state_machine in the plan and asks Step Functions' ValidateStateMachineDefinition, a
read-only call, for its diagnostics. Warnings are printed, errors fail.

Exit 0 when every definition is OK, 1 otherwise (or when none is in the plan).
"""

from __future__ import annotations

import json
import sys
from typing import Any

TYPE = "aws_sfn_state_machine"


def definitions(plan: dict[str, Any]) -> list[tuple[str, str]]:
    """``(address, definition)`` of every state machine the plan keeps or creates.

    Raises ``ValueError`` when a definition is only known after apply: there is nothing to
    validate then, and passing silently would defeat the check.
    """
    found = []
    for change in plan.get("resource_changes", []):
        if change.get("type") != TYPE or change["change"]["actions"] == ["delete"]:
            continue
        address = change["address"]
        after = change["change"].get("after") or {}
        if (change["change"].get("after_unknown") or {}).get("definition"):
            raise ValueError(f"{address}: the definition is only known after apply")
        found.append((address, after["definition"]))
    return found


def main() -> int:
    import boto3

    plan = json.load(sys.stdin)
    try:
        machines = definitions(plan)
    except ValueError as exc:
        print(f"Cannot validate: {exc}")
        return 1
    if not machines:
        print(f"No {TYPE} in the plan: nothing validated")
        return 1

    client = boto3.client("stepfunctions")
    ok = True
    for address, definition in machines:
        result = client.validate_state_machine_definition(
            definition=definition, type="STANDARD", severity="WARNING"
        )
        for diag in result.get("diagnostics", []):
            where = diag.get("location", "")
            print(f"{address}: {diag['severity']} {diag['code']} {where}: {diag['message']}")
        if result["result"] != "OK":
            ok = False
        print(f"{address}: {result['result']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
