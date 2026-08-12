from __future__ import annotations

import pytest

from danmu_autopilot.config import Settings


def _set_minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISAKA_BASE_URL", "http://misaka:7768")
    monkeypatch.setenv("MISAKA_CONTROL_KEY", "secret-control-key")
    monkeypatch.setenv("MISAKA_PLAYER_TOKEN", "secret-player-token")
    monkeypatch.setenv("DANMU_API_BASE_URL", "http://danmu-api:9321")
    monkeypatch.setenv("DANMU_API_TOKEN", "secret-backup-token")
    monkeypatch.setenv("STATE_DIR", "/data")


def test_settings_accept_internal_engine_urls_and_hide_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_minimal_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.misaka_base_url.host == "misaka"
    assert settings.misaka_base_url.port == 7768
    assert settings.danmu_api_base_url.host == "danmu-api"
    assert "secret-control-key" not in repr(settings)
    assert "secret-backup-token" not in str(settings)


def test_settings_reject_public_control_api(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_minimal_env(monkeypatch)
    monkeypatch.setenv("MISAKA_BASE_URL", "https://public.example.invalid")

    with pytest.raises(ValueError, match="internal|private|localhost"):
        Settings(_env_file=None)


def test_settings_require_independent_engine_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_minimal_env(monkeypatch)
    monkeypatch.delenv("DANMU_API_TOKEN")

    with pytest.raises(ValueError, match="DANMU_API_TOKEN|danmu_api_token"):
        Settings(_env_file=None)


def test_settings_cap_scratch_space(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_minimal_env(monkeypatch)
    monkeypatch.setenv("SCRATCH_MAX_BYTES", str(501 * 1024 * 1024))

    with pytest.raises(ValueError, match="SCRATCH_MAX_BYTES"):
        Settings(_env_file=None)


def test_settings_default_scratch_space_is_500_mib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_minimal_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.scratch_max_bytes == 500 * 1024 * 1024
