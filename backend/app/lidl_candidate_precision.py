from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.lidl_page_schema_inspector import grocery_hits

# Phase 2B15 is a post-processing audit only.  It consumes the existing
# full-grocery OCR dry-run report and does not fetch flyer assets or write DB rows.
_ORIGIN_TERMS = {
    "deutschland", "frankreich", "italien", "spanien", "griechenland", "irland",
    "japan", "japanese", "lombardei", "toskana", "rhone", "rhône", "europa",
}
_DESCRIPTOR_ONLY = {
    "trocken", "halbtrocken", "lieblich", "brut", "organic", "original",
    "aktion", "angebot", "normalpreis", "sorten", "klasse", "ursprung",
    "cards", "produkte", "produkt", "jahre",
}
_TRAILING_GLUE = {
    "in", "im", "am", "an", "aus", "ausder", "der", "die", "das", "von", "vom", "mit", "und",
}
_NOISE_RE = re.compile(
    r"(?:\bkauf\s+von\s+\d+\s*(?:stk|stück)\b|\b\d+er[-\s]?pack\b|\b\d+\s+jahre\b|"
    r"\b(?:je\s+)?\d+(?:[,.]\d+)?\s*(?:ml|cl|l|liter|g|kg|stk|stück)\b\s*$|"
    r"\b(?:blauen|roten|grünen)\s+produkten\b|\ba\s+liter\b)",
    re.IGNORECASE,
)
_FRAGMENT_RE = re.compile(r"(?:[-–/]\s*$|^\W+$)")
_BRANDLIKE_RE = re.compile(r"^[A-ZÄÖÜ0-9][A-ZÄÖÜ0-9&+./'’\-]{2,}$")
_ALPHA_RE = re.compile(r"[A-Za-zÄÖÜäöüß]")
_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")

_PACKAGING_LABEL_TERMS = {
    "abtropfgewicht", "fullmenge", "fuellmenge", "nettofullmenge", "nettofuellmenge",
    "pfand", "vol", "volumen", "inhalt",
}
_NONFOOD_CUES = {
    "easyfill", "filterkorb", "filter", "schlauch", "pumpe", "akku", "bettwasche",
    "bettwaesche", "staufach", "mahroboter", "maehroboter", "rasen", "werkzeug",
    "crivit", "parkside", "silvercrest",
}
_ALCOHOL_CUES = {
    "wein", "rosewein", "rotwein", "weisswein", "champagner", "sekt", "gin", "vodka",
    "whisky", "whiskey", "pisco", "rum", "likor", "likoer", "brut",
}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", asciiish.lower())


def _words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text or "")
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return [_fold(w) for w in _WORD_RE.findall(asciiish) if len(_fold(w)) >= 2]


def _clean_label(text: str) -> str:
    value = " ".join((text or "").replace("®", "").split()).strip(" |,:;\t")
    # Common OCR shape: a valid brand/product followed by a dangling preposition,
    # e.g. "COCA-COLA in". Trim only one trailing glue word; do not rewrite the
    # substantive product label.
    bits = value.split()
    if len(bits) >= 2 and _fold(bits[-1]) in _TRAILING_GLUE:
        value = " ".join(bits[:-1]).strip()
    return value


def _origin_only(words: list[str]) -> bool:
    if not words:
        return False
    origins = {_fold(x) for x in _ORIGIN_TERMS}
    return all(word in origins for word in words)


def _descriptor_only(words: list[str]) -> bool:
    if not words:
        return False
    descriptors = {_fold(x) for x in _DESCRIPTOR_ONLY}
    return all(word in descriptors for word in words)


def _brandlike(label: str) -> bool:
    tokens = [t.strip("|()[]{}:,;") for t in re.split(r"\s+", label) if t.strip()]
    for token in tokens:
        if _BRANDLIKE_RE.fullmatch(token) and any(ch.isalpha() for ch in token):
            return True
        letters = [ch for ch in token if ch.isalpha()]
        if len(letters) >= 4 and sum(ch.isupper() for ch in letters) / len(letters) >= 0.75:
            return True
    return False


