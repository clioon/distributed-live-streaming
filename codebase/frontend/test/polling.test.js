import assert from "node:assert/strict";
import test from "node:test";

import { startCatalogPolling } from "../src/polling.js";


test("catalog polling refreshes silently every five seconds", async () => {
  let scheduled;
  let delay;
  const calls = [];
  const timerId = startCatalogPolling(
    async (options) => calls.push(options),
    {
      setIntervalImpl: (callback, milliseconds) => {
        scheduled = callback;
        delay = milliseconds;
        return 17;
      },
    },
  );

  await scheduled();

  assert.equal(timerId, 17);
  assert.equal(delay, 5000);
  assert.deepEqual(calls, [{ silent: true }]);
});