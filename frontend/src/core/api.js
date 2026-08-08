export class UiApiError extends Error {
  constructor(message, { status = null, errorCode = "", rayId = "", retryable = false, retryAfter = null } = {}) {
    super(message);
    this.name = "UiApiError";
    this.status = status;
    this.errorCode = errorCode;
    this.rayId = rayId;
    this.retryable = retryable;
    this.retryAfter = retryAfter;
  }
}

export function temporaryApiFailure(status, errorCode, retryable) {
  return retryable === true ||
    [502, 503, 504].includes(Number(status)) ||
    ["origin_bad_gateway", "bad_gateway", "service_unavailable", "gateway_timeout"]
      .includes(String(errorCode || "").toLowerCase());
}

export function apiErrorMessage(status, errorCode, retryable) {
  if (temporaryApiFailure(status, errorCode, retryable)) {
    return "Serveris īslaicīgi nav sasniedzams. Mēģini vēlreiz pēc brīža.";
  }
  if (Number(status) === 429) {
    return "Pieprasījumu ir par daudz. Mēģini vēlreiz pēc brīža.";
  }
  return "Datus neizdevās ielādēt.";
}

export function apiErrorReference(error) {
  const parts = [];
  if (Number.isFinite(Number(error?.status)) && Number(error.status) > 0) {
    parts.push(`HTTP ${Number(error.status)}`);
  }
  if (error?.rayId) parts.push(`Ray ID ${String(error.rayId)}`);
  return parts.join(" · ");
}

export async function fetchJson(url, options) {
  const response = await fetch(url, {
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let data = {};
    try {
      data = await response.json();
    } catch {
      // Preserve the current fail-closed behavior when an error body is not JSON.
    }
    const detail = data?.detail && typeof data.detail === "object" ? data.detail : {};
    const status = Number(data?.status || detail.status || response.status) || response.status;
    const errorCode = String(data?.error_code || detail.error_code || data?.error_name || detail.error_name || "");
    const rayId = String(response.headers.get("cf-ray") || data?.ray_id || detail.ray_id || "");
    const retryAfter = response.headers.get("retry-after") || data?.retry_after || detail.retry_after || null;
    const retryable = data?.retryable === true || detail.retryable === true || temporaryApiFailure(status, errorCode, false);
    throw new UiApiError(apiErrorMessage(status, errorCode, retryable), {
      status,
      errorCode,
      rayId,
      retryable,
      retryAfter,
    });
  }
  return response.json();
}
