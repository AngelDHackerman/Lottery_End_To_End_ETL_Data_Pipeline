"""The Embedded Metric Format line the UY Lambdas print (UY-045).

CloudWatch Logs reads a metric out of the line only if it has this exact shape, and says
nothing when it does not: a malformed line is just a log line, and the alarm sees no data.
So the shape is pinned here, field by field.
"""

from __future__ import annotations

import json

import pytest

from sorteos.core import metrics

NOW_MS = 1_794_364_277_460


def test_the_line_is_what_cloudwatch_logs_reads():
    line = metrics.emf_line({"OpenDrawGaps": 0, "SilverQuarantineRows": 2}, "prod", NOW_MS)
    assert "\n" not in line  # one event per line, or Logs splits it
    assert json.loads(line) == {
        "_aws": {
            "Timestamp": NOW_MS,
            "CloudWatchMetrics": [
                {
                    "Namespace": "Loteria/UY",
                    "Dimensions": [["Environment"]],
                    "Metrics": [
                        {"Name": "OpenDrawGaps", "Unit": "Count"},
                        {"Name": "SilverQuarantineRows", "Unit": "Count"},
                    ],
                }
            ],
        },
        "Environment": "prod",
        "OpenDrawGaps": 0,
        "SilverQuarantineRows": 2,
    }


@pytest.mark.parametrize(
    "counts, problem",
    [
        ({}, "no metric"),
        ({"OpenDrawGaps": -1}, "must be a count"),
        ({"OpenDrawGaps": 1.5}, "must be a count"),
        ({"OpenDrawGaps": True}, "must be a count"),
        ({"OpenDrawGaps": None}, "must be a count"),
        ({"Environment": 1}, "reserved"),
        ({"_aws": 1}, "reserved"),
    ],
)
def test_a_value_that_is_not_a_count_is_refused(counts, problem):
    with pytest.raises(ValueError, match=problem):
        metrics.emf_line(counts, "prod", NOW_MS)


def test_publish_prints_the_line_only_when_told_the_environment(monkeypatch, capsys):
    monkeypatch.delenv(metrics.ENVIRONMENT_VARIABLE, raising=False)
    assert metrics.publish({"FetchErrors": 0}) is False
    assert capsys.readouterr().out == ""

    monkeypatch.setenv(metrics.ENVIRONMENT_VARIABLE, "prod")
    assert metrics.publish({"FetchErrors": 0}) is True
    line = json.loads(capsys.readouterr().out)
    assert line["Environment"] == "prod" and line["FetchErrors"] == 0
    assert line["_aws"]["Timestamp"] > NOW_MS - 10**12  # milliseconds, not seconds
