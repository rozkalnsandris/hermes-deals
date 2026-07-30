from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence


# Scope taxonomy is intentionally generic and mirrors the validated V631 scope:
# physical-store food, drinks and household essentials are target; durable goods,
# clothing, electronics and generic online-only content are not.
_EDIBLE_HERB_RE = re.compile(
    r"\b(?:basilikum|petersilie|schnittlauch|koriander|dill|minze|kräuter?)\b",
    re.I,
)
_INCLUDE_HOUSEHOLD_RE = re.compile(
    r"\b(?:waschmittel|weichspüler|spülmittel|reiniger|toilettenpapier|windel|"
    r"pampers|taschentücher|küchenrolle|shampoo|duschgel|katzenstreu)\b",
    re.I,
)
_FOOD_DRINK_RE = re.compile(
    r"\b(?:milch|joghurt|käse|schnittkäse|butter|sahne|quark|zucker|fleisch|"
    r"hähnchen|rind|schwein|wurst|schinken|salami|pizza|flammkuchen|chips|"
    r"pasta|pesto|brot|frischkäse|croissant|tomate|apfel|mango|pfirsich|kiwi|"
    r"beeren|gemüse|obst|öl|honig|kaffee|tee|cola|fanta|sprite|wasser|saft|"
    r"bier|wein|whisky|vodka|likör|eis|garnelen|lachs|fisch|nudel|müsli|"
    r"riegel|nutella|schokolade|kaugummi|pommes)\b",
    re.I,
)
_COMPOUND_TARGET_RE = re.compile(
    r"(?:butter|croissant|brötchen|brot|käse|milch|joghurt|quark|wurst|"
    r"schinken|salami|fleisch|fisch|lachs|nudel|pasta|pizza|kuchen|torte|"
    r"schokolade|riegel|müsli|kaffee|tee|saft|cola|bier|wein|wasser|"
    r"waschmittel|weichspüler|spülmittel|reiniger|toilettenpapier|"
    r"taschentücher|küchenrolle|shampoo|duschgel|windel|katzenstreu)",
    re.I,
)
_HARD_NON_TARGET_RE = re.compile(
    r"\b(?:kombiservice|partygeschirr|geschirr|besteck|porzellan|pfanne|topfset|"
    r"kochtopf|kochplatte|toaster|waffeleisen|sandwichmaker|wassersprudler|"
    r"trinkflasche|multizerkleinerer|backofen|reiskocher|bratenform|"
    r"frischhaltedosen|staubsauger|bügeleisen|schubladenmatte|nähmaschine|"
    r"matratze|kissen|decke|schuhe|shirt|hose|jacke|kleid|socken|werkzeug|"
    r"bohrer|akku|rasenmäher|grillgerät|allround[-\s]?sup|stand[-\s]?up|"
    r"paddel|pool|reise|hotel|flug|fotobuch|fotoservice|karriere|job|"
    r"fahrrad|e[-\s]?bike|rutsche|wasserbahn|energiespartopf|tellerset|"
    r"servierschüssel|kaffeevollautomat|standmixer|fleckenreiniger|entsafter|"
    r"elektrischer mopp|saug[-\s]?und wischroboter|rucksack|schulranzen|"
    r"schultasche)\b",
    re.I,
)
_ORNAMENTAL_PLANT_RE = re.compile(
    r"\b(?:blühpflanze|gartenhortensie|hortensie|lavendel|grünpflanze|"
    r"orchidee|phalaenopsis|zierpflanze|blumenstrauß|blumenstrauss)\b",
    re.I,
)
_STRUCTURED_TARGET_CATEGORY_RE = re.compile(
    r"(?:lebensmittel|getränk|drogerie|körperpflege|waschen|reinigen|"
    r"haushaltsreiniger|tierbedarf|tierfutter|lebensmittelvorrat)",
    re.I,
)
_STRUCTURED_NON_TARGET_CATEGORY_RE = re.compile(
    r"(?:geschirr|besteck|porzellan|küchengerät|elektro|werkzeug|bekleidung|"
    r"mode|textil|möbel|sportgerät|freizeitgerät|reise|foto|spielzeug|spielware|"
    r"fahrrad|haushaltsgerät|kinderausstattung|schule|schulranzen|"
    r"schultaschen|rucksack)",
    re.I,
)
_TITLE_TARGET_RE = re.compile(
    r"\b(?:garnelen|lachs|fisch|pistaz|cashew|erdnüss|walnuss|mandel|nuts|"
    r"kohl|tomat|mais|apfel|pfirsich|heidelbeer|beeren|gemüse|obst|rinder|"
    r"fleisch|hähnchen|kaninchen|lammlachse|roastbeef|wurst|schinken|salami|"
    r"leberkäse|frikadellen|aufschnitt|würstchen|brot|brötchen|apfeltasche|"
    r"crusti|streusel|croissant|hefegebäck|milch|joghurt|quark|käse|"
    r"mozzarella|butter|crème|camembert|obazda|pizza|flammkuchen|pasta|pesto|"
    r"nudel|mehl|zucker|öl|ajvar|fond|chips|snack|riegel|schoko|schokolade|"
    r"candy|tiramisu|cantuccini|kaffee|coffee|tee|eistee|cola|fanta|sprite|"
    r"mezzo|energy|refresh|wasser|volvic|saft|drink|bier|pils|wein|sekt|"
    r"whisky|whiskey|wodka|vodka|ouzo|bourbon|liqueur|likör|waschmittel|"
    r"weichspüler|hygienespüler|spülmittel|reiniger|allzwecktücher|"
    r"toilettenpapier|taschentücher|küchenrolle|shampoo|duschgel|mundspül|"
    r"windel|pampers|katzenstreu|tierfutter|purina)\b",
    re.I,
)
_PROMO_NOISE_RE = re.compile(
    r"^(?:pro monat|gesamtpreis|gutscheincode|mit lidl plus|lidl plus|"
    r"nur online|auch online|uvp|je stück|je packung)$",
    re.I,
)
_ONLINE_ONLY_RE = re.compile(r"\bnur\s+online\b", re.I)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("ß", "ss").replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
    text = re.sub(r"[^\wäöü]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def text_similarity(first: object, second: object) -> float:
    a = normalize_text(first)
    b = normalize_text(second)
    if not a or not b:
        return 0.0
    score = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        score = max(score, min(len(a), len(b)) / max(len(a), len(b)))
    return score


def significant_tokens(value: object) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) >= 4 and not token.isdigit()
    }


