from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from app import kaufland_real_k2_v2_derivation as k3c


SYNTHETIC_HTML = """
<!doctype html>
<html><body><main>
  <div class="offer-card" data-family="DE_de_KDZ1_1503_D33">
    <a href="/angebote/detail.html?kloffer-articleID=A100">Secret Product Name Alpha</a>
    <div class="promo">nur <span>1,99 €</span></div>
    <span class="k-price-tag__old-price">2,79 €</span>
    <div class="k-price-tag--xtra">Mit Kaufland Card XTRA ** <span>1,49 €</span></div>
  </div>
  <div class="offer-card">
    <a href="/angebote/detail.html?kloffer-articleID=A200">Secret Product Name Beta</a>
    <div class="promo">nur <span>3,49 €</span></div>
  </div>
</main></body></html>
"""


def test_projection_is_deterministic_and_proves_separate_roles():
    first = k3c.derive_html_projection(SYNTHETIC_HTML)
    second = k3c.derive_html_projection(
        SYNTHETIC_HTML,
        reverse_construction_order=True,
    )

    assert first == second
    assert first["evidence_gate_status"] == "PASS"
    assert first["candidate_card_count"] == 2
    assert first["promo_receipt_count"] == 2
    assert first["reference_receipt_count"] == 1
    assert first["xtra_receipt_count"] == 1
    assert first["dual_promo_xtra_receipt_count"] == 1
    assert first["bound_family_count"] == 1
    assert first["unbound_family_count"] == 1
    assert (
        first["broad_ambiguity_probe"]["reason_code"]
        == "AMBIGUOUS_CARD_OWNERSHIP"
    )


def test_projection_is_sanitized_and_does_not_emit_product_text():
    payload = k3c.derive_html_projection(SYNTHETIC_HTML)
    encoded = json.dumps(payload, sort_keys=True)

    assert "Secret Product Name Alpha" not in encoded
    assert "Secret Product Name Beta" not in encoded
    assert "<div" not in encoded
    assert "kloffer-articleID=A100" not in encoded


def test_reference_is_not_inferred_from_larger_unlabelled_number():
    html = """
    <html><body>
      <div class="offer-card">
        <a href="/x?kloffer-articleID=A300">Hidden</a>
        <div class="promo">nur <span>1,99 €</span></div>
        <div class="generic-number">9,99 €</div>
      </div>
      <div class="offer-card"><a href="/x?kloffer-articleID=A301">Control</a></div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["promo_receipt_count"] == 1
    assert payload["reference_receipt_count"] == 0
    assert payload["evidence_gate_status"] == "BLOCKED"


def test_xtra_does_not_satisfy_public_promo():
    html = """
    <html><body>
      <div class="offer-card">
        <a href="/x?kloffer-articleID=A400">Hidden</a>
        <div class="k-price-tag--xtra">Kaufland Card XTRA 1,49 €</div>
      </div>
      <div class="offer-card"><a href="/x?kloffer-articleID=A401">Control</a></div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["xtra_receipt_count"] == 1
    assert payload["promo_receipt_count"] == 0
    assert payload["evidence_gate_status"] == "BLOCKED"


def test_multiple_same_role_candidates_fail_closed_for_that_role():
    html = """
    <html><body>
      <div class="offer-card">
        <a href="/x?kloffer-articleID=A500">Hidden</a>
        <span class="k-price-tag__old-price">2,79 €</span>
        <span class="k-price-tag__old-price">2,99 €</span>
        <div class="promo">nur 1,99 €</div>
      </div>
      <div class="offer-card"><a href="/x?kloffer-articleID=A501">Control</a></div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["reference_receipt_count"] == 0
    assert payload["blocker_counts"]["REFERENCE_ROLE_AMBIGUOUS"] == 1


def test_multiple_family_relations_become_unbound_ambiguous():
    html = """
    <html><body>
      <div class="offer-card" data-a="DE_de_KDZ1_1503_D33" data-b="DE_de_KDZ1_1503_D34">
        <a href="/x?kloffer-articleID=A600">Hidden</a>
        <div class="promo">nur 1,99 €</div>
      </div>
      <div class="offer-card"><a href="/x?kloffer-articleID=A601">Control</a></div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["bound_family_count"] == 0
    assert payload["unbound_family_count"] == 1
    assert payload["blocker_counts"]["FAMILY_BINDING_AMBIGUOUS"] == 1
    assert (
        payload["family_association_samples"][0]["blocker_reason"]
        == "FAMILY_BINDING_AMBIGUOUS"
    )
    assert payload["family_association_samples"][0]["family_relation"] is None


def test_target_scoped_fingerprint_is_stable_and_content_bound(tmp_path: Path):
    target = tmp_path / "kaufland" / "1503" / "k2" / "packet"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}", encoding="utf-8")
    data = target / "common.bin"
    data.write_bytes(b"alpha")

    first = k3c.target_scoped_fingerprint(target)
    second = k3c.target_scoped_fingerprint(target)
    assert first == second

    data.write_bytes(b"bravo")
    third = k3c.target_scoped_fingerprint(target)
    assert third != first


def test_target_fingerprint_does_not_scan_sibling_packets(tmp_path: Path):
    target = tmp_path / "kaufland" / "1503" / "k2" / "packet"
    sibling = tmp_path / "kaufland" / "1503" / "k2" / "other"
    target.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (target / "manifest.json").write_text("target", encoding="utf-8")
    (sibling / "manifest.json").write_text("before", encoding="utf-8")

    before = k3c.target_scoped_fingerprint(target)
    (sibling / "manifest.json").write_text("after", encoding="utf-8")
    after = k3c.target_scoped_fingerprint(target)
    assert after == before


def test_network_guard_fails_closed_before_socket_use():
    with k3c.network_guard():
        with pytest.raises(k3c.K3CDerivationError) as exc_info:
            socket.create_connection(("127.0.0.1", 9), timeout=0.01)
    assert exc_info.value.code == "NETWORK_FORBIDDEN"


def test_parser_backend_and_runtime_version_are_explicit():
    assert k3c.PARSER_BACKEND == "html.parser"
    assert k3c.EXPECTED_BS4_VERSION == "4.15.0"


def test_blocked_payload_carries_no_raw_error_message():
    payload = k3c._blocked_payload("OFFER_OVERVIEW_IDENTITY_MISMATCH")
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "OFFER_OVERVIEW_IDENTITY_MISMATCH"
    assert "/home/" not in encoded
    assert "Traceback" not in encoded
