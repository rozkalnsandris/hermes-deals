#!/usr/bin/env python3
"""Audit every workflow Action and checkout using the CI-locked YAML parser."""
from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION_SHA = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}\Z")
VERSION = re.compile(r"#\s*(?:v\d[\w.-]*\b|reviewed policy revision [0-9a-f]{7,40}\b)")
# Existing trusted evidence writers only. A new exception requires source review.
CREDENTIAL_EXCEPTIONS = {
    ("netto-hz33-completed-truth-import-v3.yml", "import_exact_truth",
     "Checkout exact owner evidence PR head"):
        "Required only so this trusted base workflow can push the two allowlisted evidence files.",
    ("netto-hz34-completed-truth-import.yml", "validate-and-freeze",
     "Checkout exact evidence PR head only after truth validation"):
        "Required only to push the allowlisted immutable receipt to the exact owner-authorized evidence PR.",
}


def mapping(node: yaml.Node) -> dict[str, yaml.Node]:
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("expected YAML mapping")
    result = {}
    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode) or key.value in result or key.value == "<<":
            raise ValueError("duplicate, merged or non-scalar YAML key")
        result[key.value] = value
    return result


def scalar(node: yaml.Node | None) -> str:
    return node.value if isinstance(node, yaml.ScalarNode) else ""


def audit_text(text: str, filename: str) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    try:
        # Reject aliases rather than silently auditing a different anchor location.
        if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)):
            raise ValueError("YAML aliases are not supported in audited workflows")
        document = yaml.compose(text)
        if document is None:
            raise ValueError("empty workflow")
        jobs = mapping(mapping(document)["jobs"])
        for job_name, job_node in jobs.items():
            job = mapping(job_node)
            steps = job.get("steps")
            if steps is not None and not isinstance(steps, yaml.SequenceNode):
                raise ValueError("steps must be a sequence")
            entries = [job_node] if "uses" in job else []
            if steps is not None:
                entries.extend(steps.value)
            for entry in entries:
                data = mapping(entry)
                if "uses" not in data:
                    continue
                use_node = data["uses"]
                ref = scalar(use_node)
                location = f"{job_name}:{use_node.start_mark.line + 1}"
                if not ref.startswith("./"):
                    if not ACTION_SHA.fullmatch(ref):
                        errors.append(f"{location}: external Action must use full commit SHA: {ref}")
                    # Comments must accompany the actual scalar, including quoted/flow YAML.
                    line = lines[use_node.end_mark.line]
                    if not VERSION.search(line[use_node.end_mark.column:]):
                        errors.append(f"{location}: missing reviewed-version comment")
                if not ref.lower().startswith("actions/checkout@"):
                    continue
                inputs = mapping(data["with"]) if "with" in data else {}
                setting = inputs.get("persist-credentials")
                value = scalar(setting)
                exception = CREDENTIAL_EXCEPTIONS.get(
                    (filename, job_name, scalar(data.get("name")))
                )
                if value == "false":
                    continue
                documented = (
                    setting is not None and setting.start_mark.line > 0
                    and lines[setting.start_mark.line - 1].strip() == f"# {exception}"
                )
                if value != "true" or exception is None or not documented:
                    errors.append(f"{location}: checkout must explicitly disable credential persistence")
    except (yaml.YAMLError, ValueError, KeyError) as exc:
        errors.append(f"invalid workflow structure: {exc}")
    return errors


def main() -> int:
    paths = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    errors = [f"{path.name}: {error}" for path in paths
              for error in audit_text(path.read_text(encoding="utf-8"), path.name)]
    if not paths:
        errors.append("no workflows found")
    for error in errors:
        print(error, file=sys.stderr)
    print(f"WORKFLOW_ACTION_AUDIT={'FAIL' if errors else 'PASS'} workflows={len(paths)} violations={len(errors)}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
