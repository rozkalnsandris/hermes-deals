from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
import hashlib
import importlib.util
from pathlib import Path
import sys
import types
from typing import Any

from app.lidl_weekly_semantics import gate_parser_report
from app.schemas import OfferCandidate


BASE_SHA256 = "55b403e1b23eb3bce5eb67e2d1665b47be7bf4d5e8ea109234f9c317a77518a2"
SHADOW_SHA256 = "7191e910f07bb0a14ece3f398f1ba73e3ea250fc4bec1aeafea3afa8ce6dda90"
PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"


class FlyerTarget(StrEnum):
    CURRENT = "current"
    NEXT = "next"


@dataclass(frozen=True)
class DiscoveredFlyer:
    target: FlyerTarget
    hub_url: str
    viewer_url: str
    flyer_identifier: str
    route_region: str
    advertised_regions: tuple[str, ...]
    schwarz_json_url: str
    document_url: str
    official_flyer_id: str
    valid_from: date | None
    valid_until: date | None
    raw_fetch: bytes
    raw_fetch_sha256: str
    etag: str | None
    last_modified: str | None
    hub_etag: str | None
    hub_last_modified: str | None
    viewer_etag: str | None
    viewer_last_modified: str | None
    discovered_at: datetime
    product_bindings: tuple["ProductBinding", ...] = ()


@dataclass(frozen=True)
class ProductBinding:
    page: int
    product_id: str
    title: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class TextSpan:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    font: str = ""
    size: float = 0.0
    flags: int = 0


@dataclass(frozen=True)
class DisplayPriceObservation:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    price_eur: str
    font: str
    size: float


@dataclass(frozen=True)
class PhysicalCard:
    page: int
    card_index: int
    bbox: tuple[float, float, float, float]
    spans: tuple[TextSpan, ...]
    prices: tuple[DisplayPriceObservation, ...]
    title: str | None
    title_bbox: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class CardSemanticOffer:
    page: int
    card_index: int
    semantic_index: int
    product_name: str
    price_eur: str
    app_price_eur: str | None
    requires_app: bool
    package_text: str | None
    variant_key: str
    classification: str
    valid_from: date | None
    valid_until: date | None
    app_valid_from: date | None
    app_valid_until: date | None
    occurrence: dict[str, Any]
    official_product_id: str | None = None


@dataclass(frozen=True)
class UnresolvedObservation:
    reason: str
    page: int | None
    text: str
    bbox: tuple[float, float, float, float] | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LidlParseResult:
    offers: tuple[OfferCandidate, ...]
    unresolved: tuple[UnresolvedObservation, ...]
    parser_input_fingerprint_v1: str
    display_prices: tuple[DisplayPriceObservation, ...]
    physical_cards: tuple[PhysicalCard, ...]
    semantic_occurrences: tuple[CardSemanticOffer, ...]


class SemanticGatedShadowRuntime:
    """Read-only proxy that keeps frozen parser rows review-only by default."""

    def __init__(self, module: types.ModuleType) -> None:
        self._module = module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module, name)

    @property
    def raw_module(self) -> types.ModuleType:
        return self._module

    def analyze_lidl_pdf(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        report = self._module.analyze_lidl_pdf(*args, **kwargs)
        if not isinstance(report, dict):
            raise RuntimeError("Frozen Lidl V6.3.1 parser returned a non-object report")
        return gate_parser_report(report)


@dataclass(frozen=True)
class LidlV631Runtime:
    base: types.ModuleType
    shadow: SemanticGatedShadowRuntime
    provenance_dir: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_provenance_dir() -> Path:
    candidates = (
        Path(__file__).resolve().with_name("v631"),
        Path("/repo/tools/lidl_parser_provenance/v631"),
        Path.cwd() / "tools" / "lidl_parser_provenance" / "v631",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Lidl V6.3.1 provenance directory was not found")


def _models_module() -> types.ModuleType:
    module = types.ModuleType("app.lidl.models")
    for model in (
        CardSemanticOffer,
        DiscoveredFlyer,
        DisplayPriceObservation,
        LidlParseResult,
        PhysicalCard,
        ProductBinding,
        TextSpan,
        UnresolvedObservation,
    ):
        setattr(module, model.__name__, model)
    return module


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Lidl parser module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if Path(str(module.__file__)).resolve() != path.resolve():
        raise RuntimeError(f"Loaded Lidl parser from the wrong path: {module.__file__}")
    return module


def load_lidl_v631(
    provenance_dir: Path | None = None,
) -> LidlV631Runtime:
    root = (provenance_dir or _default_provenance_dir()).resolve()
    base_path = root / "r61_base.py"
    shadow_path = root / "r61_shadow.py"
    expected = {
        base_path: BASE_SHA256,
        shadow_path: SHADOW_SHA256,
    }
    for path, digest in expected.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = _sha256(path)
        if actual != digest:
            raise RuntimeError(
                f"Lidl V6.3.1 source SHA drift for {path.name}: {actual}"
            )

    import app

    lidl_module = types.ModuleType("app.lidl")
    lidl_module.__path__ = []
    models_module = _models_module()
    lidl_module.models = models_module

    names = ("app.lidl", "app.lidl.models", "app.lidl.r61_base", "app.lidl.r61_shadow")
    previous_modules = {name: sys.modules.get(name) for name in names}
    previous_app_lidl = getattr(app, "lidl", None)
    had_app_lidl = hasattr(app, "lidl")
    try:
        app.lidl = lidl_module
        sys.modules["app.lidl"] = lidl_module
        sys.modules["app.lidl.models"] = models_module
        base = _load_module("app.lidl.r61_base", base_path)
        lidl_module.r61_base = base
        shadow_module = _load_module("app.lidl.r61_shadow", shadow_path)
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        if had_app_lidl:
            app.lidl = previous_app_lidl
        else:
            delattr(app, "lidl")

    if getattr(base, "PARSER_VERSION", None) != "lidl-pdf-v08c-r6":
        raise RuntimeError("Unexpected frozen Lidl base parser version")
    if getattr(shadow_module, "PARSER_VERSION", None) != PARSER_VERSION:
        raise RuntimeError("Unexpected Lidl V6.3.1 shadow parser version")
    return LidlV631Runtime(
        base=base,
        shadow=SemanticGatedShadowRuntime(shadow_module),
        provenance_dir=root,
    )
