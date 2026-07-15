import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


test("frontend loads hls.js locally and never reads tokens from storage", async () => {
  const [html, app] = await Promise.all([
    readFile(new URL("../index.html", import.meta.url), "utf8"),
    readFile(new URL("../src/app.js", import.meta.url), "utf8"),
  ]);

  assert.match(html, /src="\/vendor\/hls\.min\.js"/);
  assert.doesNotMatch(html, /https?:\/\//);
  assert.doesNotMatch(app, /localStorage|sessionStorage/);
});


test("nginx applies a self-only script policy", async () => {
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");

  assert.match(nginx, /script-src 'self'/);
  assert.match(nginx, /frame-ancestors 'none'/);
  assert.match(nginx, /X-Content-Type-Options/);
});


test("nginx proxies API HLS and WebSocket traffic to backend components", async () => {
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");

  assert.match(nginx, /location \/api\/[^]*proxy_pass http:\/\/bff:8000/);
  assert.match(nginx, /location \/hls\/[^]*proxy_pass http:\/\/hls-origin:8080/);
  assert.match(nginx, /location \/ws\/[^]*proxy_pass http:\/\/chat-service:8000/);
  assert.match(nginx, /proxy_set_header Upgrade \$http_upgrade/);
});