def plausible_same_title(first: object, second: object) -> bool:
    a = normalize_text(first)
    b = normalize_text(second)
    if not a or not b:
        return False
    if a == b:
        return True
    common = significant_tokens(a) & significant_tokens(b)
    if not common:
        return False
    return text_similarity(a, b) >= 0.82


def classify_target_scope(
    *,
    title: object,
    structured_category_text: object = "",
) -> str:
    title_text = str(title or "")
    category_text = str(structured_category_text or "")

    if _EDIBLE_HERB_RE.search(title_text):
        return "in_scope"
    if _HARD_NON_TARGET_RE.search(title_text) or _ORNAMENTAL_PLANT_RE.search(title_text):
        return "excluded"
    if category_text:
        if _STRUCTURED_NON_TARGET_CATEGORY_RE.search(category_text):
            return "excluded"
        if _STRUCTURED_TARGET_CATEGORY_RE.search(category_text):
            return "in_scope"
    if (
        _INCLUDE_HOUSEHOLD_RE.search(title_text)
        or _FOOD_DRINK_RE.search(title_text)
        or _TITLE_TARGET_RE.search(title_text)
        or _COMPOUND_TARGET_RE.search(normalize_text(title_text))
    ):
        return "in_scope"
    return "review"


def is_online_only(
    *,
    local_text: object = "",
    structured_online_signal: bool = False,
) -> bool:
    if structured_online_signal:
        return True
    return _ONLINE_ONLY_RE.search(str(local_text or "")) is not None


def promo_or_non_product_title(value: object) -> bool:
    text = normalize_text(value)
    if not text:
        return True
    return _PROMO_NOISE_RE.fullmatch(text) is not None


def obvious_non_target_title(value: object) -> bool:
    return classify_target_scope(title=value) == "excluded"


def strong_ocr_title_echo(title: object, ocr_text: object) -> bool:
    """Return True when bounded OCR independently echoes the native title."""
    a = normalize_text(title)
    b = normalize_text(ocr_text)
    if len(a) < 4 or len(b) < 4:
        return False
    if a in b:
        return True

    title_tokens = significant_tokens(a)
    if not title_tokens:
        return False
    ocr_tokens = significant_tokens(b)
    common = title_tokens & ocr_tokens
    needed = 1 if len(title_tokens) == 1 else min(2, len(title_tokens))
    return len(common) >= needed and len(common) / len(title_tokens) >= 0.6


