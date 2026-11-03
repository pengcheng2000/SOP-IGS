param(
    [string]$DataRoot = "D:\SOP-IGS-Data",
    [string]$BackupRoot = "D:\SOP-IGS-Backups"
)
$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Destination = Join-Path $BackupRoot $Stamp
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
foreach ($Folder in @("outputs", "originals", "processed", "boost", "cabinet_plan")) {
    $Source = Join-Path $DataRoot $Folder
    if (Test-Path -LiteralPath $Source) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Recurse
    }
}
pg_dump --format=custom --file=(Join-Path $Destination "sop-igs.dump") sop_igs
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed: $LASTEXITCODE" }

