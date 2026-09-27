"""Tests for the quarantine store (PR-044.2, fault E).

Quarantine only earns its place if it is there when something goes wrong — so most of these
are about failure: the writer must not raise, the vocabulary must stay closed, and the
schema must not drift away from the Terraform table that makes it queryable.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from loteria.common import quarantine
from loteria.common.lineage import PARSER_VERSION
from loteria.parser.parser import (
    REJECT_ORPHAN_VENDOR_LINE,
    REJECT_SECTION_HEADER,
    REJECT_UNRECOGNISED,
)

REPO = Path(__file__).parents[2]
BUCKET = "lottery-partitioned-storage-prod"


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def rejects(*reasons):
    return [{"reason": r, "line": f"line-{i}", "position": i} for i, r in enumerate(reasons, 1)]


class TestStructureIsNotStored:
    """The decision the PR-044.1 measurement forced.

    6.50% of every real body is millar headings. Storing them would write ~9,500 rows of
    structure per draw — 1.1M across the archive — and make `SELECT reason, count(*)`
    useless. They are counted; they are not kept.
    """

    def test_section_headers_are_dropped(self):
        rows = quarantine.build_rows(
            rejects(REJECT_SECTION_HEADER, REJECT_SECTION_HEADER),
            source_key="raw/year=2026/sorteo=415/f.txt",
            run_id="exec-1",
        )

        assert rows == []

    def test_the_reasons_worth_keeping_are_kept(self):
        rows = quarantine.build_rows(
            rejects(REJECT_SECTION_HEADER, REJECT_UNRECOGNISED, REJECT_ORPHAN_VENDOR_LINE),
            source_key="raw/year=2026/sorteo=415/f.txt",
            run_id="exec-1",
        )

        assert [r["reason"] for r in rows] == [REJECT_UNRECOGNISED, REJECT_ORPHAN_VENDOR_LINE]

    def test_a_body_of_pure_structure_writes_no_object(self, s3):
        """The normal case. Archive baseline is ONE storable reject in 145,680 lines, so
        almost every run must produce no object at all — a quarantine prefix full of empty
        files per draw would be its own kind of noise."""
        written = quarantine.write(
            BUCKET,
            quarantine.build_rows(
                rejects(REJECT_SECTION_HEADER), source_key="raw/f.txt", run_id="exec-1"
            ),
            dataset="premios",
            year="2026",
            numero_sorteo=415,
            run_id="exec-1",
        )

        assert written == 0
        assert s3.list_objects_v2(Bucket=BUCKET, Prefix="quarantine/").get("Contents") is None


class TestTheWriterNeverFailsTheRun:
    """The constraint stated out loud in the roadmap, asserted.

    A quarantine that can raise turns one odd footer line into a missed week of ingestion —
    the exact outcome fault E exists to prevent, reached from the opposite direction. The
    swallowed exception is the feature, not an oversight.
    """

    def test_a_refused_put_is_logged_and_swallowed(self, s3, caplog):
        class Refusing:
            def put_object(self, **kwargs):
                raise RuntimeError("AccessDenied: the PR-002 bucket Deny")

        rows = quarantine.build_rows(
            rejects(REJECT_UNRECOGNISED), source_key="raw/f.txt", run_id="exec-1"
        )

        with caplog.at_level("ERROR"):
            written = quarantine.write(
                BUCKET,
                rows,
                dataset="premios",
                year="2026",
                numero_sorteo=415,
                run_id="exec-1",
                s3_client=Refusing(),
            )

        assert written == 0
        assert quarantine.QUARANTINE_WRITE_FAILED in caplog.text

    def test_the_failure_marker_matches_the_pattern_terraform_greps_for(self):
        """Same contract as PR-042.2's retention alarm: reword the log line and nothing
        fails, the alarm just stops firing forever."""
        alarms = (REPO / "terraform/modules/observability/alarms.tf").read_text()

        assert f'"\\"{quarantine.QUARANTINE_WRITE_FAILED}\\""' in alarms
        assert f'"\\"{quarantine.QUARANTINED_UNRECOGNISED}\\""' in alarms


class TestWhatLandsInS3:
    def test_a_stored_reject_round_trips_as_parquet(self, s3):
        rows = quarantine.build_rows(
            rejects(REJECT_UNRECOGNISED),
            source_key="raw/year=2026/sorteo=415/f.txt",
            run_id="exec-1",
        )

        assert (
            quarantine.write(
                BUCKET, rows, dataset="premios", year="2026", numero_sorteo=415, run_id="exec-1"
            )
            == 1
        )

        (obj,) = s3.list_objects_v2(Bucket=BUCKET, Prefix="quarantine/")["Contents"]
        body = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
        df = pd.read_parquet(io.BytesIO(body))

        assert list(df.columns) == list(quarantine.QUARANTINE_COLUMNS)
        assert df.loc[0, "reason"] == REJECT_UNRECOGNISED
        assert df.loc[0, "run_id"] == "exec-1"
        assert int(df.loc[0, "parser_version"]) == PARSER_VERSION

    def test_the_key_is_hive_partitioned(self):
        key = quarantine.quarantine_key("premios", "2026", 415, "exec-1")

        assert key == "quarantine/dataset=premios/year=2026/sorteo=415/exec-1.parquet"

    def test_a_file_that_failed_before_its_header_partitions_as_unknown(self):
        """The partition that says "we could not even tell which draw this was" is precisely
        the one worth keeping, so the partition keys are strings, not ints."""
        key = quarantine.quarantine_key("sorteos", "unknown", "unknown", None)

        assert key == "quarantine/dataset=sorteos/year=unknown/sorteo=unknown/unknown.parquet"

    def test_two_runs_of_one_sorteo_do_not_overwrite_each_other(self):
        """The earlier record is the evidence of what the parser used to do. A reprocessing
        must not erase it."""
        a = quarantine.quarantine_key("premios", "2026", 415, "exec-1")
        b = quarantine.quarantine_key("premios", "2026", 415, "exec-2")

        assert a != b


class TestTheSchemaMatchesTheTerraformTable:
    """The table is DEFINED, not crawled (PR-045.1 established the crawlers cannot evolve a
    schema). That makes the Terraform column list and `QUARANTINE_COLUMNS` two halves of one
    contract, with nothing but this test holding them together.
    """

    def test_every_code_column_is_declared_in_terraform(self):
        catalog = (REPO / "terraform/modules/catalog/main.tf").read_text()
        block = catalog[catalog.index('resource "aws_glue_catalog_table" "quarantine"') :]
        declared = re.findall(r'columns\s*\{\s*name\s*=\s*"([a-z_]+)"', block)

        assert declared == list(quarantine.QUARANTINE_COLUMNS)

    def test_partition_keys_are_not_also_columns(self):
        """Glue rejects a table whose columns and partition keys overlap, and it would also
        defeat the partition pruning that is the only reason to lay the prefix out this way."""
        catalog = (REPO / "terraform/modules/catalog/main.tf").read_text()
        block = catalog[catalog.index('resource "aws_glue_catalog_table" "quarantine"') :]
        partitions = re.findall(r'partition_keys\s*\{\s*name\s*=\s*"([a-z_]+)"', block)

        assert partitions == ["dataset", "year", "sorteo"]
        assert not set(partitions) & set(quarantine.QUARANTINE_COLUMNS)


class TestTheVocabularyIsClosed:
    def test_file_level_codes_are_stable(self):
        assert quarantine.REJECT_MALFORMED_HEADER == "malformed_header"
        assert quarantine.REJECT_UNEXPECTED_KEY == "unexpected_key"

    def test_there_is_no_replay_path(self):
        """Quarantine is NOT a dead-letter queue — the roadmap says resist, and this is what
        resisting looks like when someone greps for it later. A human reads it and decides
        whether the parser or the source changed; an automatic retry would turn "the site
        changed" into "the site changed, silently, every week"."""
        source = (REPO / "src/loteria/common/quarantine.py").read_text()

        assert not re.search(r"\bdef\s+(replay|reprocess|retry)", source)
