export function startCatalogPolling(
  loadCatalog,
  { intervalMs = 5000, setIntervalImpl = globalThis.setInterval } = {},
) {
  if (typeof loadCatalog !== "function" || typeof setIntervalImpl !== "function") {
    throw new TypeError("Polling requires a catalog loader and timer implementation");
  }
  return setIntervalImpl(() => loadCatalog({ silent: true }), intervalMs);
}