param(
    [string]$TaskName = 'Simbanai Brahmans Daily Backup',
    [string]$At = '02:00',
    [string]$DatabaseConfig = (Join-Path $PSScriptRoot 'instance/deployment.json'),
    [Parameter(Mandatory=$true)][PSCredential]$Credential,
    [Parameter(Mandatory=$true)][string]$VerifiedBackup,
    [switch]$PostgresRestoreVerified
)
$ErrorActionPreference = 'Stop'
$backupScript = Join-Path $PSScriptRoot 'Backup.ps1'
if (-not (Test-Path -LiteralPath $backupScript)) { throw 'Backup.ps1 is missing.' }
if (-not (Test-Path -LiteralPath $DatabaseConfig)) { throw 'Explicit deployment database configuration is required.' }
if (-not (Test-Path -LiteralPath $VerifiedBackup)) { throw 'Provide a backup from the selected deployment database.' }
$databaseSettings = Get-Content -LiteralPath $DatabaseConfig -Raw | ConvertFrom-Json
if (-not $databaseSettings.DATABASE_URL) { throw 'Deployment configuration requires DATABASE_URL.' }
$env:DATABASE_URL = $databaseSettings.DATABASE_URL
$runtimePath = Join-Path $PSScriptRoot '.runtime'
if (Test-Path -LiteralPath $runtimePath) { $env:PYTHONPATH = $runtimePath + [IO.Path]::PathSeparator + $env:PYTHONPATH }
$pythonExecutable = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { $pythonExecutable = 'python' }
if ($env:DATABASE_URL -like 'sqlite:*') {
    & $pythonExecutable -m flask --app app verify-sqlite-backup --compare-current $VerifiedBackup
    if ($LASTEXITCODE -ne 0) { throw 'Backup restoration verification failed.' }
} else {
    if (-not $PostgresRestoreVerified) { throw 'Restore this PostgreSQL backup into an isolated database and reconcile it first; explicitly attest with -PostgresRestoreVerified.' }
}
# Confirm the configured database is reachable and create an integrity-checked backup before installation.
& $backupScript -DatabaseConfig $DatabaseConfig
$resolvedConfig = (Resolve-Path -LiteralPath $DatabaseConfig).Path
$powerShellPath = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $backupScript + '" -DatabaseConfig "' + $resolvedConfig + '"'
$action = New-ScheduledTaskAction -Execute $powerShellPath -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$backupPassword = $Credential.GetNetworkCredential().Password
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $Credential.UserName -Password $backupPassword -Description 'Daily Simbanai Brahmans database backup; explicit deployment database' | Out-Null
} finally { $backupPassword = $null }
Write-Host "Scheduled at $At using an explicit unattended identity. Verify execution while logged off and after reboot. Server time zone must be Africa/Harare (UTC+02:00)."
