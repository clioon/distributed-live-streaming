# Distributed Live Streaming

Plataforma academica distribuida de live streaming. O fluxo integrado recebe RTMP, cria um Worker FFmpeg por live, publica HLS, lista a transmissao no frontend e oferece chat WebSocket com Redis.

## Executar

```powershell
docker compose -f codebase/docker-compose.yml up -d --build --wait
```

Abra `http://localhost:8080`. O frontend e a entrada RTMP sao as interfaces principais.

| Interface | Endereco |
|---|---|
| Frontend, BFF, HLS e WebSocket | `http://localhost:8080` |
| Ingestao OBS | `rtmp://localhost:1935/live` |
| RabbitMQ Management | `http://localhost:15672` (`guest` / `guest`) |
| PostgreSQL write via HAProxy | `localhost:55432` |
| PostgreSQL read via HAProxy | `localhost:55433` |

Crie uma live para obter a chave RTMP:

```powershell
$live = Invoke-RestMethod `
	-Method Post `
	-Uri "http://localhost:8080/api/v1/lives" `
	-ContentType "application/json" `
	-Body '{"title":"Minha live","description":"Teste local"}'
$live
```

No OBS, use o servidor `rtmp://localhost:1935/live` e o valor de `stream_key` retornado pela API.

## Componentes

| Componente | Implementacao integrada |
|---|---|
| API Service | FastAPI, dominio de lives, PostgreSQL e transactional outbox |
| Ingest Service | nginx-rtmp e callback HTTP validado |
| RabbitMQ | Eventos duraveis, quorum queue, retry e DLQ |
| Worker Pool Orchestrator | Consumidor AMQP, reconciliacao e Docker SDK |
| Worker | FFmpeg isolado por live, healthcheck e publicacao HLS atomica |
| Healthcheck | Reinicio do Orchestrator via Docker e reidratacao pelo PostgreSQL |
| PostgreSQL HA | Primary, streaming replica, HAProxy e promocao automatica |
| HLS Volume | Volume nomeado compartilhado e nginx origin |
| Chat Service | FastAPI WebSocket, sequencia e deduplicacao no Redis |
| Redis | Script Lua atomico, Pub/Sub e persistencia AOF |
| BFF | Catalogo, criacao e playback session |
| Frontend | Player hls.js, catalogo e chat responsivo |

## Testes

Testes isolados e build do frontend:

```powershell
./test-components.ps1 -Python "C:/caminho/para/python.exe"
```

Smoke E2E com containers ativos:

```powershell
./test-e2e.ps1
```

O smoke cria uma live, publica video sintetico por RTMP, valida Worker, HLS, BFF, WebSocket/Redis e confirma a remocao do Worker no encerramento.

## Tolerancia A Falhas

- Worker removido: o Orchestrator cria uma geracao nova e preserva a URL HLS.
- Orchestrator parado: o Health Monitor reinicia o container e o estado e reconstruido pelo PostgreSQL.
- PostgreSQL Primary parado: o monitor promove a replica e o HAProxy mantem o endpoint de escrita.

Ao iniciar, o Orchestrator consulta no PostgreSQL as lives em estado operacional e restaura a geracao de cada Worker. Se um Worker saudavel ainda existe, ele e adotado. Se estiver ausente, o Orchestrator cria a proxima geracao sem depender de uma nova mensagem RabbitMQ.

O failover do PostgreSQL e automatico, mas o failback e manual. Depois de um teste destrutivo de promocao, recrie os volumes Primary/Replica para restaurar a topologia original.

## Observacoes

O ambiente usa credenciais locais simples e monta o Docker socket no Orchestrator e no Healthcheck. Essas escolhas atendem ao escopo da disciplina e nao devem ser copiadas para producao.