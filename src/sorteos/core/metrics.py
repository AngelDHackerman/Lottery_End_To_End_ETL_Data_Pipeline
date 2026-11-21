"""CloudWatch metrics from a Lambda, as one log line (UY-045).

A Lambda's stdout goes to CloudWatch Logs, and Logs turns any line in the Embedded Metric
Format into metric datapoints: no ``PutMetricData`` call, no IAM permission, no dependency.
The line has to be the JSON alone, so the caller ``print()``s it: the Lambda runtime's logging
handler would put a level and a request id in front, and Logs would no longer read it.

A number published every night is what lets an alarm tell 0 from "nothing ran" (master's
PR-025): the alarms in ``terraform/uy/alarms.tf`` treat missing data as not breaching, and
leave the night that never ran to the dead-man alarm.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping

NAMESPACE = "Loteria/UY"
DIMENSION = "Environment"
# Set by Terraform on each Lambda. Without it (a test, a local run) nothing is published.
ENVIRONMENT_VARIABLE = "METRICS_ENVIRONMENT"


def emf_line(counts: Mapping[str, int], environment: str, timestamp_ms: int) -> str:
    """The Embedded Metric Format line for ``counts``, each a Count under one dimension."""
    if not counts:
        raise ValueError("no metric to publish")
    for name, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a count: {value!r}")
    if set(counts) & {"_aws", DIMENSION}:
        raise ValueError(f"reserved metric name in {sorted(counts)}")
    return json.dumps(
        {
            "_aws": {
                "Timestamp": timestamp_ms,
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": [[DIMENSION]],
                        "Metrics": [{"Name": name, "Unit": "Count"} for name in counts],
                    }
                ],
            },
            DIMENSION: environment,
            **counts,
        }
    )


def publish(counts: Mapping[str, int]) -> bool:
    """Print the line for ``counts`` if the function was told its environment; say if it did."""
    environment = os.environ.get(ENVIRONMENT_VARIABLE)
    if not environment:
        return False
    print(emf_line(counts, environment, int(time.time() * 1000)))
    return True
