from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "tools" / "runner" / "w4c" / "http_header_contract.py"


def _headers(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "headers.txt"
    path.write_bytes(text.replace("\n", "\r\n").encode("iso-8859-1"))
    return path


def _run(path: Path, check: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(path), check],
        check=False,
        capture_output=True,
        text=True,
    )


def test_w4c_header_checker_accepts_exact_w4b_and_w4c_cache_semantics(
    tmp_path: Path,
) -> None:
    w4b = _headers(
        tmp_path,
        "HTTP/1.1 200 OK\n"
        "X-Hermes-UI-Asset-Mode: hashed-w4\n"
        "Cache-Control: no-store\n\n",
    )
    assert _run(w4b, "mode-hashed-w4").returncode == 0
    assert _run(w4b, "cache-w4b").returncode == 0

    html = _headers(
        tmp_path,
        "HTTP/1.1 200 OK\n"
        "X-Hermes-UI-Asset-Mode: hashed-w4\n"
        "Cache-Control: NO-CACHE\n\n",
    )
    assert _run(html, "cache-html-w4c").returncode == 0

    asset = _headers(
        tmp_path,
        "HTTP/1.1 200 OK\n"
        "Content-Type: application/javascript; charset=utf-8\n"
        "Cache-Control: public, max-age=31536000\n"
        "Cache-Control: immutable\n\n",
    )
    assert _run(asset, "mime-js").returncode == 0
    assert _run(asset, "cache-asset-w4c").returncode == 0


def test_w4c_header_checker_uses_final_response_block(tmp_path: Path) -> None:
    headers = _headers(
        tmp_path,
        "HTTP/1.1 100 Continue\n"
        "Cache-Control: no-store\n\n"
        "HTTP/1.1 200 OK\n"
        "Cache-Control: no-cache\n\n",
    )
    assert _run(headers, "cache-html-w4c").returncode == 0
    assert _run(headers, "cache-w4b").returncode != 0


def test_w4c_header_checker_rejects_weakened_or_conflicting_cache_policy(
    tmp_path: Path,
) -> None:
    cases = [
        (
            "HTTP/1.1 200 OK\nCache-Control: no-cache, immutable\n\n",
            "cache-html-w4c",
        ),
        (
            "HTTP/1.1 200 OK\n"
            "Cache-Control: public, max-age=3600, immutable\n\n",
            "cache-asset-w4c",
        ),
        (
            "HTTP/1.1 200 OK\n"
            "Cache-Control: public, max-age=31536000, immutable, no-store\n\n",
            "cache-asset-w4c",
        ),
        (
            "HTTP/1.1 200 OK\nCache-Control: no-store, no-store\n\n",
            "cache-w4b",
        ),
    ]
    for index, (text, check) in enumerate(cases):
        path = tmp_path / f"bad-{index}.headers"
        path.write_bytes(text.replace("\n", "\r\n").encode("iso-8859-1"))
        assert _run(path, check).returncode != 0


def test_w4c_header_checker_rejects_folded_and_duplicate_mode_headers(
    tmp_path: Path,
) -> None:
    folded = _headers(
        tmp_path,
        "HTTP/1.1 200 OK\nCache-Control: public,\n immutable\n\n",
    )
    assert _run(folded, "cache-asset-w4c").returncode != 0

    duplicate = _headers(
        tmp_path,
        "HTTP/1.1 200 OK\n"
        "X-Hermes-UI-Asset-Mode: hashed-w4\n"
        "X-Hermes-UI-Asset-Mode: hashed-w4\n\n",
    )
    assert _run(duplicate, "mode-hashed-w4").returncode != 0
