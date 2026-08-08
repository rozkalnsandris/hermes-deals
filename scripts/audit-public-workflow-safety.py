#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


@dataclass(frozen=True)
class WorkflowAudit:
    path: Path
    events: tuple[str, ...]
    self_hosted: bool
    checkout: bool


def extract_events(text: str) -> tuple[str, ...]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.fullmatch(r"on:\s*", line):
            events: list[str] = []
            for child in lines[index + 1 :]:
                if child and not child[0].isspace() and not child.lstrip().startswith("#"):
                    break
                match = re.match(r"^  ([A-Za-z_][A-Za-z0-9_-]*):(?:\s|$)", child)
                if match:
                    events.append(match.group(1))
            return tuple(events)

        inline = re.fullmatch(r"on:\s*\[(.*)\]\s*", line)
        if inline:
            return tuple(
                item.strip().strip("'\"")
                for item in inline.group(1).split(",")
                if item.strip()
            )

        scalar = re.fullmatch(r"on:\s*([A-Za-z_][A-Za-z0-9_-]*)\s*", line)
        if scalar:
            return (scalar.group(1),)
    return ()


def has_self_hosted_runner(text: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        inline = re.search(r"\bruns-on:\s*\[[^\]]*\bself-hosted\b", line)
        if inline:
            return True

        match = re.match(r"^(\s*)runs-on:\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                continue
            child_indent = len(child) - len(child.lstrip())
            if child_indent <= indent:
                break
            if re.fullmatch(r"\s*-\s*self-hosted\s*(?:#.*)?", child):
                return True
    return False


def audit(path: Path) -> WorkflowAudit:
    text = path.read_text(encoding="utf-8")
    return WorkflowAudit(
        path=path,
        events=extract_events(text),
        self_hosted=has_self_hosted_runner(text),
        checkout=bool(re.search(r"uses:\s*actions/checkout@", text)),
    )


def main() -> int:
    if not WORKFLOWS.is_dir():
        print("PUBLIC_WORKFLOW_AUDIT=FAIL reason=missing-workflows-directory", file=sys.stderr)
        return 1

    paths = sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
    if not paths:
        print("PUBLIC_WORKFLOW_AUDIT=FAIL reason=no-workflows", file=sys.stderr)
        return 1

    audits = [audit(path) for path in paths]
    self_hosted = [item for item in audits if item.self_hosted]
    blocked = [item for item in self_hosted if "pull_request" in item.events]
    pr_target_review = [
        item for item in self_hosted if "pull_request_target" in item.events
    ]
    issue_comment_review = [
        item for item in self_hosted if "issue_comment" in item.events
    ]
    review = sorted(
        {item.path: item for item in (*pr_target_review, *issue_comment_review)}.values(),
        key=lambda item: str(item.path),
    )

    print(f"PUBLIC_WORKFLOW_COUNT={len(audits)}")
    print(f"PUBLIC_SELF_HOSTED_WORKFLOW_COUNT={len(self_hosted)}")
    print(f"PUBLIC_SELF_HOSTED_PULL_REQUEST_BLOCK_COUNT={len(blocked)}")
    print(
        "PUBLIC_SELF_HOSTED_PULL_REQUEST_TARGET_REVIEW_COUNT="
        f"{len(pr_target_review)}"
    )
    print(
        "PUBLIC_SELF_HOSTED_ISSUE_COMMENT_REVIEW_COUNT="
        f"{len(issue_comment_review)}"
    )
    print(f"PUBLIC_SELF_HOSTED_MANUAL_REVIEW_COUNT={len(review)}")

    for item in self_hosted:
        rel = item.path.relative_to(ROOT)
        events = ",".join(item.events) if item.events else "unknown"
        classification = "trusted-trigger"
        if "pull_request" in item.events:
            classification = "BLOCK-direct-pull-request"
        elif "pull_request_target" in item.events and "issue_comment" in item.events:
            classification = "REVIEW-pull-request-target+issue-comment"
        elif "pull_request_target" in item.events:
            classification = "REVIEW-pull-request-target"
        elif "issue_comment" in item.events:
            classification = "REVIEW-issue-comment"
        print(
            "self-hosted-workflow"
            f" path={rel}"
            f" events={events}"
            f" checkout={str(item.checkout).lower()}"
            f" classification={classification}"
        )

    if blocked:
        print(
            "PUBLIC_WORKFLOW_AUDIT=FAIL reason=self-hosted-direct-pull-request",
            file=sys.stderr,
        )
        return 1

    if review:
        print(
            "PUBLIC_WORKFLOW_AUDIT=PASS_WITH_MANUAL_REVIEW"
            " reason=public-user-triggerable-self-hosted-workflows-require-owner-gate-review"
        )
    else:
        print("PUBLIC_WORKFLOW_AUDIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
