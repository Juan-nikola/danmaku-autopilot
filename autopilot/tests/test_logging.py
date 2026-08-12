from __future__ import annotations

from danmu_autopilot.logging import redact


def test_redact_nested_secrets() -> None:
    value = {
        "cookie": "SESSDATA=abc",
        "nested": {"Authorization": "Bearer abc", "normal": "ok"},
        "url": "/token-abc/api/v2/match",
        "items": [{"password": "pw", "text": "hello"}],
    }

    assert redact(value) == {
        "cookie": "[REDACTED]",
        "nested": {"Authorization": "[REDACTED]", "normal": "ok"},
        "url": "/[TOKEN]/api/v2/match",
        "items": [{"password": "[REDACTED]", "text": "hello"}],
    }


def test_redact_preserves_input_and_handles_sequences() -> None:
    value = {"values": ("ok", {"token": "abc"})}

    result = redact(value)

    assert value["values"][1]["token"] == "abc"
    assert result == {"values": ["ok", {"token": "[REDACTED]"}]}

