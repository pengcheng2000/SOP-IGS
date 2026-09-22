$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "start-word-worker.ps1"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "SOP-IGS Word Worker" -Action $Action -Trigger $Trigger -Settings $Settings -Description "SOP DOCX Word COM finalizer" -Force

