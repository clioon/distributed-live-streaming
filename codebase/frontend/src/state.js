export function initialState() {
  return {
    status: "idle",
    error: null,
    lives: [],
    selectedLiveId: null,
    playback: null,
    messages: [],
  };
}

export function reduce(state, action) {
  switch (action.type) {
    case "catalog.loading":
      return { ...state, status: "loading", error: null };
    case "catalog.loaded": {
      const lives = [...action.lives];
      const selectedStillExists = lives.some((live) => live.id === state.selectedLiveId);
      return {
        ...state,
        status: "ready",
        lives,
        selectedLiveId: selectedStillExists ? state.selectedLiveId : null,
        playback: selectedStillExists ? state.playback : null,
        messages: selectedStillExists ? state.messages : [],
      };
    }
    case "catalog.failed":
      return { ...state, status: "error", error: action.error };
    case "live.selected":
      return {
        ...state,
        selectedLiveId: action.liveId,
        playback: null,
        messages: [],
      };
    case "playback.loaded":
      if (action.playback.live_id !== state.selectedLiveId) return state;
      return { ...state, playback: action.playback };
    case "chat.message": {
      if (action.message.live_id !== state.selectedLiveId) return state;
      if (state.messages.some((item) => item.message_id === action.message.message_id)) {
        return state;
      }
      const messages = [...state.messages, action.message]
        .sort((left, right) => left.sequence - right.sequence)
        .slice(-200);
      return { ...state, messages };
    }
    default:
      return state;
  }
}

export function selectedLive(state) {
  return state.lives.find((live) => live.id === state.selectedLiveId) ?? null;
}