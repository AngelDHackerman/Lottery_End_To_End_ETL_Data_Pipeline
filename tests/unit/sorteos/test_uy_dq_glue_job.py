"""The UY silver gate as a Glue job (UY-043.4): sorteos.uy.dq.glue_job and scripts/uy_dq_run.py.

The suites themselves are tested in test_uy_dq.py. Here: the job's arguments, the copy of
uy/silver/ to disk, and the owner's decision that a failed gate is a failed job (3a).
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sorteos.core import dq as core
from sorteos.uy.dq import glue_job, runner

REPO = Path(__file__).parents[3]
BUCKET, PREFIX = "data-bucket", "uy/silver/"
ARGV = ["script.py", "--JOB_NAME", "x", "--SILVER_BUCKET", BUCKET, "--SILVER_PREFIX", PREFIX]


class FakeS3:
    """list_objects_v2 (two pages) and get_object over a dict of key -> bytes."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3's names
        assert Bucket == BUCKET
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        half = len(keys) // 2
        for page in (keys[:half], keys[half:]):
            yield {"Contents": [{"Key": k} for k in page]} if page else {}

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": type("Body", (), {"read": lambda _: self.objects[Key]})()}


def _report(*, ok: bool) -> core.Report:
    bad = core.Outcome("expect_column_values_to_be_unique", "draw_id", False, 2, ["a", "b"])
    good = core.Outcome("expect_column_values_to_not_be_null", "draw_id", True, 0)
    return core.Report([core.SuiteResult("uy_draws", 12999, [good] if ok else [good, bad])])


def test_arguments_are_found_by_name_among_glues_own():
    args = glue_job.parse_args([*ARGV, "--RUN_ID=manual-1", "--job-language", "python"])
    assert args == {"SILVER_BUCKET": BUCKET, "SILVER_PREFIX": PREFIX, "RUN_ID": "manual-1"}


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["script.py", "--SILVER_BUCKET", BUCKET], "SILVER_PREFIX"),
        (["script.py", "--SILVER_PREFIX", PREFIX], "SILVER_BUCKET"),
        # Without the slash "uy/silver" would also match a sibling prefix.
        (["script.py", "--SILVER_BUCKET", BUCKET, "--SILVER_PREFIX", "uy/silver"], "end with"),
    ],
)
def test_a_missing_or_open_ended_argument_stops_the_job(argv, message):
    with pytest.raises(SystemExit, match=message):
        glue_job.parse_args(argv)


def test_download_mirrors_the_prefix_and_keeps_empty_files(tmp_path):
    s3 = FakeS3(
        {
            "uy/silver/draws/country=uy/game=5_de_oro/year=2026/part-0.parquet": b"abc",
            "uy/silver/draw_gaps/country=uy/part-0.parquet": b"",  # a partition that vanished
            "uy/silver/prizes/": b"",  # a console "folder" marker
            "uy/silver_old/draws/part-0.parquet": b"never",
            "uy/raw/x.html": b"never",
        }
    )
    assert glue_job.download(s3, BUCKET, PREFIX, tmp_path) == (2, 3)
    found = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert found == {
        "draws/country=uy/game=5_de_oro/year=2026/part-0.parquet",
        "draw_gaps/country=uy/part-0.parquet",
    }


def test_a_green_gate_runs_the_local_runner_on_the_copy(monkeypatch, capsys):
    seen = {}

    def run(root: Path) -> core.Report:
        seen["files"] = sorted(p.name for p in root.rglob("*.parquet"))
        return _report(ok=True)

    monkeypatch.setattr(runner, "run", run)
    out = glue_job.main(
        [*ARGV, "--RUN_ID", "exec-1"], s3=FakeS3({"uy/silver/draws/a.parquet": b"x"})
    )

    assert seen["files"] == ["a.parquet"]  # the same runner.run as `make uy-dq` (owner, 2a)
    assert out["success"] is True and out["files"] == 1
    assert out["suites"] == {"uy_draws": {"expectations": 1, "rows": 12999}}
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"{glue_job.START_MARK} 20") and lines[0].endswith("run_id=exec-1")
    assert "uy_draws: ok (1 expectations, 12999 rows)" in lines
    assert lines[-1].startswith(f"{glue_job.RESULT_MARK}: PASS seconds=")
    assert set(out["seconds"]) == {"imports", "download", "validate", "total"}


def test_a_failed_expectation_fails_the_job_and_names_itself(monkeypatch, capsys):
    monkeypatch.setattr(runner, "run", lambda root: _report(ok=False))
    with pytest.raises(glue_job.SilverDataQualityFailed) as failure:
        glue_job.main(ARGV, s3=FakeS3({"uy/silver/draws/a.parquet": b"x"}))
    # What Step Functions shows as the cause (owner, 3a).
    assert "uy_draws: expect_column_values_to_be_unique on draw_id: 2 unexpected" in str(
        failure.value
    )
    out = capsys.readouterr().out
    assert f"{glue_job.RESULT_MARK}: FAIL" in out and "run_id=-" in out


def test_nothing_to_validate_is_a_wiring_error_not_a_verdict(monkeypatch):
    with pytest.raises(glue_job.SilverNotFound, match="nothing under s3://data-bucket/uy/silver/"):
        glue_job.main(ARGV, s3=FakeS3({}))

    def run(root):
        raise core.TableEmpty("draws: no Parquet files")

    monkeypatch.setattr(runner, "run", run)
    with pytest.raises(glue_job.SilverNotFound, match="draws: no Parquet files"):
        glue_job.main(ARGV, s3=FakeS3({"uy/silver/prizes/a.parquet": b"x"}))


def test_a_report_with_no_suites_is_not_green(monkeypatch):
    monkeypatch.setattr(runner, "run", lambda root: core.Report([]))
    with pytest.raises(glue_job.SilverDataQualityFailed, match="no suite ran"):
        glue_job.main(ARGV, s3=FakeS3({"uy/silver/draws/a.parquet": b"x"}))


def test_the_script_glue_runs_only_calls_main():
    source = (REPO / "scripts" / "uy_dq_glue_main.py").read_text("utf-8")
    code = [ln for ln in source.split('"""')[2].splitlines() if ln.strip()]
    assert code == ["from sorteos.uy.dq.glue_job import main", "main()"]


# --- scripts/uy_dq_run.py ------------------------------------------------------------------


def _run_script():
    spec = importlib.util.spec_from_file_location("uy_dq_run", REPO / "scripts" / "uy_dq_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_startup_is_the_first_line_minus_started_on():
    run = _run_script()
    assert run.START_MARK == glue_job.START_MARK
    started = datetime(2026, 11, 10, 20, 0, 0, tzinfo=UTC)
    job_run = {
        "StartedOn": started,
        "CompletedOn": datetime(2026, 11, 10, 20, 1, 50, tzinfo=UTC),
        "ExecutionTime": 95,
    }
    lines = ["pip noise", "UY DQ START 2026-11-10T20:01:20Z run_id=-", "uy_draws: ok"]
    assert run.timings(job_run, lines) == {
        "wall_seconds": 110,
        "startup_seconds": 80,
        "billed_seconds": 95,
    }
    # A run that died before the script: no mark, no start-up, still a wall clock.
    assert run.timings(job_run, ["pip noise"])["startup_seconds"] is None
    assert run.timings({"StartedOn": started}, [])["wall_seconds"] is None
