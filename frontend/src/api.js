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
        if (Array.isArray(data.detail)) {
          // Pydantic validation error array
          errorDetail = data.detail.map((d) => d.msg || d.detail || JSON.stringify(d)).join(". ");
        } else {
          errorDetail = data.detail;
        }
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
 * Authenticate user and receive JWT access token
 */
export async function loginUser(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username: username.trim(),
      password,
    }),
  });
  return handleResponse(res);
}

/**
 * Register a new regular user (always role='user')
 */
export async function registerUser(username, email, password) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username: username.trim(),
      email: email.trim(),
      password,
    }),
  });
  return handleResponse(res);
}

/**
 * Fetch current inverted index status (public endpoint)
 */
export async function fetchIndexStatus() {
  const res = await fetch(`${API_BASE}/index/status`);
  return handleResponse(res);
}

/**
 * Trigger persistent inverted index build / rebuild (admin-only endpoint)
 * Must provide the JWT access token in the Authorization header.
 */
export async function triggerBuildIndex(token) {
  const headers = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}/index/build`, {
    method: "POST",
    headers,
  });
  return handleResponse(res);
}

/**
 * Search patents by keyword or phrase using persistent inverted index (public endpoint)
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
