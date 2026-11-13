"""Fixtures shared by the sorteos tests: the DynamoDB manifest table on moto (UY-042.2).

boto3 and moto are imported inside the fixture, never at the top: CI's `uy dq` job runs
test_uy_dq.py on Glue 5.0's Python with only the zip of wheels installed, and this file is
loaded for every test in the folder. A top-level import fails that job before any test runs.
"""

from __future__ import annotations

import pytest

MANIFEST_TABLE = "lottery-uy-manifest-test"


def create_manifest_table(client, name: str = MANIFEST_TABLE) -> None:
    """The table of terraform/uy/manifest.tf (P16): keys, the sparse index and its projection."""
    client.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "open", "AttributeType": "S"},
            {"AttributeName": "draw_date", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "open-keys",
                "KeySchema": [
                    {"AttributeName": "open", "KeyType": "HASH"},
                    {"AttributeName": "draw_date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["state"]},
            }
        ],
    )


@pytest.fixture
def dynamodb():
    """A moto DynamoDB client with an empty manifest table named MANIFEST_TABLE."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_manifest_table(client)
        yield client
