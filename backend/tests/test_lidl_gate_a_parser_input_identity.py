from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT / "tools", ROOT / "backend"):
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from lidl_weekly_one_shot import _parser_input_identity as gate_a_parser_input_identity  # noqa: E402
from lidl_weekly_staging import _parser_input_identity as staging_parser_input_identity  # noqa: E402


def source_payload() -> dict:
    return {
        "dateTime": "2026-08-07T07:00:00Z",
        "warnings": ["volatile warning"],
        "flyer": {
            "id": "official-1",
            "flyerUrlAbsolute": (
                "https://www.lidl.de/l/prospekte/aktionsprospekt-test/ar/21"
            ),
            "hiResPdfUrl": "https://assets.leaflets.schwarz/source.pdf",
            "offerStartDate": "2026-08-03",
            "offerEndDate": "2026-08-08",
            "regions": [{"code": "21"}, {"code": "7"}],
            "products": {
                "p1": {"productId": "p1", "title": "Milch"},
            },
            "pages": [
                {
                    "links": [
                        {
                            "displayType": "product",
                            "left": 10,
                            "top": 20,
                            "width": 30,
                            "height": 40,
                            "productDetails": {
                                "productId": "p1",
                                "title": "Milch",
                            },
                        }
                    ]
                }
            ],
        },
    }


def encoded(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def test_gate_a_and_staging_parser_input_identity_are_identical() -> None:
    payload = source_payload()
    assert gate_a_parser_input_identity(encoded(payload)) == staging_parser_input_identity(
        encoded(payload)
    )


def test_both_identities_ignore_only_known_volatile_top_level_fields() -> None:
    first = source_payload()
    second = source_payload()
    second["dateTime"] = "2026-08-07T08:30:00Z"
    second["warnings"] = ["different volatile warning"]

    first_gate = gate_a_parser_input_identity(encoded(first))
    second_gate = gate_a_parser_input_identity(encoded(second))
    first_staging = staging_parser_input_identity(encoded(first))
    second_staging = staging_parser_input_identity(encoded(second))

    assert first_gate == second_gate
    assert first_staging == second_staging
    assert first_gate == first_staging


def test_both_identities_change_for_parser_relevant_product_refresh() -> None:
    first = source_payload()
    second = source_payload()
    second["flyer"]["products"]["p1"]["title"] = "Vollmilch"

    first_gate = gate_a_parser_input_identity(encoded(first))
    second_gate = gate_a_parser_input_identity(encoded(second))
    first_staging = staging_parser_input_identity(encoded(first))
    second_staging = staging_parser_input_identity(encoded(second))

    assert first_gate != second_gate
    assert first_staging != second_staging
    assert first_gate == first_staging
    assert second_gate == second_staging
