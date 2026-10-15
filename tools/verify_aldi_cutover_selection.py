"""Read-only host proof for the API selected by installed ALDI collector syntax.

The operator must separately verify the installed systemd unit and deployment
receipt. This program never invokes a collector or changes Docker state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import resource
import subprocess


PROJECT = "hermes-deals"
SERVICE = "api"
CHECKOUT = Path("/home/andris/hermes-deals")
IMAGE = "ghcr.io/rozkalnsandris/hermes-deals"
RAW_SOURCE = "/var/lib/rozkalns-simple-deployer/hermes-deals/data/raw"
CONFIG_SOURCE = "/var/lib/rozkalns-simple-deployer/hermes-deals/config"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class Stop(Exception):
    """Fail closed without printing Docker metadata or private config."""


def require(value: object) -> None:
    if not value:
        raise Stop()


def _run(args: list[str]) -> str:
    # Match the unit's HOME and working directory. Do not inherit Compose
    # overrides from the invoking shell or relay Docker's stderr to stdout.
    env = {"HOME": "/home/andris", "PATH": "/usr/local/bin:/usr/bin:/bin"}
    try:
        result = subprocess.run(args, cwd=CHECKOUT, env=env, check=True,
                                capture_output=True, text=True, timeout=10)
        require(len(result.stdout) <= 256 * 1024)
        return result.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise Stop() from exc


def verify(expected_container: str, expected_digest: str, *, run=_run) -> None:
    require(bool(HEX64.fullmatch(expected_container)))
    require(bool(HEX64.fullmatch(expected_digest)))

    selected = run(["docker", "compose", "ps", "-q", SERVICE]).splitlines()
    require(selected == [expected_container])
    all_api = run(["docker", "ps", "-a", "--no-trunc", "--filter",
                   f"label=com.docker.compose.project={PROJECT}", "--filter",
                   f"label=com.docker.compose.service={SERVICE}",
                   "--format", "{{.ID}}"]).splitlines()
    require(all_api == [expected_container])

    container = _parse_one(run(["docker", "inspect", expected_container]))
    require(container.get("Id") == expected_container)
    labels = container.get("Config", {}).get("Labels", {})
    require(labels.get("com.docker.compose.project") == PROJECT)
    require(labels.get("com.docker.compose.service") == SERVICE)
    state = container.get("State", {})
    require(state.get("Running") is True)
    require(state.get("Health", {}).get("Status") == "healthy")
    require(container.get("Config", {}).get("Image", "").startswith(IMAGE + ":")
            or container.get("Config", {}).get("Image", "").startswith(IMAGE + "@"))

    mounts = container.get("Mounts")
    require(isinstance(mounts, list))
    raw = [mount for mount in mounts if mount.get("Destination") == "/data/raw"]
    config = [mount for mount in mounts if mount.get("Destination") == "/app/config"]
    require(len(raw) == len(config) == 1)
    require(raw[0].get("Type") == "bind" and raw[0].get("Source") == RAW_SOURCE
            and raw[0].get("RW") is True)
    require(config[0].get("Type") == "bind"
            and config[0].get("Source") == CONFIG_SOURCE
            and config[0].get("RW") is False)

    pinned = _parse_one(run(["docker", "image", "inspect",
                             f"{IMAGE}@sha256:{expected_digest}"]))
    require(container.get("Image") == pinned.get("Id"))
    require(f"{IMAGE}@sha256:{expected_digest}" in pinned.get("RepoDigests", []))


def _parse_one(raw: str) -> dict:
    try:
        rows = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise Stop() from exc
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict))
    return rows[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only ALDI API selection proof")
    parser.add_argument("--expected-container", required=True)
    parser.add_argument("--expected-digest", required=True,
                        help="SHA-256 digest from the reviewed deployment receipt")
    args = parser.parse_args(argv)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        verify(args.expected_container, args.expected_digest)
    except Exception:
        print("ALDI_CUTOVER_SELECTION=STOP")
        return 2
    print("ALDI_CUTOVER_SELECTION=PASS")
    print("DOCKER_WRITES=false")
    print("COLLECTOR_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
