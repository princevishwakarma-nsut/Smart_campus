const api = {
  baseUrl: CONFIG.API_BASE_URL,

  getToken() {
    return sessionStorage.getItem(CONFIG.STORAGE_TOKEN_KEY);
  },

  setToken(token) {
    sessionStorage.setItem(CONFIG.STORAGE_TOKEN_KEY, token);
  },

  clearToken() {
    sessionStorage.removeItem(CONFIG.STORAGE_TOKEN_KEY);
    sessionStorage.removeItem(CONFIG.STORAGE_USER_KEY);
  },

  async request(endpoint, options = {}) {
    const url = endpoint.startsWith("http") ? endpoint : `${this.baseUrl}${endpoint}`;
    const headers = options.headers || {};
    
    if (!headers["Content-Type"] && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    const token = this.getToken();
    if (token && !endpoint.includes("/auth/login") && !endpoint.includes("/auth/register")) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    options.headers = headers;

    try {
      const response = await fetch(url, options);

      if (response.status === 401) {
        // If login endpoint returns 401, extract server message (e.g. "Incorrect email or password")
        if (url.includes("/auth/login")) {
          const contentType = response.headers.get("content-type");
          let errData = null;
          if (contentType && contentType.includes("application/json")) {
            try { errData = await response.json(); } catch (_) {}
          }
          const msg = errData && errData.detail 
            ? (typeof errData.detail === "string" ? errData.detail : (Array.isArray(errData.detail) ? errData.detail.map(e => e.msg || JSON.stringify(e)).join(", ") : JSON.stringify(errData.detail))) 
            : "Incorrect email or password";
          throw new Error(msg);
        }

        // Token expired or invalid during active authenticated session
        this.clearToken();
        if (typeof setCurrentUser === "function") {
          setCurrentUser(null);
        }
        if (typeof showLoginScreen === "function") {
          showLoginScreen();
        }
        throw new Error("Session expired. Please sign in again.");
      }

      const contentType = response.headers.get("content-type");
      let data = null;
      if (contentType && contentType.includes("application/json")) {
        data = await response.json();
      } else {
        data = await response.text();
      }

      if (!response.ok) {
        let errorMsg = response.statusText;
        if (data && data.detail) {
          if (typeof data.detail === "string") {
            errorMsg = data.detail;
          } else if (Array.isArray(data.detail)) {
            errorMsg = data.detail.map(e => e.msg || JSON.stringify(e)).join(", ");
          } else {
            errorMsg = JSON.stringify(data.detail);
          }
        }
        throw new Error(errorMsg || "Request failed");
      }

      return data;
    } catch (err) {
      console.error(`API Error on ${url}:`, err);
      throw err;
    }
  },

  get(endpoint, params) {
    let url = endpoint;
    if (params) {
      const q = new URLSearchParams(params).toString();
      if (q) url += (url.includes("?") ? "&" : "?") + q;
    }
    return this.request(url, { method: "GET" });
  },

  post(endpoint, body) {
    return this.request(endpoint, {
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body)
    });
  },

  put(endpoint, body) {
    return this.request(endpoint, {
      method: "PUT",
      body: body instanceof FormData ? body : JSON.stringify(body)
    });
  },

  patch(endpoint, body) {
    return this.request(endpoint, {
      method: "PATCH",
      body: body instanceof FormData ? body : JSON.stringify(body)
    });
  },

  delete(endpoint) {
    return this.request(endpoint, { method: "DELETE" });
  }
};

window.api = api;