def bbox_center(box: Sequence[float]) -> tuple[float, float]:
    return (
        (float(box[0]) + float(box[2])) / 2.0,
        (float(box[1]) + float(box[3])) / 2.0,
    )


def bbox_center_distance(first: Sequence[float], second: Sequence[float]) -> float:
    ax, ay = bbox_center(first)
    bx, by = bbox_center(second)
    return math.hypot(ax - bx, ay - by)


def anchor_is_owned(
    *,
    page: int,
    price_eur: object,
    bbox: Sequence[float],
    owned: Iterable[Mapping[str, Any]],
    tolerance: float = 8.0,
) -> bool:
    price = str(price_eur)
    for row in owned:
        if int(row["page"]) != int(page):
            continue
        if str(row["price_eur"]) != price:
            continue
        if bbox_center_distance(bbox, row["bbox"]) <= tolerance:
            return True
    return False


def represented_on_page(
    *,
    page: int,
    title: object,
    represented: Mapping[int, Iterable[str]],
) -> bool:
    return any(
        plausible_same_title(title, existing)
        for existing in represented.get(int(page), ())
    )


WEEKLY_PAGE_ROLE_REVIEWED_STATUSES = frozenset(
    {
        "reviewed",
        "independent_page_role_reviewed_product_audit_in_progress",
    }
)


def load_weekly_target_profile(
    flyer_dir: Path,
    *,
    page_count: int,
) -> dict[str, Any] | None:
    """Load the immutable human-reviewed weekly physical page-role profile.

    The profile decides *which pages may be searched for missing observations*.
    It does not decide that any product is correct, in scope, or publishable.
    """
    path = Path(flyer_dir) / "review-profile.json"
    if not path.is_file():
        return None

    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid review-profile.json: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("review-profile.json must contain a JSON object")

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"unsupported review profile schema_version={schema_version!r}")

    target_kind = str(payload.get("target_kind") or "")
    if target_kind != "weekly_physical_deals":
        raise ValueError(f"unexpected review profile target_kind={target_kind!r}")

    raw_pages = payload.get("target_pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise ValueError("review profile target_pages must be a non-empty list")

    pages: list[int] = []
    for value in raw_pages:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"review profile page must be an integer: {value!r}")
        page = int(value)
        if page < 1 or page > int(page_count):
            raise ValueError(
                f"review profile page out of range: page={page} page_count={page_count}"
            )
        pages.append(page)

    if len(pages) != len(set(pages)):
        raise ValueError("review profile target_pages contains duplicates")

    status = str(payload.get("status") or "")
    return {
        "schema_version": 1,
        "status": status,
        "page_role_reviewed": status in WEEKLY_PAGE_ROLE_REVIEWED_STATUSES,
        "target_kind": target_kind,
        "target_pages": sorted(pages),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


class WeeklyTargetProfileGate(RuntimeError):
    def __init__(self, result: str, message: str) -> None:
        super().__init__(message)
        self.result = result


def require_weekly_target_profile(
    flyer_dir: Path,
    *,
    page_count: int,
) -> dict[str, Any]:
    profile = load_weekly_target_profile(flyer_dir, page_count=page_count)
    if profile is None:
        raise WeeklyTargetProfileGate(
            "WAIT_PROFILE",
            "review-profile.json is missing",
        )
    if not profile["page_role_reviewed"]:
        raise WeeklyTargetProfileGate(
            "WAIT_PROFILE",
            f"review profile page-role status is not reviewed: {profile['status']!r}",
        )
    return profile


def stable_candidate_key(
    *,
    flyer_key: str,
    scan: str,
    lane: str,
    page: int,
    title: str,
    price_eur: str | None,
    bbox: Sequence[float],
) -> str:
    payload = "|".join(
        (
            flyer_key,
            scan,
            lane,
            str(int(page)),
            normalize_text(title),
            price_eur or "",
            ",".join(f"{float(v):.2f}" for v in bbox),
        )
    ).encode("utf-8")
    return "weekly-" + hashlib.sha256(payload).hexdigest()[:32]
