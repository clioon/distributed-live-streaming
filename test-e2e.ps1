param(
    [string]$ComposeFile = (Join-Path $PSScriptRoot "codebase/docker-compose.yml")
)

$ErrorActionPreference = "Stop"
$publisherName = "distributed-live-e2e-publisher"
$liveId = $null

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

try {
    docker compose -f $ComposeFile up -d --wait
    if ($LASTEXITCODE -ne 0) {
        throw "Compose stack did not become healthy"
    }

    docker rm -f $publisherName 2>$null | Out-Null
    $request = @{
        title = "Automated E2E Live"
        description = "RTMP, HLS and chat smoke test"
    } | ConvertTo-Json
    $created = Invoke-RestMethod `
        -Method Post `
        -Uri "http://localhost:8080/api/v1/lives" `
        -ContentType "application/json" `
        -Body $request
    $liveId = $created.live.id

    $eventSince = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    docker run `
        -d `
        --name $publisherName `
        --network distributed-live-streaming-network `
        --entrypoint ffmpeg `
        distributed-live-streaming-worker:local `
        -hide_banner `
        -loglevel warning `
        -re `
        -f lavfi `
        -i "testsrc2=size=640x360:rate=30" `
        -f lavfi `
        -i "sine=frequency=700:sample_rate=48000" `
        -t 35 `
        -c:v libx264 `
        -preset ultrafast `
        -tune zerolatency `
        -pix_fmt yuv420p `
        -c:a aac `
        -f flv `
        "rtmp://ingest-service:1935/live/$($created.stream_key)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not start RTMP publisher"
    }

    $eventUntil = [DateTimeOffset]::UtcNow.AddSeconds(45).ToUnixTimeSeconds()
    $healthyEvent = docker events `
        --since $eventSince `
        --until $eventUntil `
        --filter type=container `
        --filter event=health_status `
        --filter "label=streaming.live_id=$liveId" `
        --format '{{.Action}}|{{.Actor.Attributes.name}}' |
        Where-Object { $_ -like "health_status: healthy*" } |
        Select-Object -First 1
    Assert-True ([bool]$healthyEvent) "Worker did not become healthy"

    $live = Invoke-RestMethod -Uri "http://localhost:8080/api/v1/lives/$liveId"
    Assert-True ($live.status -eq "live") "Live did not reach live status"

    $playback = Invoke-RestMethod `
        -Method Post `
        -Uri "http://localhost:8080/api/v1/lives/$liveId/playback-session"
    $manifest = Invoke-WebRequest -Uri $playback.manifest_url -UseBasicParsing
    Assert-True ($manifest.StatusCode -eq 200) "HLS manifest was not served"
    $manifestText = [Text.Encoding]::UTF8.GetString($manifest.Content)
    $segment = [regex]::Match($manifestText, 'segment_[0-9]{6}\.ts').Value
    Assert-True ([bool]$segment) "HLS manifest did not contain a segment"
    $segmentResponse = Invoke-WebRequest `
        -Uri "http://localhost:8080/hls/$liveId/current/$segment" `
        -UseBasicParsing
    Assert-True ($segmentResponse.StatusCode -eq 200) "HLS segment was not served"
    Assert-True ($segmentResponse.RawContentLength -gt 0) "HLS segment was empty"

    $chatCode = @"
import asyncio
import json
from uuid import uuid4
import websockets

async def main():
    url = "ws://frontend:8080/ws/v1/lives/$($liveId)?user_id=$($playback.chat_user_id)&display_name=E2E"
    async with websockets.connect(url) as socket:
        await socket.send(json.dumps({
            "type": "chat.message.send",
            "client_message_id": str(uuid4()),
            "text": "Automated E2E chat"
        }))
        message = json.loads(await socket.recv())
        assert message["live_id"] == "$liveId"
        assert message["text"] == "Automated E2E chat"
        assert message["sequence"] >= 1

asyncio.run(main())
"@
    docker compose -f $ComposeFile exec -T chat-service python -c $chatCode
    if ($LASTEXITCODE -ne 0) {
        throw "Chat WebSocket smoke test failed"
    }

    $destroySince = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $publisherExit = docker wait $publisherName
    Assert-True ($publisherExit -eq "0") "RTMP publisher exited with $publisherExit"

    $destroyUntil = [DateTimeOffset]::UtcNow.AddSeconds(30).ToUnixTimeSeconds()
    $destroyEvent = docker events `
        --since $destroySince `
        --until $destroyUntil `
        --filter type=container `
        --filter event=destroy `
        --filter "label=streaming.live_id=$liveId" `
        --format '{{.Actor.Attributes.name}}' |
        Select-Object -First 1
    Assert-True ([bool]$destroyEvent) "Worker was not removed after stream end"

    $ended = Invoke-RestMethod -Uri "http://localhost:8080/api/v1/lives/$liveId"
    Assert-True ($ended.status -eq "ended") "Live did not reach ended status"

    Write-Host "PASS E2E live=$liveId worker=$healthyEvent segmentBytes=$($segmentResponse.RawContentLength)"
}
finally {
    docker rm -f $publisherName 2>$null | Out-Null
}
