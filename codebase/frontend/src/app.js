import { LiveApi } from "./api.js";
import { startCatalogPolling } from "./polling.js";
import { initialState, reduce, selectedLive } from "./state.js";

const baseUrl = document.querySelector('meta[name="bff-base-url"]')?.content ?? "";
const api = new LiveApi({ baseUrl });

const elements = {
  status: document.querySelector("#connection-status"),
  statusLabel: document.querySelector("#connection-label"),
  liveCount: document.querySelector("#live-count"),
  liveList: document.querySelector("#live-list"),
  video: document.querySelector("#video-player"),
  videoEmpty: document.querySelector("#video-empty"),
  liveState: document.querySelector("#live-state"),
  liveTitle: document.querySelector("#live-title"),
  liveDescription: document.querySelector("#live-description"),
  messages: document.querySelector("#messages"),
  chatSequence: document.querySelector("#chat-sequence"),
  chatForm: document.querySelector("#chat-form"),
  chatInput: document.querySelector("#chat-input"),
  chatButton: document.querySelector("#chat-form button"),
};

let state = initialState();
let hls = null;
let socket = null;

function dispatch(action) {
  state = reduce(state, action);
  render();
}

function render() {
  elements.status.dataset.state = state.status;
  elements.statusLabel.textContent =
    state.status === "ready" ? "Conectado" : state.status === "error" ? "Indisponivel" : "Carregando";
  elements.liveCount.textContent = String(state.lives.length);
  renderCatalog();
  renderSelection();
  renderMessages();
}

function renderCatalog() {
  elements.liveList.replaceChildren();
  if (state.status === "error" || state.lives.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-list";
    empty.textContent = state.error || "Nenhuma live no ar";
    elements.liveList.append(empty);
    return;
  }
  for (const live of state.lives) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "live-item";
    button.setAttribute("aria-current", String(live.id === state.selectedLiveId));
    const title = document.createElement("strong");
    title.textContent = live.title;
    const description = document.createElement("span");
    description.textContent = live.description || "Ao vivo";
    button.append(title, description);
    button.addEventListener("click", () => selectLive(live.id));
    elements.liveList.append(button);
  }
}

function renderSelection() {
  const live = selectedLive(state);
  elements.liveTitle.textContent = live?.title ?? "Escolha uma live";
  elements.liveDescription.textContent = live?.description || "O player aparecera aqui.";
  elements.liveState.textContent = live ? "Ao vivo" : "Fora do ar";
  elements.videoEmpty.hidden = Boolean(state.playback);
  const chatEnabled = Boolean(state.playback && socket?.readyState === WebSocket.OPEN);
  elements.chatInput.disabled = !chatEnabled;
  elements.chatButton.disabled = !chatEnabled;
}

function renderMessages() {
  elements.messages.replaceChildren();
  for (const message of state.messages) {
    const item = document.createElement("li");
    item.className = "message";
    const author = document.createElement("strong");
    author.textContent = message.user.display_name;
    item.append(author, document.createTextNode(message.text));
    elements.messages.append(item);
  }
  const sequence = state.messages.at(-1)?.sequence ?? 0;
  elements.chatSequence.textContent = `#${sequence}`;
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

async function selectLive(liveId) {
  closePlayback();
  dispatch({ type: "live.selected", liveId });
  try {
    const playback = await api.createPlaybackSession(liveId);
    dispatch({ type: "playback.loaded", playback });
    attachVideo(playback.manifest_url);
    attachChat(playback);
  } catch (error) {
    dispatch({ type: "catalog.failed", error: error.message });
  }
}

function attachVideo(manifestUrl) {
  if (elements.video.canPlayType("application/vnd.apple.mpegurl")) {
    elements.video.src = manifestUrl;
    return;
  }
  if (window.Hls?.isSupported()) {
    hls = new window.Hls({ liveSyncDurationCount: 3 });
    hls.loadSource(manifestUrl);
    hls.attachMedia(elements.video);
  }
}

function attachChat(playback) {
  const url = new URL(playback.chat_websocket_url);
  url.searchParams.set("user_id", playback.chat_user_id);
  url.searchParams.set("display_name", playback.chat_display_name);
  socket = new WebSocket(url);
  socket.addEventListener("open", render);
  socket.addEventListener("close", render);
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "chat.message.created") {
      dispatch({ type: "chat.message", message });
    }
  });
}

function closePlayback() {
  socket?.close();
  socket = null;
  hls?.destroy();
  hls = null;
  elements.video.removeAttribute("src");
  elements.video.load();
}

elements.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.chatInput.value.trim();
  if (!text || socket?.readyState !== WebSocket.OPEN) return;
  socket.send(
    JSON.stringify({
      type: "chat.message.send",
      client_message_id: crypto.randomUUID(),
      text,
    }),
  );
  elements.chatInput.value = "";
});

async function loadCatalog({ silent = false } = {}) {
  if (!silent) dispatch({ type: "catalog.loading" });
  try {
    dispatch({ type: "catalog.loaded", lives: await api.listLives() });
  } catch (error) {
    if (!silent) dispatch({ type: "catalog.failed", error: error.message });
  }
}

loadCatalog();
startCatalogPolling(loadCatalog);