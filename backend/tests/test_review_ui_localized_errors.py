from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "app" / "ui" / "review.html"


def test_review_api_failures_are_localized_and_retryable() -> None:
    html = REVIEW.read_text(encoding="utf-8")
    for marker in (
        "class ReviewApiError extends Error",
        "function temporaryReviewApiFailure",
        "function reviewApiError",
        "function reviewErrorMessage",
        "function reviewErrorReference",
        "async function reviewRequest",
        "Serveris īslaicīgi nav sasniedzams. Mēģini vēlreiz pēc brīža.",
        'data-review-retry',
        'role="alert"',
        'reviewRequest("/api/v1/review-items?source_chain=lidl&limit=500"',
        'reviewRequest("/api/v1/review-items/"+encodeURIComponent(id)',
        'const d=await reviewRequest(url,opt,"Darbība neizdevās.")',
    ):
        assert marker in html

    for forbidden in (
        "function detailMessage(detail,fallback)",
        "JSON.stringify(detail)",
        'Neizdevās ielādēt: ${esc(error?.message||String(error))}',
        "throw new Error(detailMessage",
        "showToast(detailMessage",
    ):
        assert forbidden not in html
