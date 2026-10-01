"""Healing capture: DLP redaction of samples and traceback fallback."""

from __future__ import annotations

import pytest

from engine.healing import _infer_shape, _redact_text, redact_sample, safe_traceback


def test_redact_text_masks_pii():
    out = _redact_text("mail bob@example.com or call 415-555-1234, card 4111 1111 1111 1111")
    assert "bob@example.com" not in out
    assert "415-555-1234" not in out
    assert "4111 1111 1111 1111" not in out
    assert "[EMAIL_MASKED]" in out


def test_redact_sample_walks_nested_values():
    sample = {
        "customer": {"email": "a@b.co", "phones": ["+1 (212) 555-0100"]},
        "amount": 12.5,
        "ok": True,
        "note": None,
    }
    out = redact_sample(sample)
    assert out["customer"]["email"] == "[EMAIL_MASKED]"
    assert "555-0100" not in out["customer"]["phones"][0]
    assert out["amount"] == 12.5 and out["ok"] is True and out["note"] is None
    assert redact_sample(None) is None


def test_infer_shape_unaffected_by_redaction():
    sample = {"email": "a@b.co", "n": 1}
    assert _infer_shape(redact_sample(sample)) == _infer_shape(sample)


def test_safe_traceback_formats_exception():
    try:
        raise KeyError("missing")
    except KeyError as e:
        tb = safe_traceback(e)
    assert tb and "KeyError" in tb
    assert safe_traceback(None) is None


@pytest.mark.asyncio
async def test_capture_failure_without_db_url_is_noop():
    from engine.healing import capture_failure

    rid = await capture_failure(
        db_url="",
        tenant_id="t",
        pipeline_id="p",
        execution_id="e",
        node_id="n",
        node_kind="tool",
        node_target="calc",
        error_class="X",
        error_message="m",
        error_traceback=None,
        upstream_inputs=None,
        observed_sample=None,
    )
    assert rid is None
