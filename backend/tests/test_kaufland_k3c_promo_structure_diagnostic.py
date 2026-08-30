from __future__ import annotations

import json

from app import kaufland_k3c_promo_structure_diagnostic as promo


def test_descendant_public_amount_candidate_is_observed_but_not_promoted():
    html = """
    <html><body>
      <a class="k-product-tile" href="#" tabindex="0">
        <div class="promo-shell">nur <span class="k-price-tag__price">1,99 €</span></div>
        <span class="k-price-tag__old-price">2,79 €</span>
        <div class="k-price-tag--xtra"><span>1,49 €</span></div>
      </a>
    </body></html>
    """
    payload = promo.derive_promo_structure_projection(html)

    assert payload["diagnostic_status"] == "EVIDENCE_ONLY"
    assert payload["promo_role_promoted"] is False
    assert payload["nur_marker_count"] == 1
    assert payload["card_local_nur_marker_count"] == 1
    assert payload["orphan_nur_marker_count"] == 0
    marker = payload["marker_samples"][0]
    assert marker["public_amount_candidate_count"] == 1
    candidate = marker["public_amount_candidate_samples"][0]
    assert candidate["relation"] == "candidate_descendant_of_marker_parent"
    assert candidate["candidate_tag"] == "span"
    assert candidate["candidate_price_classes"] == ["k-price-tag__price"]
    assert candidate["candidate_xtra_class_present"] is False
    assert candidate["candidate_old_price_class_present"] is False


def test_duplicate_price_classes_are_canonicalized_for_sanitized_projection():
    html = """
    <html><body>
      <a class="k-product-tile" href="#" tabindex="0">
        <div class="k-price-shell k-price-shell">
          <span class="k-price-marker k-price-marker">nur</span>
          <span class="k-price-tag__price k-price-tag__price">1,99 €</span>
        </div>
      </a>
    </body></html>
    """
    payload = promo.derive_promo_structure_projection(html)

    marker = payload["marker_samples"][0]
    assert marker["marker_price_classes"] == ["k-price-marker"]
    candidate = marker["public_amount_candidate_samples"][0]
    assert candidate["candidate_price_classes"] == ["k-price-tag__price"]
    assert candidate["lca_price_classes"] == ["k-price-shell"]


def test_sibling_candidate_relation_is_structural_and_amount_is_not_emitted():
    html = """
    <html><body>
      <a class="k-product-tile" href="#" tabindex="0">
        <div class="promo-shell">
          <span class="promo-label">nur</span>
          <span class="k-price-tag__price">3,49 €</span>
        </div>
      </a>
    </body></html>
    """
    payload = promo.derive_promo_structure_projection(html)
    candidate = payload["marker_samples"][0]["public_amount_candidate_samples"][0]

    assert candidate["relation"] == "siblings"
    assert candidate["marker_parent_to_lca_steps"] == 1
    assert candidate["candidate_to_lca_steps"] == 1
    encoded = json.dumps(payload, sort_keys=True)
    assert "3.49" not in encoded
    assert "3,49" not in encoded


def test_explicit_xtra_and_old_price_branches_are_excluded_from_public_candidates():
    html = """
    <html><body>
      <a class="k-product-tile" href="#" tabindex="0">
        <span>nur</span>
        <span class="k-price-tag__old-price">2,79 €</span>
        <div class="k-price-tag--xtra"><span>1,49 €</span></div>
      </a>
    </body></html>
    """
    payload = promo.derive_promo_structure_projection(html)

    marker = payload["marker_samples"][0]
    assert marker["public_amount_candidate_count"] == 0
    assert payload["public_amount_candidate_pair_count"] == 0
    assert payload["distinct_structure_signature_count"] == 0
    assert payload["promo_role_promoted"] is False


def test_orphan_nur_marker_is_counted_without_inventing_card_ownership():
    html = """
    <html><body>
      <div class="outside">nur <span>4,99 €</span></div>
      <a class="k-product-tile" href="#" tabindex="0">
        <span class="k-price-tag__old-price">5,99 €</span>
      </a>
    </body></html>
    """
    payload = promo.derive_promo_structure_projection(html)

    assert payload["nur_marker_count"] == 1
    assert payload["card_local_nur_marker_count"] == 0
    assert payload["orphan_nur_marker_count"] == 1
    assert payload["marker_samples"] == []
    assert payload["orphan_marker_samples"][0]["marker"] == "text:nur"


def test_projection_is_deterministic_under_reversed_construction_order():
    html = """
    <html><body><main>
      <a class="k-product-tile" href="#" tabindex="0">
        <div><span>nur</span><span class="k-price-tag__price">1,99 €</span></div>
      </a>
      <a class="k-product-tile" href="#" tabindex="0">
        <div>nur <span class="k-price-tag__price">3,49 €</span></div>
      </a>
    </main></body></html>
    """
    first = promo.derive_promo_structure_projection(html)
    second = promo.derive_promo_structure_projection(
        html,
        reverse_construction_order=True,
    )

    assert first == second
    assert first["public_amount_candidate_pair_count"] == 2
    assert first["promo_role_promoted"] is False


def test_diagnostic_output_is_sanitized():
    html = """
    <html><body>
      <a class="k-product-tile" href="/secret-product-id" tabindex="0">
        <div>nur <span class="k-price-tag__price">1,99 €</span></div>
        <p>SECRET PRODUCT TITLE</p>
      </a>
    </body></html>
    """
    payload = promo.derive_promo_structure_projection(html)
    encoded = json.dumps(payload, sort_keys=True)

    assert "SECRET PRODUCT TITLE" not in encoded
    assert "/secret-product-id" not in encoded
    assert "<a " not in encoded
    assert "1,99" not in encoded
    assert "1.99" not in encoded


def test_blocked_payload_never_claims_promo_promotion():
    payload = promo._blocked_payload("PROMO_STRUCTURE_BLOCKED")

    assert payload["status"] == "BLOCKED"
    assert payload["evidence_only"] is True
    assert payload["promo_role_promoted"] is False
    assert payload["retained_evidence_write_performed"] is False
    assert payload["production_deploy_performed"] is False
