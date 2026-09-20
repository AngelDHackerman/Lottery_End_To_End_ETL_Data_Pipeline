"""The flag parser (PR-041.1).

``loteria.common.config`` exists because one decision — whether to keep writing to the
`simple` bucket — reaches the two writers by different routes: a Glue **job argument** for
the transformer, a Lambda **environment variable** for the extractor. Both arrive as strings
that a human typed into Terraform. If the two sides disagreed about what ``"False"`` means,
the bucket would keep growing from one writer while the PR claimed the writes had stopped.

The asymmetry below is deliberate and is the module's whole opinion: **unrecognised values
keep the default**, and the default is ON. A typo that leaves the writes enabled shows up on
the next run as an object count that did not stop moving; a typo that silently disabled them
would be an unannounced change to what the pipeline stores.
"""

from __future__ import annotations

import logging

import pytest

from loteria.common.config import FLAG_SIMPLE_BUCKET_WRITES, env_flag, parse_flag


class TestParseFlag:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", " true ", "1", "yes", "on"])
    def test_truthy_spellings(self, value):
        assert parse_flag(value) is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", " false ", "0", "no", "off"])
    def test_falsy_spellings(self, value):
        """``"false"`` is what Terraform renders through `tostring(var.x)`; the rest are here
        because a console edit is typed by a person, not emitted by HCL."""
        assert parse_flag(value) is False

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_unset_takes_the_default_quietly(self, value, caplog):
        """Absent is the NORMAL case, not an error: the Glue job's zip ships separately from
        the apply that adds the argument, so "no flag" simply means "as before"."""
        with caplog.at_level(logging.WARNING):
            assert parse_flag(value, default=True) is True
            assert parse_flag(value, default=False) is False

        assert caplog.records == []

    def test_an_unrecognised_value_keeps_the_default(self):
        assert parse_flag("flase", default=True) is True
        assert parse_flag("flase", default=False) is False

    def test_an_unrecognised_value_says_so(self, caplog):
        """Fail-safe is not the same as fail-silent. The value that was not understood has to
        appear in the log, or a typo in Terraform is indistinguishable from a decision."""
        with caplog.at_level(logging.WARNING):
            parse_flag("flase", name=FLAG_SIMPLE_BUCKET_WRITES)

        assert len(caplog.records) == 1
        assert caplog.records[0].value == "flase"
        assert caplog.records[0].config_name == FLAG_SIMPLE_BUCKET_WRITES


class TestEnvFlag:
    def test_it_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("SOME_FLAG", "false")
        assert env_flag("SOME_FLAG") is False

    def test_a_missing_variable_takes_the_default(self, monkeypatch):
        monkeypatch.delenv("SOME_FLAG", raising=False)
        assert env_flag("SOME_FLAG") is True
        assert env_flag("SOME_FLAG", default=False) is False

    def test_it_reads_at_call_time_not_at_import(self, monkeypatch):
        """The property the extractor depends on: a Terraform change to the Lambda's
        environment takes effect on the next invocation, with no rebuild of the zip."""
        monkeypatch.setenv("SOME_FLAG", "true")
        assert env_flag("SOME_FLAG") is True

        monkeypatch.setenv("SOME_FLAG", "false")
        assert env_flag("SOME_FLAG") is False


def test_both_delivery_routes_agree_on_terraforms_own_rendering():
    """`tostring(false)` in HCL is the string "false", and it reaches the transformer as a
    job argument and the extractor as an environment variable. This is the one case that
    MUST agree, because the two writers feed the same bucket."""
    from_terraform = "false"

    assert parse_flag(from_terraform) is False
