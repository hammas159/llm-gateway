"""Smoke tests for the Streamlit demo (the `ui` dependency group)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parent.parent / "ui" / "app.py")


def _app() -> AppTest:
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=15)
    assert not at.exception
    return at


def _check_sample(at: AppTest, sample: str) -> AppTest:
    next(sb for sb in at.selectbox if sb.label == "Sample").set_value(sample).run(timeout=15)
    next(b for b in at.button if b.label == "Check guardrails").click().run(timeout=15)
    return at


def test_app_loads_without_exceptions():
    _app()


def test_a_request_is_routed_and_served():
    at = _app()
    next(b for b in at.button if "Send through the gateway" in b.label).click().run(timeout=15)
    assert not at.exception
    assert any("Served by" in s.value for s in at.success)


def test_aws_key_is_redacted_before_the_request_leaves():
    at = _check_sample(_app(), "AWS key in the prompt")
    assert not at.exception
    assert any("REDACTED_AWS_KEY" in c.value for c in at.code)


def test_cnic_is_redacted_and_labelled_as_a_cnic():
    at = _check_sample(_app(), "Pakistani CNIC (PII)")
    assert not at.exception
    assert any("REDACTED_CNIC" in c.value for c in at.code)


def test_prompt_injection_is_refused_outright():
    at = _check_sample(_app(), "Prompt injection")
    assert not at.exception
    assert any("Refused" in e.value for e in at.error)


def test_clean_prompt_passes_untouched():
    at = _check_sample(_app(), "Clean prompt")
    assert not at.exception
    assert any("Allowed" in s.value for s in at.success)


def test_spend_tab_reflects_a_served_request():
    at = _app()
    next(b for b in at.button if "Send through the gateway" in b.label).click().run(timeout=15)
    assert not at.exception
    assert any("Requests" in m.label for m in at.metric)
