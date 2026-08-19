from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit-public-workflow-safety.py"
SPEC = importlib.util.spec_from_file_location("public_workflow_safety", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_mutable_action_in_self_hosted_job_is_reported() -> None:
    text = """
name: example
on: workflow_dispatch
jobs:
  audit:
    runs-on: [self-hosted, Linux, ARM64]
    steps:
      - uses: actions/upload-artifact@v6
"""
    assert MODULE.mutable_self_hosted_uses(text) == (
        "audit:actions/upload-artifact@v6",
    )


def test_full_sha_action_in_self_hosted_job_is_allowed() -> None:
    text = """
name: example
on: workflow_dispatch
jobs:
  audit:
    runs-on:
      - self-hosted
      - Linux
    steps:
      - uses: actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f
"""
    assert MODULE.mutable_self_hosted_uses(text) == ()


def test_mutable_action_in_github_hosted_job_does_not_contaminate_self_hosted_job() -> None:
    text = """
name: example
on: workflow_dispatch
jobs:
  authorize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
  audit:
    runs-on: [self-hosted, Linux, ARM64]
    steps:
      - run: echo safe-fixed-dispatcher-only
"""
    assert MODULE.mutable_self_hosted_uses(text) == ()


def test_local_action_is_allowed_in_self_hosted_job() -> None:
    text = """
name: example
on: workflow_dispatch
jobs:
  audit:
    runs-on: [self-hosted, Linux, ARM64]
    steps:
      - uses: ./.github/actions/local-audit
"""
    assert MODULE.mutable_self_hosted_uses(text) == ()


def test_docker_action_requires_digest_not_tag() -> None:
    mutable = """
name: example
on: workflow_dispatch
jobs:
  audit:
    runs-on: [self-hosted, Linux, ARM64]
    steps:
      - uses: docker://alpine:3.20
"""
    pinned = """
name: example
on: workflow_dispatch
jobs:
  audit:
    runs-on: [self-hosted, Linux, ARM64]
    steps:
      - uses: docker://alpine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""
    assert MODULE.mutable_self_hosted_uses(mutable) == (
        "audit:docker://alpine:3.20",
    )
    assert MODULE.mutable_self_hosted_uses(pinned) == ()
