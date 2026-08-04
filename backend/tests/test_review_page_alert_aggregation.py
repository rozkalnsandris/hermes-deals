from __future__ import annotations

import unittest

from app.main import UI_REVIEW_PATH


class ReviewPageAlertAggregationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ui = UI_REVIEW_PATH.read_text(encoding="utf-8")

    def test_parent_child_binding_uses_immutable_bridge_provenance(self) -> None:
        for marker in (
            "function pageAlertChildParentId(item)",
            "item?.provenance?.parent_page_alert_id",
            "item?.original_payload?.weekly_page_alert_parent_id",
            "item?.provenance?.hint_index",
            "function pageAlertAggregate(alert)",
        ):
            self.assertIn(marker, self.ui)

    def test_aggregate_fails_closed_until_every_hint_is_terminal(self) -> None:
        for marker in (
            'const TERMINAL_STATUSES=new Set(["approved","rejected"]);',
            "const hintCount=Math.max(",
            "const allHintsLinked=hintCount>0&&linkedCount===hintCount;",
            "const resolvedByChildren=allHintsLinked&&unresolvedChildCount===0;",
            'const manuallyResolved=alert?.status==="rejected"&&unresolvedChildCount===0;',
        ):
            self.assertIn(marker, self.ui)

    def test_filters_counts_and_badges_use_effective_page_state(self) -> None:
        for marker in (
            "function effectiveReviewStatus(item)",
            "OPEN_STATUSES.has(effectiveReviewStatus(item))",
            "effectiveReviewStatus(item)===status",
            "const status=effectiveReviewStatus(item);if(status in counts)",
            "const status=effectiveReviewStatus(x);",
            "const statusBadge=`<span class=\"badge ${esc(status)}\">",
        ):
            self.assertIn(marker, self.ui)

    def test_page_detail_exposes_child_progress_and_navigation(self) -> None:
        for marker in (
            "const aggregate=pageAlertAggregate(selected);",
            "const effectiveStatus=effectiveReviewStatus(selected);",
            "aggregate.childGroups.get(index)",
            'data-open-child="${esc(child.id)}"',
            "Visi ${aggregate.hintCount} hinti ir izveidoti",
            "backendOpen&&!aggregate.resolved",
        ):
            self.assertIn(marker, self.ui)

    def test_hint_creation_applies_local_state_before_full_refresh(self) -> None:
        start = self.ui.index("async function createReviewFromHint(index){")
        end = self.ui.index("async function markPageAlertChecked(){", start)
        create_path = self.ui[start:end]

        replace_index = create_path.index("replaceAuthoritativeItem(d);")
        render_index = create_path.index("await renderList(d.id);")
        refresh_index = create_path.index(
            "await load(d.id,{preserveOnError:true});"
        )
        self.assertLess(replace_index, render_index)
        self.assertLess(render_index, refresh_index)
        self.assertIn(
            'if(refreshed)showToast("Review produkts izveidots.");',
            create_path,
        )


if __name__ == "__main__":
    unittest.main()
