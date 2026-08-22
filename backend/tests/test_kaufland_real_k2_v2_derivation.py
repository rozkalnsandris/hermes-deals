from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from app import kaufland_real_k2_v2_derivation as k3c


SYNTHETIC_HTML = """
<!doctype html>
<html><body><main>
  <section data-family="DE_de_KDZ1_1503_D33">
    <a href="/angebote/detail.html?kloffer-articleID=A100">Secret Product Name Alpha</a>
    <div>nur <span>1,99 €</span></div>
    <span class="k-price-tag__old-price">2,79 €</span>
    <div class="k-price-tag--xtra">Mit Kaufland Card XTRA ** <span>1,49 €</span></div>
  </section>
  <section>
    <a href="/angebote/detail.html?kloffer-articleID=A200">Secret Product Name Beta</a>
    <div>nur <span>3,49 €</span></div>
  </section>
</main></body></html>
"""


def test_projection_is_deterministic_but_promo_marker_stays_unproven():
    first = k3c.derive_html_projection(SYNTHETIC_HTML)
    second = k3c.derive_html_projection(
        SYNTHETIC_HTML,
        reverse_construction_order=True,
    )

    assert first == second
    assert first["evidence_gate_status"] == "BLOCKED"
    assert first["candidate_card_count"] == 2
    assert first["semantic_receipt_count"] == 1
    assert first["promo_receipt_count"] == 0
    assert first["reference_receipt_count"] == 1
    assert first["xtra_receipt_count"] == 1
    assert first["promo_marker_observation_count"] == 2
    assert first["bound_family_count"] == 1
    assert first["unbound_family_count"] == 0
    assert first["promo_role_policy"] == "BLOCKED_UNTIL_EXPLICIT_SOURCE_ROLE_EVIDENCE"
    assert first["blocker_counts"]["PROMO_MARKER_OBSERVED_ROLE_UNPROVEN"] == 2


def test_nur_with_one_price_never_becomes_public_promo():
    html = """
    <html><body>
      <div>
        <a href="/x?kloffer-articleID=A300">Hidden</a>
        <div>nur <span>1,99 €</span></div>
      </div>
      <div class="other">control</div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["candidate_card_count"] == 1
    assert payload["promo_marker_observation_count"] == 1
    assert payload["promo_receipt_count"] == 0
    assert payload["semantic_receipt_count"] == 0
    assert payload["evidence_gate_status"] == "BLOCKED"


def test_projection_is_sanitized_and_does_not_emit_product_text_or_article_id():
    payload = k3c.derive_html_projection(SYNTHETIC_HTML)
    encoded = json.dumps(payload, sort_keys=True)

    assert "Secret Product Name Alpha" not in encoded
    assert "Secret Product Name Beta" not in encoded
    assert "kloffer-articleID=A100" not in encoded
    assert "<section" not in encoded


def test_reference_requires_explicit_old_price_class():
    html = """
    <html><body>
      <div>
        <a href="/x?kloffer-articleID=A400">Hidden</a>
        <div>nur 1,99 €</div>
        <div class="generic-number">9,99 €</div>
        <div class="k-price-tag--xtra">XTRA 1,49 €</div>
      </div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["reference_receipt_count"] == 0
    assert payload["xtra_receipt_count"] == 1
    assert payload["promo_receipt_count"] == 0


def test_xtra_does_not_satisfy_public_promo():
    html = """
    <html><body>
      <div>
        <a href="/x?kloffer-articleID=A500">Hidden</a>
        <div class="k-price-tag--xtra">Kaufland Card XTRA 1,49 €</div>
      </div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["xtra_receipt_count"] == 1
    assert payload["promo_receipt_count"] == 0
    assert payload["evidence_gate_status"] == "BLOCKED"


def test_multiple_reference_candidates_fail_closed_for_that_role():
    html = """
    <html><body>
      <div>
        <a href="/x?kloffer-articleID=A600">Hidden</a>
        <span class="k-price-tag__old-price">2,79 €</span>
        <span class="k-price-tag__old-price">2,99 €</span>
        <div class="k-price-tag--xtra">XTRA 1,49 €</div>
      </div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["reference_receipt_count"] == 0
    assert payload["xtra_receipt_count"] == 1
    assert payload["blocker_counts"]["REFERENCE_ROLE_AMBIGUOUS"] == 1


