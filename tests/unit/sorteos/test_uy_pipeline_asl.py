"""The UY nightly state machine (UY-043.3.1): its definition, rendered without AWS, and the two
scripts around it (scripts/uy_sfn_validate.py, scripts/uy_sfn_run.py). Since UY-043.3.2 also
the schedule that starts it and the cutover in the Makefile.

The definition is checked against AWS too, by `make uy-tf-plan`. These tests pin what AWS cannot
know: the owner's retry decisions (UY-043.3 3a) and that dry_run reaches both Lambdas.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).parents[3]
TEMPLATE = REPO / "terraform" / "uy" / "pipeline.asl.json.tftpl"
TIMEOUT = 3600  # pipeline.tf, local.execution_timeout_seconds
FETCH_ARN = "arn:aws:lambda:us-east-1:111111111111:function:lottery-uy-fetch-test"
SILVER_ARN = "arn:aws:lambda:us-east-1:111111111111:function:lottery-uy-silver-test"
DQ_JOB = "lottery-uy-silver-dq-test"
DQ_TIMEOUT = 600  # variables.tf, dq_timeout_minutes: 10 at most
LAMBDA_SERVICE_ERRORS = {
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
}


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def asl() -> dict:
    text = TEMPLATE.read_text("utf-8")
    values = {
        "fetch_function_arn": FETCH_ARN,
        "silver_function_arn": SILVER_ARN,
        "dq_job_name": DQ_JOB,
        "execution_timeout_seconds": str(TIMEOUT),
    }
    # templatefile() would fail on an unknown variable; so does this.
    assert set(re.findall(r"\$\{(\w+)\}", text)) == set(values)
    for name, value in values.items():
        text = text.replace("${" + name + "}", value)
    assert "%{" not in text  # no template directives: the file is plain JSON plus variables
    return json.loads(text)


def test_every_transition_lands_on_a_state_and_every_state_is_reachable(asl):
    states = asl["States"]
    seen, todo = set(), [asl["StartAt"]]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        assert name in states, name
        seen.add(name)
        state = states[name]
        todo += [state["Next"]] if "Next" in state else []
        todo += [c["Next"] for c in state.get("Choices", [])]
        todo += [state["Default"]] if "Default" in state else []
    assert seen == set(states)


def test_the_input_defaults_to_a_real_run_and_only_a_boolean_gets_through(asl):
    states = asl["States"]
    assert asl["StartAt"] == "Defaults"
    merge = states["Defaults"]["Parameters"]["input.$"]
    assert merge.startswith("States.JsonMerge(States.StringToJson(")
    defaults = json.loads(re.search(r"StringToJson\('(.*)'\)", merge).group(1))
    assert defaults == {"dry_run": False}
    assert merge.endswith(", $, false)")  # the input wins over the defaults
    assert states["Defaults"]["OutputPath"] == "$.input"

    check = states["CheckInput"]
    assert check["Choices"] == [{"Variable": "$.dry_run", "IsBoolean": True, "Next": "Fetch"}]
    assert states[check["Default"]]["Type"] == "Fail"


def test_fetch_then_silver_with_dry_run_reaching_both(asl):
    states = asl["States"]
    fetch, silver = states["Fetch"], states["Silver"]
    assert fetch["Next"] == "Silver" and silver["Next"] == "ValidateSilver"

    assert fetch["Parameters"]["FunctionName"] == FETCH_ARN
    assert fetch["Parameters"]["Payload"] == {"mode": "incremental", "dry_run.$": "$.dry_run"}
    assert silver["Parameters"]["FunctionName"] == SILVER_ARN
    assert silver["Parameters"]["Payload"] == {
        "pending": True,
        "finalize": True,
        "dry_run.$": "$.dry_run",
    }
    # Each report is kept beside the input, so Silver still reads $.dry_run.
    assert fetch["ResultPath"] == "$.fetch" and silver["ResultPath"] == "$.silver"


def test_fetch_never_retries_its_own_errors(asl):
    """A retry of fetch would ask the site for up to 400 pages again (owner, UY-043.3 3a)."""
    retry = asl["States"]["Fetch"]["Retry"]
    errors = {e for r in retry for e in r["ErrorEquals"]}
    assert errors == LAMBDA_SERVICE_ERRORS
    assert "Catch" not in asl["States"]["Fetch"]  # a failed fetch fails the run: the alarm


def test_silver_retries_anything_once_after_the_service_errors(asl):
    retry = asl["States"]["Silver"]["Retry"]
    assert set(retry[0]["ErrorEquals"]) == LAMBDA_SERVICE_ERRORS
    assert retry[-1]["ErrorEquals"] == ["States.ALL"]  # AWS requires States.ALL last
    assert retry[-1]["MaxAttempts"] == 1


def test_the_gate_is_the_last_step_and_its_failure_is_the_executions(asl):
    """Owner, UY-043.4 3a: a failed gate ends the run FAILED, and the alarm mails it."""
    gate = asl["States"]["ValidateSilver"]
    assert gate["End"] is True
    # .sync waits for the job; without it the state would succeed as soon as the run started.
    assert gate["Resource"] == "arn:aws:states:::glue:startJobRun.sync"
    assert gate["Parameters"] == {
        "JobName": DQ_JOB,
        "Arguments": {"--RUN_ID.$": "$$.Execution.Name"},
    }
    # Nothing swallows the failure, and the same silver is never validated twice.
    assert "Catch" not in gate and "Retry" not in gate
    # The run id is what finds the verdict in /aws-glue/jobs/output; the times are D30's.
    assert gate["ResultPath"] == "$.dq"
    assert set(gate["ResultSelector"]) == {
        "job_run_id.$",
        "state.$",
        "started_on.$",
        "completed_on.$",
        "billed_seconds.$",
    }


def test_the_gate_job_reads_from_wheels_in_s3_and_never_from_pypi():
    job = _block(
        (REPO / "terraform" / "uy" / "dq.tf").read_text("utf-8"),
        'resource "aws_glue_job" "silver_dq"',
    )
    assert re.search(r'glue_version\s*=\s*"5\.0"', job)
    assert re.search(r'"--python-modules-installer-option"\s*=\s*"--no-index"', job)
    assert re.search(r'"--additional-python-modules"\s*=\s*"s3://\$\{aws_s3_object\.dq_zip', job)
    assert "great-expectations==" not in job  # master's ~21 minutes of PyPI at every start


def test_the_execution_timeout_covers_the_worst_case(asl):
    # fetch 900 s, silver 900 s twice with 60 s between, then the DQ job's own timeout.
    assert asl["TimeoutSeconds"] == TIMEOUT
    assert TIMEOUT > 900 + 900 + 60 + 900 + DQ_TIMEOUT
    variables = (REPO / "terraform" / "uy" / "variables.tf").read_text("utf-8")
    assert "var.dq_timeout_minutes <= 10" in _block(variables, 'variable "dq_timeout_minutes"')


# --- scripts/uy_sfn_validate.py -----------------------------------------------------------


def _change(address, actions, definition="{}", unknown=False):
    return {
        "address": address,
        "type": "aws_sfn_state_machine",
        "change": {
            "actions": actions,
            "after": None if actions == ["delete"] else {"definition": definition},
            "after_unknown": {"definition": True} if unknown else {},
        },
    }


def test_validate_reads_every_kept_state_machine_and_skips_deletes():
    validate = _script("uy_sfn_validate")
    plan = {
        "resource_changes": [
            _change("aws_sfn_state_machine.pipeline", ["update"], '{"a": 1}'),
            _change("aws_sfn_state_machine.same", ["no-op"], '{"b": 2}'),
            _change("aws_sfn_state_machine.gone", ["delete"]),
            {"address": "aws_iam_role.x", "type": "aws_iam_role", "change": {"actions": []}},
        ]
    }
    assert validate.definitions(plan) == [
        ("aws_sfn_state_machine.pipeline", '{"a": 1}'),
        ("aws_sfn_state_machine.same", '{"b": 2}'),
    ]


def test_validate_refuses_a_definition_known_only_after_apply():
    validate = _script("uy_sfn_validate")
    plan = {"resource_changes": [_change("aws_sfn_state_machine.pipeline", ["create"], None, True)]}
    with pytest.raises(ValueError, match="only known after apply"):
        validate.definitions(plan)


# --- scripts/uy_sfn_run.py ----------------------------------------------------------------


def test_run_names_and_inputs():
    run = _script("uy_sfn_run")
    now = datetime(2026, 11, 9, 2, 30, 5, tzinfo=UTC)
    assert run.execution_name(True, now) == "manual-dry-20261109T023005Z"
    assert run.execution_name(False, now) == "manual-real-20261109T023005Z"
    assert json.loads(run.execution_input(True)) == {"dry_run": True}
    assert json.loads(run.execution_input(False)) == {"dry_run": False}


def test_run_reports_the_output_or_the_failure():
    run = _script("uy_sfn_run")
    ok = run.report({"status": "SUCCEEDED", "output": '{"fetch": {"report": {"requests": 33}}}'})
    assert json.loads(ok) == {"fetch": {"report": {"requests": 33}}}
    failed = run.report({"status": "FAILED", "error": "BadInput", "cause": "dry_run must be"})
    assert failed.startswith("FAILED: BadInput") and "dry_run must be" in failed
    assert run.report({"status": "TIMED_OUT"}).startswith("TIMED_OUT: ?")


# --- The schedule and the cutover (UY-043.3.2) -------------------------------------------------
#
# Terraform cannot be rendered here without AWS, so the owner's choices are pinned on the source:
# D27's hour and zone, and no retries (UY-043.3 3a).


def _block(text: str, header: str) -> str:
    start = text.index(header)
    return text[start : text.index("\n}\n", start)]


def test_the_schedule_is_2330_montevideo_without_retries():
    schedule = _block(
        (REPO / "terraform" / "uy" / "pipeline.tf").read_text("utf-8"),
        'resource "aws_scheduler_schedule" "nightly"',
    )
    assert 'schedule_expression          = "cron(30 23 * * ? *)"' in schedule
    assert 'schedule_expression_timezone = "America/Montevideo"' in schedule
    assert "maximum_retry_attempts       = 0" in schedule
    assert "arn      = aws_sfn_state_machine.pipeline.arn" in schedule
    assert "input = jsonencode({ dry_run = false })" in schedule


def _make(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {"UY_LOCAL", "UY_DRY_RUN"}}
    return subprocess.run(
        ["make", "--no-print-directory", *args], cwd=REPO, env=env, capture_output=True, text=True
    )


def test_the_local_incremental_refuses_without_uy_local():
    # Run for real, not -n: the guard is the recipe's first line, so nothing reaches Python.
    refused = _make("uy-incremental")
    assert refused.returncode != 0
    assert "UY_LOCAL=1" in refused.stdout and "frozen" in refused.stdout
    allowed = _make("-n", "uy-incremental", "UY_LOCAL=1")
    assert "python -m sorteos.uy.incremental" in allowed.stdout


def test_the_manual_run_is_real_unless_dry_run_is_asked():
    assert "uy_sfn_run.py --real" in _make("-n", "uy-sfn-run").stdout
    assert "uy_sfn_run.py --dry-run" in _make("-n", "uy-sfn-run", "UY_DRY_RUN=1").stdout
