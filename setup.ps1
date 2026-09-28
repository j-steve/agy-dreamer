<#
.SYNOPSIS
    One-click automated setup script for agy-dreamer in Google Antigravity.
.DESCRIPTION
    Scaffolds dreaming directories, registers the dreaming project in Antigravity,
    and configures the nightly-dreaming scheduled sidecar task.
.PARAMETER Cron
    Cron expression for scheduled consolidation (default: "0 3 * * *").
.PARAMETER Bootstrap
    Run cold-start historical memory ingestion immediately.
.EXAMPLE
    .\setup.ps1
.EXAMPLE
    .\setup.ps1 -Bootstrap
#>
[CmdletBinding()]
param(
    [string]$Cron = "0 3 * * *",
    [switch]$Bootstrap
)

$ErrorActionPreference = "Stop"

$setupScript = Join-Path $PSScriptRoot "scripts\setup_dreamer.py"
$pyArgs = @($setupScript, "--cron", $Cron)
if ($Bootstrap) {
    $pyArgs += "--bootstrap"
}

# Run using py launcher or fallback python
if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 @pyArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python @pyArgs
} else {
    Write-Error "Python 3 is required but not found in PATH."
}
