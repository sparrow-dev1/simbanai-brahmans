param([int]$Port = 5000, [string]$ListenAddress = '127.0.0.1')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$databaseConfig = Join-Path $PSScriptRoot 'instance/deployment.json'
if (Test-Path -LiteralPath $databaseConfig) {
    $databaseSettings = Get-Content -LiteralPath $databaseConfig -Raw | ConvertFrom-Json
    if (-not $databaseSettings.DATABASE_URL) { throw 'Deployment configuration requires DATABASE_URL.' }
    $env:DATABASE_URL = $databaseSettings.DATABASE_URL
}
$runtimePath = Join-Path $PSScriptRoot '.runtime'
if (Test-Path -LiteralPath $runtimePath) {
    $env:PYTHONPATH = $runtimePath + [IO.Path]::PathSeparator + $env:PYTHONPATH
}
$pythonExecutable = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { $pythonExecutable = 'python' }
Write-Host "Simbanai Brahmans: http://${ListenAddress}:$Port"
& $pythonExecutable serve.py --host $ListenAddress --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Server could not start. Install requirements.txt and check the database configuration.' }
