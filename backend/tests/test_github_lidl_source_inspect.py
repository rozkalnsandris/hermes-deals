from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "github_lidl_source_inspect.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-source-inspect.yml"

SPEC = importlib.util.spec_from_file_location("github_lidl_source_inspect_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_event(body: str | None = None) -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 287},
        "comment": {
            "id": 5221750384,
            "body": body
            or "/hermes-lidl-source-inspect target=current as_of=2026-08-07",
        },
    }


def test_exact_allowlisted_command_parses() -> None:
    command = MODULE.parse_comment(
        "/hermes-lidl-source-inspect target=current as_of=2026-08-07"
    )
    assert command.target == "current"
    assert command.as_of == "2026-08-07"


@pytest.mark.parametrize(
    "body",
    [
        "/hermes-lidl-source-inspect target=current as_of=2026-08-07\necho pwned",
        "/hermes-lidl-source-inspect target=current as_of=2026-08-07 extra=1",
        "/hermes-lidl-source-inspect target=other as_of=2026-08-07",
        "/hermes-lidl-source-inspect target=current as_of=2026-02-30",
        "/hermes-lidl-source-inspect target=current as_of=2026-8-7",
        "/hermes-lidl-source-write target=current as_of=2026-08-07",
    ],
)
def test_parser_fails_closed_on_invalid_or_injected_text(body: str) -> None:
    with pytest.raises(MODULE.LidlSourceInspectError):
        MODULE.parse_comment(body)


def test_authorize_event_binds_exact_owner_issue_and_comment() -> None:
    assert MODULE.authorize_event(
        valid_event(), repository="rozkalnsandris/hermes-deals"
    ) == {
        "target": "current",
        "as_of": "2026-08-07",
        "issue_number": "287",
        "comment_id": "5221750384",
        "trigger_actor": "rozkalnsandris",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("login", "someone-else"), ("id", 1)],
)
def test_authorize_event_rejects_non_owner_sender(field: str, value: object) -> None:
    event = valid_event()
    event["sender"][field] = value
    with pytest.raises(MODULE.LidlSourceInspectError, match="allowlisted"):
        MODULE.authorize_event(event, repository="rozkalnsandris/hermes-deals")


def test_authorize_event_rejects_pull_request_comments() -> None:
    event = valid_event()
    event["issue"]["pull_request"] = {"url": "https://example.invalid/pr/1"}
    with pytest.raises(MODULE.LidlSourceInspectError, match="only on issues"):
        MODULE.authorize_event(event, repository="rozkalnsandris/hermes-deals")


def sample_source() -> bytes:
    payload = {
        "dateTime": "2026-08-07T20:00:00Z",
        "warnings": ["mutable"],
        "flyer": {
            "id": "official-id",
            "flyerUrlAbsolute": (
                "https://www.lidl.de/l/prospekte/aktionsprospekt-03-08-2026-08-08-2026-test/ar/21"
            ),
            "hiResPdfUrl": "https://assets.leaflets.schwarz/pdfs/official/source.pdf",
            "offerStartDate": "2026-08-03",
            "offerEndDate": "2026-08-08",
            "regions": [{"code": "21"}, {"code": "7"}],
            "pages": [
                {
                    "links": [
                        {"displayType": "product"},
                        {"productDetails": {"id": "x"}},
                        {"displayType": "web"},
                    ]
                },
                {"links": []},
            ],
        },
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def test_stable_identity_matches_gate_b_identity_contract() -> None:
    identity = MODULE.stable_source_identity(sample_source())
    assert identity == {
        "official_flyer_id": "official-id",
        "viewer_path": (
            "/l/prospekte/aktionsprospekt-03-08-2026-08-08-2026-test/ar/21"
        ),
        "document_path": "/pdfs/official/source.pdf",
        "valid_from": "2026-08-03",
        "valid_until": "2026-08-08",
        "advertised_regions": ["21", "7"],
        "page_count": 2,
    }
    assert len(MODULE.canonical_digest(identity)) == 64


def test_parser_input_identity_ignores_only_datetime_and_warnings() -> None:
    first = sample_source()
    payload = json.loads(first)
    payload["dateTime"] = "later"
    payload["warnings"] = ["different"]
    second = json.dumps(payload, sort_keys=True).encode("utf-8")
    assert MODULE.parser_input_identity(first) == MODULE.parser_input_identity(second)

    payload["flyer"]["offerEndDate"] = "2026-08-09"
    third = json.dumps(payload, sort_keys=True).encode("utf-8")
    assert MODULE.parser_input_identity(first) != MODULE.parser_input_identity(third)


def test_product_link_count_is_source_only() -> None:
    assert MODULE.product_link_count(sample_source()) == 2


def test_output_writer_never_writes_raw_source_content(tmp_path: Path) -> None:
    payload = {
        "result": "SOURCE_AVAILABLE",
        "reason": "sanitized_selected_store_source_identity",
        "target": "current",
        "as_of": "2026-08-07",
        "flyer_identifier": "safe",
        "route_region": "21",
        "valid_from": "2026-08-03",
        "valid_until": "2026-08-08",
        "official_flyer_id": "id",
        "page_count": 69,
        "product_link_count": 141,
        "pdf_sha256": "a" * 64,
        "raw_sha256": "b" * 64,
        "stable_source_identity_sha256": "c" * 64,
        "parser_input_identity_sha256": "d" * 64,
        "source_json": "FORBIDDEN",
        "source_pdf": "FORBIDDEN",
    }
    output = tmp_path / "out"
    MODULE.write_outputs(output, payload)
    text = output.read_text(encoding="utf-8")
    assert "FORBIDDEN" not in text
    assert "source_json" not in text
    assert "source_pdf" not in text


def test_workflow_is_hosted_read_only_and_has_no_rpi5_or_shell_escape() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"issue_comment"}
    assert triggers["issue_comment"]["types"] == ["created"]
    assert "startsWith(github.event.comment.body, '/hermes-lidl-source-inspect ')" in text
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted" not in text
    assert "sudo " not in text
    assert "ssh " not in text
    assert "scp " not in text
    assert "workflow_dispatch:" not in text
    assert "docker compose" not in text
    assert "systemctl " not in text
    assert "psql " not in text
    assert "alembic " not in text
    assert "source.pdf" not in text
    assert "source.json" not in text
    assert "actions/upload-artifact@v4" in text
    assert "retention-days: 30" in text


def test_tool_has_no_local_execution_or_mutation_surface() -> None:
    text = TOOL.read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "shell=True",
        "eval(",
        "exec(",
        "docker",
        "systemctl",
        "psql",
        "alembic",
    ):
        assert forbidden not in text
    assert "COMMAND_RE.fullmatch" in text
    assert 'EXPECTED_OWNER_LOGIN = "rozkalnsandris"' in text
    assert "EXPECTED_OWNER_ID = 277435981" in text
