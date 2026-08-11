"""Validated settings loaded from the deployment environment.

Only internal service URLs belong in this settings object.  Public traffic is
terminated by Caddy and reaches the application separately; accidentally
pointing a control client at a public host would otherwise leak credentials.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

from pydantic import AnyHttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SERVICE_NAME = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
_MAX_SCRATCH_BYTES = 500 * 1024 * 1024


def _is_internal_host(host: str | None) -> bool:
    """Return whether *host* is a local/container/private-network target."""

    if not host:
        return False
    normalized = host.rstrip(".").lower()
    if normalized in {"localhost", "host.docker.internal"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_private or ipaddress.ip_address(
            normalized
        ).is_loopback
    except ValueError:
        # Docker Compose service names are intentionally short, single-label
        # names (e.g. ``misaka``).  A dotted hostname is treated as public;
        # this prevents a typo from sending control credentials over the WAN.
        return "." not in normalized and bool(_SERVICE_NAME.fullmatch(normalized))


class Settings(BaseSettings):
    """Runtime configuration with secret-safe representation and validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        hide_input_in_errors=True,
        validate_default=True,
    )

    misaka_base_url: AnyHttpUrl = "http://misaka:7768"
    misaka_control_key: SecretStr
    danmu_api_base_url: AnyHttpUrl = "http://danmu-api:9321"
    danmu_api_token: SecretStr
    state_dir: Path = Path("/data")
    scratch_max_bytes: int = 500 * 1024 * 1024

    # These limits keep accidental large uploads from consuming the VPS while
    # leaving enough room for normal XML and a bounded analysis sample.
    max_request_bytes: int = 16 * 1024 * 1024
    max_response_bytes: int = 64 * 1024 * 1024
    max_comments: int = 500_000

    @field_validator("misaka_base_url", "danmu_api_base_url")
    @classmethod
    def _validate_internal_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme not in {"http", "https"}:
            raise ValueError("engine URL must use http or https")
        if not _is_internal_host(value.host):
            raise ValueError("engine URL must point to an internal/private host")
        return value

    @field_validator("misaka_control_key", "danmu_api_token")
    @classmethod
    def _validate_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("engine credential must not be empty")
        return value

    @field_validator("scratch_max_bytes")
    @classmethod
    def _validate_scratch_limit(cls, value: int) -> int:
        if value <= 0 or value > _MAX_SCRATCH_BYTES:
            raise ValueError("SCRATCH_MAX_BYTES must be between 1 and 524288000")
        return value

    @field_validator("max_request_bytes", "max_response_bytes", "max_comments")
    @classmethod
    def _validate_positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("resource limits must be positive")
        return value

    @model_validator(mode="after")
    def _validate_distinct_credentials(self) -> Settings:
        if self.misaka_control_key.get_secret_value() == self.danmu_api_token.get_secret_value():
            raise ValueError("MISAKA_CONTROL_KEY and DANMU_API_TOKEN must be independent")
        return self

    def __repr_args__(self) -> list[tuple[str, Any]]:
        """Keep settings repr safe even if a future secret type changes."""

        return [
            ("misaka_base_url", str(self.misaka_base_url)),
            ("misaka_control_key", "[REDACTED]"),
            ("danmu_api_base_url", str(self.danmu_api_base_url)),
            ("danmu_api_token", "[REDACTED]"),
            ("state_dir", self.state_dir),
            ("scratch_max_bytes", self.scratch_max_bytes),
            ("max_request_bytes", self.max_request_bytes),
            ("max_response_bytes", self.max_response_bytes),
            ("max_comments", self.max_comments),
        ]

    def safe_dict(self) -> dict[str, Any]:
        """Return a loggable settings view without exposing credential values."""

        return {
            "misaka_base_url": str(self.misaka_base_url),
            "danmu_api_base_url": str(self.danmu_api_base_url),
            "state_dir": str(self.state_dir),
            "scratch_max_bytes": self.scratch_max_bytes,
            "max_request_bytes": self.max_request_bytes,
            "max_response_bytes": self.max_response_bytes,
            "max_comments": self.max_comments,
        }


__all__ = ["Settings"]
