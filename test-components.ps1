param(
    [Parameter(Mandatory = $true)]
    [string]$Python
)

$ErrorActionPreference = "Stop"
$componentRoot = Join-Path $PSScriptRoot "codebase"
$pythonComponents = @(
    "api-service",
    "ingest-service",
    "worker",
    "worker-pool-orchestrator",
    "chat-service",
    "bff",
    "healthcheck",
    "message-broker",
    "redis-pubsub",
    "postgres-ha",
    "hls-volume"
)

foreach ($component in $pythonComponents) {
    Push-Location (Join-Path $componentRoot $component)
    try {
        & $Python -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed for $component"
        }
        Write-Host "PASS $component"
    }
    finally {
        Pop-Location
    }
}

Push-Location (Join-Path $componentRoot "frontend")
try {
    npm test
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed for frontend"
    }
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed for frontend"
    }
    Write-Host "PASS frontend"
}
finally {
    Pop-Location
}