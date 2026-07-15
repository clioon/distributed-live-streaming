import assert from "node:assert/strict";
import test from "node:test";

import { LiveApi } from "../src/api.js";


test("fetch implementation keeps the global receiver expected by browsers", async () => {
  let receiver;
  const api = new LiveApi({
    fetchImpl: async function () {
      receiver = this;
      return { ok: true, json: async () => [] };
    },
  });

  await api.listLives();

  assert.equal(receiver, globalThis);
});


test("catalog request uses the public BFF route", async () => {
  const requests = [];
  const api = new LiveApi({
    baseUrl: "https://stream.example/",
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => [{ id: "live-1" }] };
    },
  });

  const lives = await api.listLives();

  assert.deepEqual(lives, [{ id: "live-1" }]);
  assert.equal(requests[0].url, "https://stream.example/api/v1/lives");
  assert.equal(requests[0].options.method, "GET");
});


test("playback session does not require browser credentials", async () => {
  const requests = [];
  const api = new LiveApi({
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => ({ live_id: "live-1" }) };
    },
  });

  await api.createPlaybackSession("live/unsafe id");

  assert.equal(
    requests[0].url,
    "/api/v1/lives/live%2Funsafe%20id/playback-session",
  );
  assert.equal(requests[0].options.credentials, undefined);
});


test("BFF errors are surfaced with their detail", async () => {
  const api = new LiveApi({
    fetchImpl: async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Live playback is not ready" }),
    }),
  });

  await assert.rejects(
    () => api.createPlaybackSession("live-1"),
    /Live playback is not ready/,
  );
});