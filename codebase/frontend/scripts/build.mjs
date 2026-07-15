import { cp, mkdir, rm } from "node:fs/promises";


await rm("dist", { recursive: true, force: true });
await mkdir("dist/src", { recursive: true });
await mkdir("dist/vendor", { recursive: true });
await Promise.all([
  cp("index.html", "dist/index.html"),
  cp("styles.css", "dist/styles.css"),
  cp("src", "dist/src", { recursive: true }),
  cp("node_modules/hls.js/dist/hls.min.js", "dist/vendor/hls.min.js"),
]);