def test_minimal_owner_scope_rejects_multiple_distinct_article_ids():
    html = """
    <html><body>
      <div>
        <a href="/x?kloffer-articleID=A700">One</a>
        <a href="/x?kloffer-articleID=A701">Two</a>
        <span class="k-price-tag__old-price">2,79 €</span>
      </div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["candidate_card_count"] == 0
    assert payload["semantic_receipt_count"] == 0


def test_family_binding_requires_exact_card_local_accepted_identifier():
    html = """
    <html><body>
      <div data-family="DE_de_KDZ1_1503_D33">
        <a href="/x?kloffer-articleID=A800">Hidden</a>
        <span class="k-price-tag__old-price">2,79 €</span>
      </div>
      <div>
        <a href="/x?kloffer-articleID=A801">Hidden</a>
        <span class="k-price-tag__old-price">3,79 €</span>
      </div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["bound_family_count"] == 1
    assert payload["unbound_family_count"] == 1
    statuses = {item["status"] for item in payload["family_association_samples"]}
    assert statuses == {"BOUND", "UNBOUND"}


def test_multiple_family_relations_become_unbound_ambiguous():
    html = """
    <html><body>
      <div data-a="DE_de_KDZ1_1503_D33" data-b="DE_de_KDZ1_1503_D34">
        <a href="/x?kloffer-articleID=A900">Hidden</a>
        <span class="k-price-tag__old-price">2,79 €</span>
      </div>
    </body></html>
    """
    payload = k3c.derive_html_projection(html)
    assert payload["bound_family_count"] == 0
    assert payload["unbound_family_count"] == 1
    assert payload["blocker_counts"]["FAMILY_BINDING_AMBIGUOUS"] == 1
    association = payload["family_association_samples"][0]
    assert association["blocker_reason"] == "FAMILY_BINDING_AMBIGUOUS"
    assert association["family_relation"] is None


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


def test_target_fingerprint_oserror_is_sanitized(monkeypatch, tmp_path: Path):
    target = tmp_path / "packet"
    target.mkdir()
    original_lstat = Path.lstat

    def fail_lstat(self):
        if self == target:
            raise OSError("secret /home/andris/path")
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", fail_lstat)
    with pytest.raises(k3c.K3CDerivationError) as exc_info:
        k3c.target_scoped_fingerprint(target)
    assert exc_info.value.code == "TARGET_FINGERPRINT_READ_FAILED"
    assert "/home/andris" not in str(exc_info.value)


def test_overview_read_oserror_is_sanitized(monkeypatch, tmp_path: Path):
    target = tmp_path.joinpath(*k3c.EXPECTED_K2_BUNDLE_KEY.split("/"))
    target.mkdir(parents=True)
    manifest = {
        "common_sources": [
            {
                "role": k3c.SOURCE_ARTIFACT_ROLE,
                "relative_path": k3c.EXPECTED_OVERVIEW_RELATIVE_PATH,
                "sha256": k3c.EXPECTED_OVERVIEW_SHA256,
                "byte_count": k3c.EXPECTED_OVERVIEW_BYTES,
                "content_type": k3c.EXPECTED_OVERVIEW_CONTENT_TYPE,
            }
        ]
    }
    (target / k3c.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    overview = target / k3c.EXPECTED_OVERVIEW_RELATIVE_PATH
    overview.parent.mkdir(parents=True, exist_ok=True)
    overview.write_bytes(b"x")

    original_read_bytes = Path.read_bytes

    def fail_read_bytes(self):
        if self == overview:
            raise OSError("secret /home/andris/path")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)
    with pytest.raises(k3c.K3CDerivationError) as exc_info:
        k3c._load_verified_overview(tmp_path)
    assert exc_info.value.code == "OFFER_OVERVIEW_READ_FAILED"
    assert "/home/andris" not in str(exc_info.value)
