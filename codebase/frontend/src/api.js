export class LiveApi {
  constructor({ baseUrl = "", fetchImpl = globalThis.fetch } = {}) {
    if (typeof fetchImpl !== "function") {
      throw new TypeError("A fetch implementation is required");
    }

    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.fetchImpl = fetchImpl.bind(globalThis);
  }

  async listLives() {
    return this.#request("/api/v1/lives");
  }

  async createLive({ title, description = "" } = {}) {
    return this.#request("/api/v1/lives", {
      method: "POST",
      body: JSON.stringify({ title, description }),
    });
  }

  async createPlaybackSession(liveId) {
    return this.#request(
      `/api/v1/lives/${encodeURIComponent(liveId)}/playback-session`,
      {
        method: "POST",
      }
    );
  }

  async #request(path, { method = "GET", body } = {}) {
    const headers = {
      Accept: "application/json",
    };

    if (body) {
      headers["Content-Type"] = "application/json";
    }

    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      ...(body ? { body } : {}),
    });

    const payload = await response
      .json()
      .catch(() => ({ detail: "Resposta inválida" }));

    if (!response.ok) {
      throw new Error(payload.detail || `Falha HTTP ${response.status}`);
    }

    return payload;
  }
}