from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

from starlette.responses import Response

from app.main import app as main_app


INLINE_W3 = "inline-w3"
HASHED_W4 = "hashed-w4"
ALLOWED_UI_ASSET_MODES = frozenset({INLINE_W3, HASHED_W4})
DEFAULT_UI_ASSET_MODE = INLINE_W3
DEFAULT_W4_DIR = Path(__file__).resolve().parent / "ui_w4_shadow"
HASHED_JS = re.compile(r"assets/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.js")
HASHED_CSS = re.compile(r"assets/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.css")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


class UiAssetRuntimeError(RuntimeError):
    """Raised when the selected UI serving mode cannot be proven safe."""


def resolve_ui_asset_mode(value: str | None = None) -> str:
    candidate = (
        value
        if value is not None
        else os.getenv("HERMES_UI_ASSET_MODE", DEFAULT_UI_ASSET_MODE)
    ).strip()
    if candidate not in ALLOWED_UI_ASSET_MODES:
        allowed = ",".join(sorted(ALLOWED_UI_ASSET_MODES))
        raise UiAssetRuntimeError(
            f"invalid HERMES_UI_ASSET_MODE={candidate!r}; allowed={allowed}"
        )
    return candidate


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _required_file(root: Path, relative: str, *, label: str) -> Path:
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise UiAssetRuntimeError(f"{label} is missing or unsafe: {relative}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise UiAssetRuntimeError(f"{label} escapes W4 package root: {relative}") from exc
    return resolved


def _package_item(
    package: dict[str, Any],
    key: str,
    *,
    expected_path: str | None = None,
    path_pattern: re.Pattern[str] | None = None,
) -> tuple[str, int, str]:
    item = package.get(key)
    if not isinstance(item, dict):
        raise UiAssetRuntimeError(f"W4 package is missing {key}")
    path = item.get("path")
    byte_count = item.get("bytes")
    digest = item.get("sha256")
    if not isinstance(path, str) or not isinstance(byte_count, int) or byte_count < 0:
        raise UiAssetRuntimeError(f"W4 package has invalid {key} metadata")
    if not isinstance(digest, str) or HEX_SHA256.fullmatch(digest) is None:
        raise UiAssetRuntimeError(f"W4 package has invalid {key} SHA256")
    if expected_path is not None and path != expected_path:
        raise UiAssetRuntimeError(f"W4 package has unexpected {key} path")
    if path_pattern is not None and path_pattern.fullmatch(path) is None:
        raise UiAssetRuntimeError(f"W4 package has unsafe {key} path")
    return path, byte_count, digest


def _verified_payload(
    root: Path,
    relative: str,
    expected_bytes: int,
    expected_sha256: str,
    *,
    label: str,
) -> bytes:
    path = _required_file(root, relative, label=label)
    payload = path.read_bytes()
    if len(payload) != expected_bytes or _sha(payload) != expected_sha256:
        raise UiAssetRuntimeError(f"W4 package integrity mismatch for {label}")
    return payload


class UiAssetModeApp:
    """ASGI boundary that adds an explicit, reversible W4 serving mode.

    The wrapped FastAPI application remains authoritative for every path except
    `/ui` and the exact manifest-proven `/ui/assets/*` files while hashed W4 is
    explicitly selected. The default inline W3 behavior therefore remains the
    same-image rollback path.
    """

    def __init__(
        self,
        wrapped_app: Any,
        *,
        mode: str | None = None,
        shadow_dir: Path | None = None,
    ) -> None:
        self.wrapped_app = wrapped_app
        self.mode = resolve_ui_asset_mode(mode)
        self.shadow_dir = (shadow_dir or DEFAULT_W4_DIR).resolve()
        self._shadow_html: bytes | None = None
        self._assets: dict[str, tuple[bytes, str]] = {}
        if self.mode == HASHED_W4:
            self._load_verified_w4_package()

    def _load_verified_w4_package(self) -> None:
        root = self.shadow_dir
        if root.is_symlink() or not root.is_dir():
            raise UiAssetRuntimeError("W4 shadow package directory is missing or unsafe")

        package_path = _required_file(
            root,
            "w4-shadow-package.json",
            label="W4 package evidence",
        )
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UiAssetRuntimeError("W4 package evidence is not valid JSON") from exc
        if not isinstance(package, dict):
            raise UiAssetRuntimeError("W4 package evidence must be an object")
        if package.get("result") != "PASS":
            raise UiAssetRuntimeError("W4 package evidence did not pass")
        if package.get("version") != "w4a-shadow-package-v1":
            raise UiAssetRuntimeError("W4 package evidence version mismatch")
        if package.get("production_inline_bundle_preserved") is not True:
            raise UiAssetRuntimeError("W4 package does not preserve the W3 rollback bundle")

        html_path, html_bytes, html_sha = _package_item(
            package,
            "html",
            expected_path="index.html",
        )
        manifest_path, manifest_bytes, manifest_sha = _package_item(
            package,
            "manifest",
            expected_path=".vite/manifest.json",
        )
        js_path, js_bytes, js_sha = _package_item(
            package,
            "js",
            path_pattern=HASHED_JS,
        )
        css_path, css_bytes, css_sha = _package_item(
            package,
            "css",
            path_pattern=HASHED_CSS,
        )
        if js_path == css_path:
            raise UiAssetRuntimeError("W4 JS and CSS package paths overlap")

        html = _verified_payload(
            root,
            html_path,
            html_bytes,
            html_sha,
            label="W4 HTML",
        )
        _verified_payload(
            root,
            manifest_path,
            manifest_bytes,
            manifest_sha,
            label="W4 manifest",
        )
        js = _verified_payload(
            root,
            js_path,
            js_bytes,
            js_sha,
            label="W4 JavaScript",
        )
        css = _verified_payload(
            root,
            css_path,
            css_bytes,
            css_sha,
            label="W4 CSS",
        )

        try:
            html_text = html.decode("utf-8")
            js_text = js.decode("utf-8")
            css_text = css.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UiAssetRuntimeError("W4 package contains non-UTF-8 UI assets") from exc
        if '<meta name="hermes-w4-shadow" content="hashed-assets-v1">' not in html_text:
            raise UiAssetRuntimeError("W4 HTML marker is missing")
        if html_text.count(f'/ui/{js_path}') != 1:
            raise UiAssetRuntimeError("W4 HTML does not reference the exact packaged JS once")
        if html_text.count(f'/ui/{css_path}') != 1:
            raise UiAssetRuntimeError("W4 HTML does not reference the exact packaged CSS once")
        if "/ui/app.js" in html_text or "/ui/styles.css" in html_text:
            raise UiAssetRuntimeError("W4 HTML still references the W3 asset endpoints")
        if "w3-behavior-preserving-bootstrap-v1" not in js_text:
            raise UiAssetRuntimeError("W4 JavaScript lost the W3 behavior marker")
        if "HERMES_UI_STYLE_OPEN:" not in css_text:
            raise UiAssetRuntimeError("W4 CSS lost the reviewed style marker")

        self._shadow_html = html
        self._assets = {
            f"/ui/{js_path}": (js, "application/javascript"),
            f"/ui/{css_path}": (css, "text/css"),
        }

    async def _respond(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        *,
        payload: bytes,
        content_type: str,
    ) -> None:
        body = payload if scope.get("method") != "HEAD" else b""
        response = Response(
            content=body,
            status_code=200,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-store",
                "X-Hermes-UI-Asset-Mode": self.mode,
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.wrapped_app(scope, receive, send)
            return

        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        if method not in {"GET", "HEAD"}:
            await self.wrapped_app(scope, receive, send)
            return

        if path.startswith("/ui/assets/"):
            if self.mode != HASHED_W4:
                await Response(status_code=404)(scope, receive, send)
                return
            asset = self._assets.get(path)
            if asset is None:
                await Response(status_code=404)(scope, receive, send)
                return
            payload, content_type = asset
            await self._respond(
                scope,
                receive,
                send,
                payload=payload,
                content_type=content_type,
            )
            return

        if path == "/ui" and self.mode == HASHED_W4:
            if self._shadow_html is None:
                raise UiAssetRuntimeError("W4 HTML was not loaded")
            await self._respond(
                scope,
                receive,
                send,
                payload=self._shadow_html,
                content_type="text/html; charset=utf-8",
            )
            return

        await self.wrapped_app(scope, receive, send)


app = UiAssetModeApp(main_app)
