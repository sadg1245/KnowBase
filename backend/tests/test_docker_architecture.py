"""Integration contracts for the production and development Docker stacks."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@unittest.skipUnless(shutil.which("docker"), "Docker CLI is required")
class DockerArchitectureTests(unittest.TestCase):
    def test_backend_dockerfile_exposes_development_and_production_targets(self):
        result = _docker(
            "buildx",
            "build",
            "--call=targets",
            "-f",
            "backend/Dockerfile",
            "backend",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        target_names = {
            line.split()[0]
            for line in result.stdout.splitlines()
            if line and not line.startswith(("#", "TARGET", "("))
        }
        self.assertIn("dev", target_names)
        self.assertIn("production", target_names)

    def test_compose_keeps_backend_and_worker_on_one_production_image(self):
        result = _docker("compose", "config", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        services = config["services"]
        self.assertEqual(services["backend"]["image"], services["worker"]["image"])
        self.assertEqual(services["backend"]["build"]["target"], "production")
        self.assertEqual(services["worker"]["build"]["target"], "production")

        for service_name in ("backend", "worker"):
            volume_targets = {
                volume["target"] for volume in services[service_name]["volumes"]
            }
            self.assertIn("/opt/huggingface", volume_targets)

    def test_development_compose_uses_dev_images_and_container_dns_proxy(self):
        result = _docker(
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
            "config",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services["backend"]["build"]["target"], "dev")
        self.assertEqual(services["worker"]["build"]["target"], "dev")
        self.assertEqual(services["frontend"]["build"]["target"], "dev")
        self.assertEqual(
            services["frontend"]["environment"]["VITE_API_PROXY_TARGET"],
            "http://backend:8000",
        )


if __name__ == "__main__":
    unittest.main()
