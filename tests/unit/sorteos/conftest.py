"""Fixtures shared by the sorteos tests: the DynamoDB manifest table on moto (UY-042.2)."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

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
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        create_manifest_table(client)
        yield client
