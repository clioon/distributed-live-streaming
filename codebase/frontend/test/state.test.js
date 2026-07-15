import assert from "node:assert/strict";
import test from "node:test";

import { initialState, reduce, selectedLive } from "../src/state.js";


const live = { id: "live-1", title: "Lecture", description: "Systems" };


test("catalog refresh clears a selection that no longer exists", () => {
  let state = reduce(initialState(), { type: "catalog.loaded", lives: [live] });
  state = reduce(state, { type: "live.selected", liveId: live.id });
  state = reduce(state, { type: "catalog.loaded", lives: [] });

  assert.equal(state.selectedLiveId, null);
  assert.equal(selectedLive(state), null);
});


test("playback response from an old selection is ignored", () => {
  let state = reduce(initialState(), { type: "catalog.loaded", lives: [live] });
  state = reduce(state, { type: "live.selected", liveId: live.id });

  state = reduce(state, {
    type: "playback.loaded",
    playback: { live_id: "other-live", manifest_url: "stale" },
  });

  assert.equal(state.playback, null);
});


test("chat messages are deduplicated and ordered by server sequence", () => {
  let state = reduce(initialState(), { type: "catalog.loaded", lives: [live] });
  state = reduce(state, { type: "live.selected", liveId: live.id });
  const second = { live_id: live.id, message_id: "m2", sequence: 2 };
  const first = { live_id: live.id, message_id: "m1", sequence: 1 };

  state = reduce(state, { type: "chat.message", message: second });
  state = reduce(state, { type: "chat.message", message: first });
  state = reduce(state, { type: "chat.message", message: first });

  assert.deepEqual(state.messages.map((message) => message.message_id), ["m1", "m2"]);
});


test("messages from another live do not enter the selected chat", () => {
  let state = reduce(initialState(), { type: "catalog.loaded", lives: [live] });
  state = reduce(state, { type: "live.selected", liveId: live.id });

  const unchanged = reduce(state, {
    type: "chat.message",
    message: { live_id: "other-live", message_id: "m1", sequence: 1 },
  });

  assert.equal(unchanged, state);
});