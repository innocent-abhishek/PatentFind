const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

/**
 * Helper to process JSON response or extract meaningful error message
 */
async function handleResponse(res) {
  if (!res.ok) {
    let errorDetail = `Request failed with status ${res.status}`;
    try {
      const data = await res.json();
      if (data && data.detail) {
        errorDetail = data.detail;
      } else if (data && data.message) {
        errorDetail = data.message;
      }
    } catch {
      // response wasn't JSON
    }
    const err = new Error(errorDetail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/**
 * Fetch current inverted index status
 */
export async function fetchIndexStatus() {
  const res = await fetch(`${API_BASE}/index/status`);
  return handleResponse(res);
}

/**
 * Trigger persistent inverted index build / rebuild
 */
export async function triggerBuildIndex() {
  const res = await fetch(`${API_BASE}/index/build`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
  return handleResponse(res);
}

/**
 * Search patents by keyword or phrase using persistent inverted index
 */
export async function searchPatents(query, page = 1, pageSize = 10) {
  const params = new URLSearchParams({
    q: query,
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await fetch(`${API_BASE}/search?${params.toString()}`);
  return handleResponse(res);
}
