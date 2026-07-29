from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import importlib.util
from pathlib import Path
import sys
import types
from typing import Any


FROZEN_PATH = Path(__file__).with_name("r61_base.py")
FROZEN_SHA256 = "55b403e1b23eb3bce5eb67e2d1665b47be7bf4d5e8ea109234f9c317a77518a2"


def _stub_modules() -> tuple[dict[str, types.ModuleType], type[Any], type[Any]]:
    app = types.ModuleType("app")
    app.__path__ = []
    lidl = types.ModuleType("app.lidl")
    lidl.__path__ = []
    models = types.ModuleType("app.lidl.models")
    schemas = types.ModuleType("app.schemas")

    app.lidl = lidl
    lidl.models = models
    app.schemas = schemas

    @dataclass(frozen=True)
    class TextSpan:
        page: int
        bbox: tuple[float, float, float, float]
        text: str
        font: str
        size: float
        flags: int = 0

    @dataclass(frozen=True)
    class DisplayPriceObservation:
        page: int
        bbox: tuple[float, float, float, float]
        text: str
        price_eur: str
        font: str
        size: float

    models.TextSpan = TextSpan
    models.DisplayPriceObservation = DisplayPriceObservation

    for name in (
        "CardSemanticOffer",
        "DiscoveredFlyer",
        "LidlParseResult",
        "PhysicalCard",
        "ProductBinding",
        "UnresolvedObservation",
    ):
        setattr(models, name, type(name, (), {}))

    class OfferCandidate:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class SourceChain(str, Enum):
        LIDL = "lidl"

    schemas.OfferCandidate = OfferCandidate
    schemas.SourceChain = SourceChain

    modules = {
        "app": app,
        "app.lidl": lidl,
        "app.lidl.models": models,
        "app.schemas": schemas,
    }
    return modules, TextSpan, DisplayPriceObservation


def load_frozen_r61():
    digest = hashlib.sha256(FROZEN_PATH.read_bytes()).hexdigest()
    if digest != FROZEN_SHA256:
        raise RuntimeError(f"frozen R6.1 SHA drift: {digest}")

    stubs, text_span, display_price = _stub_modules()
    previous = {name: sys.modules.get(name) for name in stubs}

    try:
        sys.modules.update(stubs)
        spec = importlib.util.spec_from_file_location(
            "hermes_frozen_r61_base_exact",
            FROZEN_PATH,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot create frozen R6.1 import spec")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old

    if Path(module.__file__).resolve() != FROZEN_PATH.resolve():
        raise RuntimeError(f"wrong frozen module loaded: {module.__file__}")
    return module, text_span, display_price
