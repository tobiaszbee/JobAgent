# setup_scheduler.ps1
# Registers a daily Windows Task Scheduler task that runs the full JobAgent pipeline.
#
# Usage (run once from the project root):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1 -Time "09:00" -Days 3
#
# The task runs as the current user, only when logged in (required — Chrome needs a display).
# Logs are written to data\logs\scheduler.log inside the project directory.

param(
    [string]$Time        = "07:30",   # Scheduled start — script adds random delay up to +90 min
    [int]   $Days        = 1,         # --days argument passed to run_all.py
    [int]   $MaxJobs     = 0,         # --max-jobs (0 = unlimited)
    [int]   $RandomStart = 5400,      # Max random startup delay in seconds (default 90 min)
    [string]$TaskName    = "JobAgent"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python      = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Script      = Join-Path $ProjectRoot "scripts\run_all.py"
$LogFile     = Join-Path $ProjectRoot "data\logs\scheduler.log"

if (-not (Test-Path $Python)) {
    Write-Error "Python not found at: $Python`nMake sure the virtual environment exists (.venv)."
    exit 1
}

$Arguments = "`"$Script`" --days $Days --log-file `"$LogFile`" --random-start $RandomStart"
if ($MaxJobs -gt 0) {
    $Arguments += " --max-jobs $MaxJobs"
}

$Action  = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# Run as current user, only when logged in (Chrome requires a session/display)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $Action `
    -Trigger   $Trigger `
    -Settings  $Settings `
    -Principal $Principal `
    -Description "JobAgent daily pipeline: collect LinkedIn jobs and score with Claude"

Write-Host ""
Write-Host "Task '$TaskName' registered successfully."
Write-Host "  Schedule : daily at $Time + random 0-$($RandomStart/60)min delay"
$EndTime = ([datetime]::ParseExact($Time,'HH:mm',$null)).AddSeconds($RandomStart).ToString('HH:mm')
Write-Host "  Effective window: $Time - $EndTime"
Write-Host "  Days back: $Days"
Write-Host "  Log file : $LogFile"
Write-Host ""
Write-Host "To run immediately:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To remove:           Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
