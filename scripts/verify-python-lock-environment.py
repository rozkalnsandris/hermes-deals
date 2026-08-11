#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from importlib import metadata
import pathlib
import re
import sys


REQUIREMENT_RE = re.compile(
    r"^([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([^\s\\]+)"
)
BOOTSTRAP_ALLOWLIST = {"pip", "setuptools"}


def canonicalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def expected_distributions(lock_path: pathlib.Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT_RE.match(line)
        if not match:
            continue
        name = canonicalize(match.group(1))
        version = match.group(2)
        previous = expected.setdefault(name, version)
        if previous != version:
            raise SystemExit(
                f"conflicting locked versions for {name}: {previous} vs {version}"
            )
    if not expected:
        raise SystemExit("lock contains no exact distributions")
    return expected


def installed_distributions() -> dict[str, str]:
    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            raise SystemExit("installed distribution is missing Name metadata")
        name = canonicalize(raw_name)
        version = distribution.version
        previous = installed.setdefault(name, version)
        if previous != version:
            raise SystemExit(
                f"duplicate installed distribution with conflicting versions: "
                f"{name} {previous} vs {version}"
            )
    return installed


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify-python-lock-environment.py <lock-file>")

    lock_path = pathlib.Path(sys.argv[1]).resolve()
    if not lock_path.is_file() or lock_path.is_symlink():
        raise SystemExit("lock file is missing or unsafe")

    expected = expected_distributions(lock_path)
    installed = installed_distributions()

    missing = sorted(set(expected) - set(installed))
    mismatched = sorted(
        name
        for name in set(expected) & set(installed)
        if expected[name] != installed[name]
    )
    extras = sorted(set(installed) - set(expected) - BOOTSTRAP_ALLOWLIST)

    if missing:
        raise SystemExit("missing locked distributions: " + ", ".join(missing))
    if mismatched:
        details = ", ".join(
            f"{name} expected={expected[name]} actual={installed[name]}"
            for name in mismatched
        )
        raise SystemExit("locked distribution version mismatch: " + details)
    if extras:
        raise SystemExit("unexpected installed distributions: " + ", ".join(extras))

    locked_inventory = "\n".join(
        f"{name}=={expected[name]}" for name in sorted(expected)
    ) + "\n"
    inventory_sha = hashlib.sha256(locked_inventory.encode("utf-8")).hexdigest()
    bootstrap = sorted(set(installed) & BOOTSTRAP_ALLOWLIST)

    print("PYTHON_LOCK_ENVIRONMENT=PASS")
    print(f"LOCKED_DISTRIBUTION_COUNT={len(expected)}")
    print(f"LOCKED_INVENTORY_SHA256={inventory_sha}")
    print("BOOTSTRAP_DISTRIBUTIONS=" + ",".join(bootstrap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
