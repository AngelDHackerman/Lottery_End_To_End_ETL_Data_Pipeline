"""terraform/uy/alarms.tf against the code that feeds it (UY-045).

An alarm on a metric nobody publishes never fires and never complains: CloudWatch accepts any
name. So the names, the namespace and the dimension in the .tf are compared here with what the
Lambdas print, and the windows with CloudWatch's limits (master's PR-025).
"""

from __future__ import annotations

import re
from pathlib import Path

from sorteos.core import metrics
from sorteos.uy import lambda_fetch, lambda_silver

UY_STACK = Path(__file__).parents[3] / "terraform" / "uy"
ALARMS = (UY_STACK / "alarms.tf").read_text("utf-8")


def published() -> set[str]:
    silver = lambda_silver.gap_counts({"open": 0, "quarantine": 0})
    fetch = lambda_fetch.fetch_counts({"requests": 0, "by_state": {}})
    return set(silver) | set(fetch)


def test_every_alarmed_metric_is_one_a_lambda_publishes():
    alarmed = set(re.findall(r'^\s+metric\s+= "(\w+)"', ALARMS, re.M))
    assert alarmed == {"OpenDrawGaps", "SilverQuarantineRows", "FetchErrors"}
    assert alarmed <= published()


def test_the_namespace_and_the_dimension_are_the_codes():
    assert f'metrics_namespace   = "{metrics.NAMESPACE}"' in ALARMS
    assert f"metrics_dimensions  = {{ {metrics.DIMENSION} = var.environment }}" in ALARMS


def test_both_lambdas_are_told_their_environment():
    for name in ("fetch.tf", "silver.tf"):
        text = (UY_STACK / name).read_text("utf-8")
        assert f"{metrics.ENVIRONMENT_VARIABLE} = var.environment" in text, name


def test_the_nightly_alarms_keep_last_nights_datapoint_until_the_next_one():
    hours = int(re.search(r"nightly_alarm_hours = (\d+)", ALARMS).group(1))
    # More than a day, or the alarm drops to OK between two bad nights and mails again; an
    # hourly period may be evaluated over 7 days at most.
    assert 24 < hours <= 48
    block = ALARMS.split('resource "aws_cloudwatch_metric_alarm" "nightly_count"')[1]
    block = block.split("\nresource ")[0]
    assert re.search(r"period\s+= 3600\n", block)
    assert re.search(r"datapoints_to_alarm = 1\n", block)
    assert 'treat_missing_data  = "notBreaching"' in block  # no run is the dead-man's, not theirs
    assert "ok_actions" not in block


def test_the_dead_man_treats_no_data_as_no_success():
    block = ALARMS.split('resource "aws_cloudwatch_metric_alarm" "pipeline_no_success"')[1]
    assert 'metric_name = "ExecutionsSucceeded"' in block
    assert 'treat_missing_data  = "breaching"' in block  # no run publishes nothing, not a 0
    assert 'comparison_operator = "LessThanThreshold"' in block
    assert re.search(r"period\s+= 86400\n", block)
    variables = (UY_STACK / "variables.tf").read_text("utf-8")
    days = variables.split('variable "no_success_alarm_days"')[1]
    assert int(re.search(r"default\s+= (\d+)", days).group(1)) == 2  # owner, UY-045 3a
    assert "<= 7" in days  # CloudWatch evaluates 7 days at most


def test_no_alarm_description_is_longer_than_cloudwatch_takes():
    # 1,024 characters; the interpolations are short names, so the literal text is the bound.
    for description in re.findall(r'description = "([^"\n]+)"', ALARMS):
        assert len(description) + 250 < 1024, description[:60]
