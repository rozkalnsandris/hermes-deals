from __future__ import annotations

import unittest

from app.main import UI_REVIEW_PATH


class ReviewUiAuthoritativeStateContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ui = UI_REVIEW_PATH.read_text(encoding="utf-8")

    def test_mutation_response_is_applied_before_full_refresh(self) -> None:
        replace_index = self.ui.index("replaceAuthoritativeItem(d);")
        local_render_index = self.ui.index("await renderList(preferredId);")
        refresh_index = self.ui.index(
            "await load(preferredId,{preserveOnError:true});"
        )
        self.assertLess(replace_index, local_render_index)
        self.assertLess(local_render_index, refresh_index)

    def test_refresh_failure_preserves_authoritative_local_state(self) -> None:
        self.assertIn(
            "async function load(preferredId=null,{preserveOnError=false}={})",
            self.ui,
        )
        self.assertIn("if(!preserveOnError){", self.ui)
        self.assertIn(
            "Darbība pabeigta, bet sarakstu neizdevās pilnībā atjaunot.",
            self.ui,
        )

    def test_reopen_controls_match_backend_status_rules(self) -> None:
        self.assertIn(
            'function canReopenStatus(status){return '
            '["draft","needs_followup","rejected"].includes(status);}',
            self.ui,
        )
        self.assertIn(
            "${reopenAllowed?'<button id=\"reopen\" type=\"button\">"
            "Atgriezt gaidīšanā</button>':\"\"}",
            self.ui,
        )
        self.assertIn('id="page_reopen"', self.ui)
        self.assertIn('if($("reopen"))$("reopen").onclick=reopen;', self.ui)

    def test_approval_actions_follow_scope_and_channel(self) -> None:
        self.assertIn("function updateProductActionAvailability(){", self.ui)
        self.assertIn(
            'approveButton.disabled=busy||excluded||wrongChannel;',
            self.ui,
        )
        self.assertIn(
            'if(channel!=="physical_store")',
            self.ui,
        )

    def test_fast_approval_uses_shared_authoritative_call_path(self) -> None:
        start = self.ui.index("async function approveScopeOnlyFast(){")
        end = self.ui.index(
            "// fast_scope_approve is created dynamically",
            start,
        )
        fast_path = self.ui[start:end]
        self.assertIn("const body=await call(", fast_path)
        self.assertIn("{advance:true,successMessage:", fast_path)
        self.assertNotIn("selected=null;", fast_path)
        self.assertNotIn("await load();", fast_path)


if __name__ == "__main__":
    unittest.main()
