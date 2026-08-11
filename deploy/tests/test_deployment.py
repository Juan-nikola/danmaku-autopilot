"""Static deployment-policy checks.

These tests intentionally use only the Python standard library so they can run on
a fresh VPS before the application image or its Python dependencies are built.
"""

from __future__ import annotations

import re
import stat
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ComposePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    def test_only_gateway_and_misaka_loopback_ports_are_published(self) -> None:
        ports = re.findall(r'^\s*-\s*"?([^"\n]+)"?\s*$', self.compose, re.MULTILINE)
        published = [line.strip() for line in ports if ":" in line and "127.0.0.1:" in line]
        self.assertEqual(
            published,
            [
                "127.0.0.1:${MISAKA_BIND_PORT:-7768}:7768",
                "127.0.0.1:${AUTOPILOT_BIND_PORT:-7770}:8080",
            ],
        )

    def test_backup_engine_has_no_host_port(self) -> None:
        service = re.search(r"(?ms)^  danmu-api:\n(.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)", self.compose)
        self.assertIsNotNone(service)
        self.assertNotRegex(service.group(1), r"(?m)^\s+ports:\s*$")
        self.assertIn("danmu-api-cache", service.group(1))

    def test_no_container_mounts_docker_socket(self) -> None:
        self.assertNotIn("/var/run/docker.sock", self.compose)

    def test_misaka_has_only_the_capability_needed_by_its_entrypoint(self) -> None:
        service = re.search(r"(?ms)^  misaka:\n(.*?)(?=^  [a-zA-Z0-9_-]+:|\\Z)", self.compose)
        self.assertIsNotNone(service)
        self.assertIn("cap_drop:", service.group(1))
        for capability in ("CHOWN", "SETGID", "SETUID"):
            self.assertRegex(service.group(1), rf"(?m)^\s+- {capability}$")


class CaddyPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.caddy = (ROOT / "config" / "Caddyfile.native.example").read_text(encoding="utf-8")

    def test_player_host_never_exposes_control_api(self) -> None:
        player = re.search(r'(?ms)^\{\$DANMU_API_HOST\} \{(.*?)(?=^\S|\Z)', self.caddy)
        self.assertIsNotNone(player)
        self.assertIn("/api/control*", player.group(1))
        self.assertRegex(player.group(1), r"respond\s+.*404")
        self.assertIn("reverse_proxy 127.0.0.1:7770", player.group(1))

    def test_admin_host_has_basic_auth_and_misaka_proxy(self) -> None:
        admin = re.search(r'(?ms)^\{\$DANMU_ADMIN_HOST\} \{(.*?)(?=^\S|\Z)', self.caddy)
        self.assertIsNotNone(admin)
        self.assertIn("basic_auth", admin.group(1))
        self.assertIn("reverse_proxy 127.0.0.1:7768", admin.group(1))


class ScriptSafetyTests(unittest.TestCase):
    def test_required_scripts_are_executable_and_strict(self) -> None:
        for name in (
            "lib.sh",
            "preflight.sh",
            "bootstrap.sh",
            "backup.sh",
            "restore.sh",
            "update.sh",
            "rollback.sh",
            "healthcheck.sh",
            "resolve-images.sh",
        ):
            path = ROOT / "scripts" / name
            mode = path.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, name)
            text = path.read_text(encoding="utf-8")
            self.assertIn("set -Eeuo pipefail", text, name)

    def test_restore_requires_explicit_apply(self) -> None:
        text = (ROOT / "scripts" / "restore.sh").read_text(encoding="utf-8")
        self.assertIn("--apply", text)
        self.assertRegex(text.lower(), r"refus(?:e|ing).*restore")

    def test_scripts_do_not_delete_broad_paths(self) -> None:
        scripts = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "scripts").glob("*.sh"))
        for forbidden in ("rm -rf /", "rm -rf $HOME", "rm -rf ~"):
            self.assertNotIn(forbidden, scripts)


if __name__ == "__main__":
    unittest.main()
