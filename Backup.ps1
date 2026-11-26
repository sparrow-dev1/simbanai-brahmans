param([string]$Directory = 'backups', [string]$DatabaseConfig = (Join-Path $PSScriptRoot 'instance/deployment.json'))
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath $DatabaseConfig)) { throw 'An explicit deployment database configuration is required; SQLite fallback is not permitted for scheduled backups.' }
$databaseSettings = Get-Content -LiteralPath $DatabaseConfig -Raw | ConvertFrom-Json
if (-not $databaseSettings.DATABASE_URL) { throw 'Deployment configuration must contain DATABASE_URL.' }
$env:DATABASE_URL = $databaseSettings.DATABASE_URL
$runtimePath = Join-Path $PSScriptRoot '.runtime'
if (Test-Path -LiteralPath $runtimePath) { $env:PYTHONPATH = $runtimePath + [IO.Path]::PathSeparator + $env:PYTHONPATH }
$pythonExecutable = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { $pythonExecutable = 'python' }
& $pythonExecutable -m flask --app app backup --directory $Directory
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed. Check the selected deployment database and backup account permissions.' }
