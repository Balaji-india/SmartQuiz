param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("db", "api", "web", "test")]
    [string]$Target
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$root = Split-Path -Parent $PSScriptRoot
$apiDir = Join-Path $root "api"
$webDir = Join-Path $root "web"
$contractsDir = Join-Path $root "contracts"
$python = Join-Path $apiDir ".venv\Scripts\python.exe"

function Invoke-Step([string]$Dir, [scriptblock]$Step) {
    Push-Location -LiteralPath $Dir
    try {
        & $Step
        if ($LASTEXITCODE -ne 0) { throw "Step failed with exit code $LASTEXITCODE in $Dir" }
    }
    finally { Pop-Location }
}

switch ($Target) {
    "db"  { Invoke-Step $root { docker compose up -d db } }
    "api" { Invoke-Step $apiDir { & "$python" -m uvicorn app.main:app --reload --port 8000 } }
    "web" { Invoke-Step $webDir { npm.cmd run dev } }
    "test" {
        Invoke-Step $apiDir { & "$python" -m pytest -q }
        Invoke-Step $contractsDir { npx.cmd hardhat test }
        Invoke-Step $webDir { npm.cmd run build }
    }
}
