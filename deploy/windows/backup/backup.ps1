param(
    [string]$DataRoot = "D:\SOP-IGS-Data",
    [string]$BackupRoot = "D:\SOP-IGS-Backups"
)
$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Destination = Join-Path $BackupRoot $Stamp
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Copy-Item -LiteralPath (Join-Path $DataRoot "outputs") -Destination $Destination -Recurse
Copy-Item -LiteralPath (Join-Path $DataRoot "originals") -Destination $Destination -Recurse
pg_dump --format=custom --file=(Join-Path $Destination "sop-igs.dump") sop_igs

