"""Render the distributed live-streaming general architecture diagram.

Faithful recreation of the original (general_architecture_old.png).
Only the Ingest Service and the Worker Pool boxes changed their internal
content; every other component, color and connection is preserved.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# ---- palette (matching the original) -------------------------------------
C_BG = "#15151a"
C_DOCKER = "#243b6b"      # big blue docker-compose container
C_USERS = "#2a1f4d"       # dark purple users container
C_PURPLE = "#4c3d80"      # ingest / frontend / api / chat containers
C_RED = "#c2566a"         # queue / middleware containers
C_TEAL = "#3f9ba0"        # worker pool container
C_ORANGE = "#e0a838"      # storage container
C_NODE = "#1a1a24"        # inner dark node boxes
C_NODE_TEAL = "#2c6f73"   # orchestrator inner node
C_TEXT = "#f2f5fa"
C_SUB = "#cdd6e2"
C_EDGE = "#c4ccd8"
C_DOT = "#e7b6bd"
C_LBL_BG = "#5f5f5f"

fig, ax = plt.subplots(figsize=(19, 12), dpi=110)
fig.patch.set_facecolor(C_BG)
ax.set_facecolor(C_BG)
ax.set_xlim(0, 19)
ax.set_ylim(0, 12)
ax.axis("off")


def container(x, y, w, h, color, title, title_color=C_TEXT, tfs=12):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.10",
            linewidth=1.4, edgecolor="#b9c2d0",
            facecolor=color, alpha=0.55, zorder=2,
        )
    )
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top",
            color=title_color, fontsize=tfs, fontweight="bold", zorder=6)


def node(cx, cy, w, h, text, fc=C_NODE, fs=9.5, weight="normal"):
    ax.add_patch(
        FancyBboxPatch(
            (cx - w / 2, cy - h / 2), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=1.3, edgecolor="#dfe5ee",
            facecolor=fc, alpha=0.98, zorder=4,
        )
    )
    ax.text(cx, cy, text, ha="center", va="center", color=C_TEXT,
            fontsize=fs, fontweight=weight, zorder=5, linespacing=1.35)


def arrow(p1, p2, color=C_EDGE, lw=1.7, ls="-", rad=0.0, style="-|>"):
    ax.add_patch(
        FancyArrowPatch(
            p1, p2, arrowstyle=style, mutation_scale=15,
            linewidth=lw, color=color, linestyle=ls,
            connectionstyle=f"arc3,rad={rad}", zorder=3,
        )
    )


def elabel(x, y, text, fs=8.5, color=C_TEXT):
    ax.text(x, y, text, ha="center", va="center", color=color, fontsize=fs,
            zorder=7, linespacing=1.2,
            bbox=dict(boxstyle="round,pad=0.28", fc=C_LBL_BG, ec="none", alpha=0.92))


# ========================= CONTAINERS =====================================
container(1.2, 0.8, 13.8, 10.2, C_DOCKER, "")
ax.text(8.1, 10.78, "Docker Compose", ha="center", va="top",
        color=C_TEXT, fontsize=13, fontweight="bold", zorder=6)

container(15.5, 4.0, 3.3, 7.3, C_USERS, "Usuários")

# inside docker
container(1.6, 9.0, 3.7, 1.7, C_PURPLE, "Ingest Service")
container(4.2, 5.9, 3.9, 2.7, C_RED, "Fila de Mensagens")
container(1.6, 2.9, 2.3, 2.4, C_PURPLE, "API Service (FastAPI)", tfs=10)
container(4.2, 2.9, 5.0, 2.4, C_TEAL, "Worker Pool Orchestrator", tfs=11)
container(10.0, 2.9, 3.2, 2.4, C_PURPLE, "Chat Service (FastAPI)", tfs=10)
container(1.6, 0.4, 7.6, 2.2, C_ORANGE, "Armazenamento")
container(10.0, 0.4, 3.2, 2.2, C_RED, "Middleware Pub/Sub")

# ========================= NODES ==========================================
# Users
node(17.15, 10.3, 2.3, 0.95, "Streamer\n(OBS Studio)", fs=9.5)
node(17.15, 7.4, 2.5, 0.95, "Espectadores\n(Navegador Web)", fs=9.5)
node(17.15, 5.2, 2.5, 1.3,
     "Frontend\nHTML + JS\nhls.js (player)\nWebSocket (chat)", fs=8.2)

# Ingest Service  (CHANGED)
node(3.45, 9.55, 3.1, 1.05,
     "Ingest Service\nrecebe msg do OBS (token da live)\npublica evento na fila",
     fc=C_NODE, fs=8.6)

# Queue
node(6.15, 6.95, 2.9, 1.7,
     "RabbitMQ (AMQP)\nPUT / GET / NOTIFY\nCap.4: Comunicação\nPersistente\nCap.2: Desacoplamento\nTemporal",
     fs=8.4)

# API
node(2.75, 3.9, 1.9, 1.6,
     "REST API\nGET /lives\nPOST /users\nStateless\nCap.2: SOA", fs=8.2)

# Worker Pool  (CHANGED) -> Orchestrator + dynamic workers
node(5.55, 3.95, 2.05, 1.75,
     "Orchestrator\n• escuta a fila\n• sobe 1 worker/live\n  (imagem base + ENV token)\n• monitora heartbeat\n• mapa worker→token (JSON)",
     fc=C_NODE_TEAL, fs=7.3)
node(7.9, 4.5, 1.75, 0.68, "Worker (live A)\nFFmpeg", fs=7.6)
node(7.9, 3.45, 1.75, 0.68, "Worker (live B)\nFFmpeg", fs=7.6)

# Chat
node(11.6, 3.9, 2.5, 1.55,
     "WebSocket Server\nAsync I/O\nCap.3: Threads\nCap.5: Ordenação NTP", fs=8.2)

# Storage  (CHANGED) -> PostgreSQL primary + replica (redundância / failover)
node(2.7, 1.83, 2.15, 0.72, "PostgreSQL (Primary)\nUsuários, Lives, Metadados", fs=7.2)
node(2.7, 0.92, 2.15, 0.72, "PostgreSQL (Réplica)\nstandby — assume no failover", fs=7.2)
node(7.4, 1.35, 2.1, 1.3, "Volume HLS\n.m3u8 + .ts\nchunks de vídeo", fs=8.4)

# replication / failover link between the two databases
arrow((4.0, 1.7), (4.0, 1.05), color=C_DOT, ls=(0, (3, 2)), lw=1.4, style="<|-|>")
elabel(4.62, 1.38, "replicação\nfailover", fs=6.6, color=C_TEXT)

# Middleware
node(11.6, 1.35, 2.5, 1.55,
     "Redis\nPUBLISH / SUBSCRIBE\nCanal por live\nCap.2: Pub/Sub\nCap.2: Desacoplamento\nReferencial",
     fs=7.9)

# ========================= EDGES ==========================================
# Streamer -> Ingest (RTMP)
arrow((16.0, 10.35), (5.05, 9.85), rad=-0.16)
elabel(10.4, 11.05, "RTMP (TCP/Socket)\nComunicação Transiente")

# Ingest -> Queue (publish token)  (CHANGED label: ingest behavior)
arrow((3.9, 9.02), (5.5, 8.6), rad=-0.12)
elabel(4.45, 8.95, "publica evento\n(token da live)")

# Ingest -> API (Notifica nova live)
arrow((2.55, 9.02), (2.7, 5.32), rad=0.0)
elabel(2.35, 7.15, "Notifica\nnova live")

# Queue -> Orchestrator (consume)
arrow((6.0, 5.88), (5.55, 4.85), rad=0.05)
elabel(5.5, 5.55, "GET (consume)\nescuta a fila")

# Orchestrator -> workers (spawn)
arrow((6.6, 4.5), (7.0, 4.5), color="#ffd27a")
arrow((6.6, 3.7), (7.0, 3.45), color="#ffd27a")
elabel(6.79, 4.62, "spawn", fs=7.0, color=C_TEXT)

# workers -> orchestrator (heartbeat / ack)  -> respawn
arrow((7.0, 4.25), (6.6, 4.1), color=C_DOT, ls=(0, (3, 2)), lw=1.3)
arrow((7.0, 3.25), (6.6, 3.4), color=C_DOT, ls=(0, (3, 2)), lw=1.3)
elabel(7.75, 2.78, "heartbeat — sem ACK → respawn", fs=7.3, color=C_TEXT)

# workers -> Volume HLS
arrow((7.7, 4.16), (7.2, 2.02), rad=0.08)
arrow((8.0, 3.11), (7.6, 2.02), rad=0.05)
elabel(8.55, 2.5, "Gera HLS\n.m3u8/.ts")

# API -> PostgreSQL
arrow((2.8, 2.88), (2.75, 2.22), rad=0.0)
elabel(2.5, 2.5, "CRUD")

# Espectadores -> API (HTTP GET /lives)
arrow((15.85, 7.65), (3.9, 4.55), rad=0.14)
elabel(11.7, 7.5, "HTTP GET /lives")

# Espectadores -> Volume HLS (HTTP GET .m3u8)
arrow((15.85, 7.15), (8.5, 1.7), rad=0.18)
elabel(9.7, 3.05, "HTTP GET .m3u8")

# Frontend <-> Espectadores  (internal, short)
arrow((17.15, 5.85), (17.15, 6.92))
elabel(18.15, 6.35, "Serve\nHTML/JS", fs=7.6)

# Chat <-> Redis
arrow((11.2, 3.12), (11.2, 2.12))
elabel(10.85, 2.48, "PUBLISH msg")
arrow((12.0, 2.12), (12.0, 3.12))
elabel(12.5, 2.48, "SUBSCRIBE canal")

# Espectadores <-> Chat
arrow((15.85, 7.55), (13.22, 4.45), rad=0.16)
elabel(14.5, 5.7, "WebSocket")
arrow((13.22, 3.95), (15.85, 7.25), rad=0.16)
elabel(14.85, 5.0, "Broadcast WebSocket")

plt.tight_layout()
out = "general_architecture.png"
plt.savefig(out, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.2)
print("saved", out)