def _candidate_page_map(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for page in report.get("pages") or []:
        if not isinstance(page, dict):
            continue
        number = int(page.get("page") or 0)
        if number <= 0:
            continue
        selection = page.get("selection") if isinstance(page.get("selection"), dict) else {}
        out[number] = selection
    return out



def _contains_folded_term(label: str, terms: set[str]) -> bool:
    folded_words = set(_words(label))
    folded_label = _fold(label)
    folded_terms = {_fold(x) for x in terms}
    return bool(folded_words & folded_terms) or any(term and term in folded_label for term in folded_terms)


def _math_context_mismatch(candidate: dict[str, Any]) -> bool:
    actual = candidate.get("ocr_price_eur")
    expected = candidate.get("math_expected_price_eur")
    try:
        if actual is None or expected is None:
            return False
        actual_f = float(actual)
        expected_f = float(expected)
    except (TypeError, ValueError):
        return False
    delta = abs(actual_f - expected_f)
    tolerance = max(0.05, abs(expected_f) * 0.03)
    return delta > tolerance



def _high_confidence_math_correction(candidate: dict[str, Any]) -> bool:
    # Strict shadow-only promotion. This never enables a DB write.
    if str(candidate.get("evidence_tier") or "") != "math_correction_review":
        return False
    if str(candidate.get("precision_disposition") or "") != "correction_review":
        return False

    psm_support = int(candidate.get("psm_support") or len(candidate.get("psm_modes") or []))
    semantic_score = float(candidate.get("semantic_score") or 0.0)
    label_quality = float(candidate.get("label_quality_score") or 0.0)
    overlap = [str(x) for x in (candidate.get("keyword_overlap") or []) if str(x).strip()]

    if psm_support < 2 or semantic_score < 8.0 or label_quality < 10.0 or not overlap:
        return False
    if not str(candidate.get("package_text") or "").strip():
        return False
    if candidate.get("unit_price") is None:
        return False

    try:
        ocr_price = round(float(candidate.get("ocr_price_eur")), 2)
        corrected = round(float(candidate.get("proposed_corrected_price_eur")), 2)
        expected = round(float(candidate.get("math_expected_price_eur")), 2)
    except (TypeError, ValueError):
        return False

    if corrected <= 0 or corrected != expected or corrected == ocr_price:
        return False
    if abs(corrected - ocr_price) > 0.15:
        return False

    return True


def _strict_ready_math_consistent(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("evidence_tier") or "") == "math_corrected_verified":
        try:
            corrected = round(float(candidate.get("proposed_corrected_price_eur")), 2)
            expected = round(float(candidate.get("math_expected_price_eur")), 2)
            effective = round(float(candidate.get("effective_price_eur")), 2)
        except (TypeError, ValueError):
            return False
        return corrected == expected == effective
    return not _math_context_mismatch(candidate)


def _strict_base_assessment(candidate: dict[str, Any]) -> tuple[str, str | None, list[str]]:
    """Second-stage persistence shadow gate. Never enables DB writes."""
    disposition = str(candidate.get("precision_disposition") or "")
    tier = str(candidate.get("evidence_tier") or "")
    label = str(candidate.get("product_name_clean") or candidate.get("product_name_raw") or "")
    psm_support = int(candidate.get("psm_support") or len(candidate.get("psm_modes") or []))
    semantic_score = float(candidate.get("semantic_score") or 0.0)
    overlap = [str(x) for x in (candidate.get("keyword_overlap") or []) if str(x).strip()]
    label_grocery = [str(x) for x in (candidate.get("label_grocery_hits") or [])]
    page_grocery = {_fold(str(x)) for x in (candidate.get("page_grocery_hits") or [])}
    reasons: list[str] = []

    if disposition == "reject_noise":
        return "strict_reject", str(candidate.get("precision_reject_reason") or "precision_reject"), ["precision_reject"]
    if tier == "unresolved_math_conflict":
        return "strict_review", "unresolved_math_conflict", ["math_conflict"]
    if tier == "math_correction_review" or disposition == "correction_review":
        if _high_confidence_math_correction(candidate):
            return "strict_ready", None, [
                "math_corrected_verified",
                "dual_psm",
                "unit_price_math_agreement",
                "correction_provenance_preserved",
            ]
        return "strict_review", "math_correction_review", ["correction_requires_review"]
    if disposition == "math_verified_name_review":
        return "strict_review", "math_verified_name_review", ["verified_price_but_name_uncertain"]
    if _contains_folded_term(label, _PACKAGING_LABEL_TERMS):
        return "strict_review", "packaging_descriptor_label", ["packaging_descriptor"]
    if _contains_folded_term(label, _NONFOOD_CUES):
        return "strict_reject", "nonfood_product_label", ["nonfood_cue"]
    if tier == "semantic_price_only" and _math_context_mismatch(candidate):
        return "strict_review", "math_context_price_mismatch", ["nearby_math_disagrees"]
    if tier == "semantic_price_only":
        try:
            semantic_price = float(candidate.get("ocr_price_eur"))
        except (TypeError, ValueError):
            semantic_price = None
        if semantic_price is not None and semantic_price < 1.0:
            return "strict_review", "sub_euro_semantic_without_math", ["sub_euro_without_math"]

    alcohol_context = bool(page_grocery & {_fold(x) for x in _ALCOHOL_CUES}) or _contains_folded_term(label, _ALCOHOL_CUES)
    if tier == "semantic_price_only" and alcohol_context:
        actual = candidate.get("ocr_price_eur")
        try:
            actual_f = float(actual) if actual is not None else None
        except (TypeError, ValueError):
            actual_f = None
        if actual_f is not None and actual_f < 1.0:
            return "strict_review", "possible_beverage_volume_not_price", ["alcohol_context", "sub_euro_numeric"]
        return "strict_review", "alcohol_semantic_only_requires_review", ["alcohol_context"]

    if tier == "math_verified":
        reasons.extend(["math_verified", "name_passed_strict_filters"])
        return "strict_ready", None, reasons

    if disposition != "semantic_high_precision":
        return "strict_review", "not_high_precision_semantic", ["precision_stage_not_ready"]
    if psm_support < 2:
        return "strict_review", "single_psm_semantic_only", ["single_psm"]
    if semantic_score < 9.0:
        return "strict_review", "semantic_score_below_strict_gate", ["semantic_score_below_9"]
    if len(overlap) < 2 and not label_grocery:
        return "strict_review", "insufficient_metadata_product_evidence", ["weak_metadata_evidence"]

    reasons.extend(["dual_psm", "high_semantic_score", "metadata_product_evidence"])
    return "strict_ready", None, reasons


def apply_strict_gate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assessed: list[dict[str, Any]] = []
    for candidate in candidates:
        disposition, reason, reasons = _strict_base_assessment(candidate)
        item = {
            **candidate,
            "strict_disposition": disposition,
            "strict_reason": reason,
            "strict_reasons": reasons,
            "db_write_eligible": False,
        }
        if "math_corrected_verified" in reasons:
            item["evidence_tier"] = "math_corrected_verified"
            item["corrected_price_verified"] = True
            item["effective_price_eur"] = candidate.get("proposed_corrected_price_eur")
        assessed.append(item)

    # A repeated generic OCR label with different prices on the same page is not
    # safe enough for persistence without a stronger product identity.
    collisions: dict[tuple[int, str], set[float]] = {}
    for candidate in assessed:
        if candidate["strict_disposition"] == "strict_reject":
            continue
        key = (int(candidate.get("page") or 0), _fold(str(candidate.get("product_name_clean") or "")))
        if not key[1]:
            continue
        try:
            price = round(float(candidate.get("ocr_price_eur")), 2)
        except (TypeError, ValueError):
            continue
        collisions.setdefault(key, set()).add(price)

    ambiguous = {key for key, prices in collisions.items() if len(prices) > 1}
    if ambiguous:
        for candidate in assessed:
            key = (int(candidate.get("page") or 0), _fold(str(candidate.get("product_name_clean") or "")))
            if key in ambiguous and candidate.get("evidence_tier") != "math_verified":
                candidate["strict_disposition"] = "strict_review"
                candidate["strict_reason"] = "ambiguous_same_label_multiple_prices"
                candidate["strict_reasons"] = list(candidate.get("strict_reasons") or []) + ["same_label_multiple_prices"]

    return assessed


def assess_candidate(candidate: dict[str, Any], page_selection: dict[str, Any] | None = None) -> dict[str, Any]:
    page_selection = page_selection or {}
    raw_label = str(candidate.get("product_name_raw") or "").strip()
    label = _clean_label(raw_label)
    words = _words(label)
    tier = str(candidate.get("evidence_tier") or "")
    psm_support = int(candidate.get("psm_support") or len(candidate.get("psm_modes") or []))
    semantic_score = float(candidate.get("semantic_score") or 0.0)
    overlap = [str(x) for x in (candidate.get("keyword_overlap") or []) if str(x).strip()]
    label_grocery = grocery_hits(label)
    page_grocery = [str(x) for x in (page_selection.get("grocery_hits") or [])]

    reasons: list[str] = []
    reject_reason: str | None = None

    if tier == "unresolved_math_conflict":
        reject_reason = "unresolved_math_conflict"
    elif not label or not _ALPHA_RE.search(label):
        reject_reason = "empty_or_nonalpha_label"
    elif _NOISE_RE.search(label):
        reject_reason = "package_promo_or_sentence_noise"
    elif _FRAGMENT_RE.search(label):
        reject_reason = "dangling_fragment"
    elif _origin_only(words):
        reject_reason = "origin_only"
    elif _descriptor_only(words):
        reject_reason = "descriptor_only"

    score = 0.0
    if tier == "math_verified":
        score += 8.0
        reasons.append("math_verified")
    elif tier == "math_correction_review":
        score += 6.0
        reasons.append("math_correction_review")
    elif tier == "semantic_price_only":
        score += 1.0
        reasons.append("semantic_price_only")

    if psm_support >= 2:
        score += 2.0
        reasons.append("dual_psm")
    if semantic_score >= 9.0:
        score += 2.0
        reasons.append("high_semantic_score")
    elif semantic_score >= 6.0:
        score += 1.0
        reasons.append("semantic_score")
    if len(overlap) >= 2:
        score += 2.0
        reasons.append("multi_metadata_overlap")
    elif overlap:
        score += 1.0
        reasons.append("metadata_overlap")
    if label_grocery:
        score += 3.0
        reasons.append("product_grocery_term")
    if _brandlike(label):
        score += 1.5
        reasons.append("brandlike_label")
    if len(words) >= 2:
        score += 0.5
    if len(page_grocery) >= 2:
        score += 0.5
        reasons.append("stronger_page_grocery_context")
    elif len(page_grocery) == 1 and not label_grocery and tier == "semantic_price_only":
        score -= 1.0
        reasons.append("weak_single_term_page_context")

    # Do not let a noisy label become precision-ready merely because a numeric
    # price had strong OCR support. Math verified rows remain trusted evidence,
    # but a clearly broken label is still routed to review rather than persistence.
    if reject_reason:
        if tier == "math_verified":
            disposition = "math_verified_name_review"
        elif tier == "math_correction_review":
            disposition = "correction_review"
        else:
            disposition = "reject_noise"
    elif tier == "math_verified":
        disposition = "precision_ready"
    elif tier == "math_correction_review":
        disposition = "correction_review"
    elif score >= 7.0:
        disposition = "semantic_high_precision"
    elif score >= 4.0:
        disposition = "semantic_review"
    else:
        disposition = "reject_noise"
        if reject_reason is None:
            reject_reason = "insufficient_product_evidence"

    return {
        **candidate,
        "product_name_clean": label,
        "label_quality_score": round(score, 2),
        "label_grocery_hits": label_grocery,
        "page_grocery_hits": page_grocery,
        "brandlike_label": _brandlike(label),
        "precision_disposition": disposition,
        "precision_reasons": reasons,
        "precision_reject_reason": reject_reason,
        "db_write_eligible": False,
    }


def audit_candidate_precision(*, full_report_path: Path, output_dir: Path) -> dict[str, Any]:
    source = json.loads(full_report_path.read_text(encoding="utf-8"))
    if source.get("strategy") != "full_grocery_ocr_dry_run":
        raise ValueError("Input is not a Lidl full-grocery OCR dry-run report")
    if source.get("db_write_performed") is not False:
        raise ValueError("Precision audit only accepts non-writing dry-run reports")

    page_map = _candidate_page_map(source)
    source_candidates = [c for c in (source.get("dry_run_candidates") or []) if isinstance(c, dict)]
    assessed = [assess_candidate(c, page_map.get(int(c.get("page") or 0))) for c in source_candidates]
    assessed = apply_strict_gate(assessed)

    counts = Counter(str(c["precision_disposition"]) for c in assessed)
    strict_counts = Counter(str(c["strict_disposition"]) for c in assessed)
    strict_reason_counts = Counter(
        str(c.get("strict_reason")) for c in assessed if c.get("strict_reason")
    )
    reject_counts = Counter(
        str(c.get("precision_reject_reason"))
        for c in assessed
        if c.get("precision_reject_reason")
    )
    page_counts: Counter[int] = Counter(int(c.get("page") or 0) for c in assessed if c["precision_disposition"] != "reject_noise")

    precision_ready_total = counts["precision_ready"] + counts["semantic_high_precision"]
    review_total = counts["semantic_review"] + counts["correction_review"] + counts["math_verified_name_review"]
    rejected_total = counts["reject_noise"]

    report: dict[str, Any] = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "lidl_full_grocery_candidate_precision_audit",
        "db_write_performed": False,
        "source_report": str(full_report_path),
        "source_report_generated_at": source.get("generated_at"),
        "source_leaflet_key": source.get("leaflet_key"),
        "source_offer_start": source.get("offer_start"),
        "source_offer_end": source.get("offer_end"),
        "source_candidate_total": len(source_candidates),
        "precision_ready_total": precision_ready_total,
        "review_total": review_total,
        "rejected_noise_total": rejected_total,
        "strict_ready_total": strict_counts["strict_ready"],
        "strict_review_total": strict_counts["strict_review"],
        "strict_rejected_total": strict_counts["strict_reject"],
        "disposition_counts": dict(sorted(counts.items())),
        "strict_disposition_counts": dict(sorted(strict_counts.items())),
        "strict_reason_counts": dict(sorted(strict_reason_counts.items())),
        "reject_reason_counts": dict(sorted(reject_counts.items())),
        "pages_with_nonrejected_candidates": len(page_counts),
        "nonrejected_candidates_by_page": dict(sorted(page_counts.items())),
        "candidates": assessed,
        "gate": {
            "source_is_dry_run": True,
            "all_db_write_disabled": all(c.get("db_write_eligible") is False for c in assessed),
            "source_candidate_count_matches": len(source_candidates) == int(source.get("dry_run_candidate_total") or len(source_candidates)),
            "strict_ready_has_no_math_context_mismatch": all(
                _strict_ready_math_consistent(c)
                for c in assessed
                if c.get("strict_disposition") == "strict_ready"
            ),
            "strict_ready_all_nonwriting": all(
                c.get("db_write_eligible") is False for c in assessed if c.get("strict_disposition") == "strict_ready"
            ),
        },
    }

    # The strict gate is a persistence shadow only. It is intentionally smaller
    # than the Phase 2B15 "precision-ready" bucket and is allowed to prefer
    # precision over recall before OfferCandidate mapping is attempted.
    if strict_counts["strict_ready"] >= 4 and report["gate"]["strict_ready_has_no_math_context_mismatch"]:
        recommendation = "offer_candidate_contract_shadow_ready"
    elif strict_counts["strict_ready"] >= 2:
        recommendation = "strict_subset_small_but_usable"
    else:
        recommendation = "tighten_pairing_before_contract_mapping"
    report["recommendation"] = recommendation

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"{stamp}-lidl-candidate-precision-audit.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
