# setup_scheduler.ps1
# Registers Pulse as a Windows Task Scheduler task.
# Run once from an elevated PowerShell session.
#
# Usage:
#   .\setup_scheduler.ps1 -PythonPath "C:\path\to\python.exe" -ProjectRoot "C:\Users\you\projects\Pulse"
#
# The task runs every Sunday at 6:00 PM and delivers the weekly briefing.
# To trigger a manual run without the --send flag, run run_pulse.py directly.

param(
    [Parameter(Mandatory=$true)]
    [string]$PythonPath,

    [Parameter(Mandatory=$true)]
    [string]$ProjectRoot,

    [string]$ConfigFile = "config\pulse_config.yaml",
    [string]$TaskName   = "PulseWeeklyBriefing",
    [int]   $Hour       = 18,   # 6 PM
    [int]   $Minute     = 0
)

$ErrorActionPreference = "Stop"

$entryPoint = Join-Path $ProjectRoot "agent\run_pulse.py"
$configPath = Join-Path $ProjectRoot $ConfigFile
$logFile    = Join-Path $ProjectRoot "logs\scheduler.log"

if (-not (Test-Path $PythonPath))  { throw "Python not found at: $PythonPath" }
if (-not (Test-Path $entryPoint))  { throw "Entry point not found: $entryPoint" }
if (-not (Test-Path $configPath))  { throw "Config not found: $configPath" }

$action  = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$entryPoint`" --config `"$configPath`" --send >> `"$logFile`" 2>&1" `
    -WorkingDirectory $ProjectRoot

# Every Sunday at the configured time
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "$($Hour):$($Minute)"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel  Highest `
    -Force | Out-Null

Write-Host "Task '$TaskName' registered. Next run: Sunday at $($Hour):$($Minute.ToString('D2'))."
Write-Host "Log file: $logFile"
Write-Host ""
Write-Host "To test immediately (no email):"
Write-Host "  $PythonPath `"$entryPoint`" --config `"$configPath`" --dry-run"
