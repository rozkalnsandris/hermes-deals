from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import unittest

from app.review_queue import (
    approve_scope_only_review_item,
    scope_only_fast_review_eligible,
)


def item(*, reasons, payload, status="pending", corrected=None):
    return SimpleNamespace(
        status=status,
        reason_codes=reasons,
        original_payload=payload,
        corrected_payload=corrected or {},
    )


BASE = {
    "product_name": "TEST Product",
    "price_eur": "1.99",
    "valid_from": "2026-08-03",
    "valid_until": "2026-08-08",
    "channel": "physical_store",
    "scope": "review",
    "price_basis": "fixed_or_explicit",
}


class ReviewScopeFastPathTest(unittest.TestCase):
    def test_server_gate_accepts_only_complete_scope_only_rows(self):
        self.assertTrue(
            scope_only_fast_review_eligible(
                item(reasons=["scope_requires_review"], payload=dict(BASE))
            )
        )

        variable=dict(BASE)
        variable["price_basis"]="variable_weight_example"
        self.assertFalse(
            scope_only_fast_review_eligible(
                item(
                    reasons=[
                        "scope_requires_review",
                        "variable_weight_requires_review",
                    ],
                    payload=variable,
                )
            )
        )

        missing=dict(BASE)
        missing["price_eur"]=""
        self.assertFalse(
            scope_only_fast_review_eligible(
                item(reasons=["scope_requires_review"], payload=missing)
            )
        )

        self.assertFalse(
            scope_only_fast_review_eligible(
                item(
                    reasons=["scope_requires_review"],
                    payload=dict(BASE),
                    status="approved",
                )
            )
        )

    def test_fast_approval_uses_existing_corrections_service_contract(self):
        review_item = item(
            reasons=["scope_requires_review"],
            payload=dict(BASE),
        )
        item_id = uuid4()
        note = "Scope-only fast review: human confirmed in-scope."

        with (
            patch("app.review_queue.get_review_item", return_value=review_item),
            patch("app.review_queue.save_review_draft") as save_draft,
            patch(
                "app.review_queue.approve_review_item",
                return_value=review_item,
            ) as approve,
        ):
            result = approve_scope_only_review_item(None, item_id=item_id)

        self.assertIs(result, review_item)
        save_draft.assert_called_once_with(
            None,
            item_id=item_id,
            corrections={"scope": "in_scope"},
            note=note,
            needs_followup=False,
        )
        approve.assert_called_once_with(
            None,
            item_id=item_id,
            note=note,
        )

    def test_ui_fast_path_has_matching_client_gate_and_protected_endpoint(self):
        html=(
            Path(__file__).resolve().parents[1]
            / "app"
            / "ui"
            / "review.html"
        ).read_text(encoding="utf-8")

        for marker in (
            'id="fast_scope_approve"',
            '✓ In scope + apstiprināt',
            'function scopeFastReviewEligible(item)',
            'reasons.has("scope_requires_review")',
            'reasons.has("variable_weight_requires_review")',
            'p.price_basis||""',
            'p.channel||""',
            'approve-scope-only',
            'method:"POST"',
            '$("fast_scope_approve").onclick=approveScopeOnlyFast',
            'if(await save(false)===false)return;',
            'const body=await call(',
            '{advance:true,successMessage:"Piedāvājums publicēts."}',
            'if(body)notifyDealsRefresh(body);',
        ):
            self.assertIn(marker, html)

        fast_path = html[
            html.index("async function approveScopeOnlyFast(){"):
            html.index("// fast_scope_approve is created dynamically")
        ]
        self.assertNotIn("selected=null;", fast_path)
        self.assertNotIn("await load();", fast_path)


if __name__ == "__main__":
    unittest.main()
