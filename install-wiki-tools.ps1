# Install / refresh the portable QA cores into ONE wiki's tools/ directory.
#
# Distinct from install.ps1: that one installs SKILLS to ~\.claude\skills (machine-level, once).
# These cores live inside each wiki repo, because they are run from the wiki root and are committed
# with it, so every clone carries its own QA. This script is what keeps those copies from drifting —
# re-run it after `git pull` on the toolkit and every wiki gets the same version from one upstream.
#
#   .\install-wiki-tools.ps1                 # install into the current directory's wiki
#   .\install-wiki-tools.ps1 -WikiRoot D:\path\to\wiki
#   .\install-wiki-tools.ps1 -Check          # report drift, change nothing
#
# It reports per file: NEW / UPDATED (the target had drifted) / unchanged — so an accidental local
# edit surfaces instead of being silently overwritten without mention.
[CmdletBinding()]
param(
    [string]$WikiRoot = (Get-Location).Path,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'

$src = Join-Path $PSScriptRoot 'wiki-tools'
if (-not (Test-Path $src)) { throw "Missing $src - run this from the llm-wiki-toolkit checkout." }

# A wiki is identified the same way the control panel identifies one: the CLAUDE.md schema marker
# plus a wiki/ directory. Refuse anything else rather than scattering tools into a random folder.
if (-not (Test-Path (Join-Path $WikiRoot 'CLAUDE.md')) -or -not (Test-Path (Join-Path $WikiRoot 'wiki'))) {
    throw "$WikiRoot does not look like an llm-wiki (expected CLAUDE.md and wiki\)."
}

$destDir = Join-Path $WikiRoot 'tools'
if (-not $Check) { New-Item -ItemType Directory -Force -Path $destDir | Out-Null }

$new = 0; $updated = 0; $same = 0
foreach ($file in Get-ChildItem -Path $src -Filter *.py) {
    $dest = Join-Path $destDir $file.Name
    if (-not (Test-Path $dest)) {
        if (-not $Check) { Copy-Item $file.FullName $dest -Force }
        Write-Host ("  NEW       {0}" -f $file.Name)
        $new++
        continue
    }
    $a = (Get-FileHash $file.FullName -Algorithm SHA256).Hash
    $b = (Get-FileHash $dest -Algorithm SHA256).Hash
    if ($a -eq $b) {
        Write-Host ("  unchanged {0}" -f $file.Name)
        $same++
    } else {
        if (-not $Check) { Copy-Item $file.FullName $dest -Force }
        Write-Host ("  UPDATED   {0}   (target had drifted from the toolkit version)" -f $file.Name) -ForegroundColor Yellow
        $updated++
    }
}

$verb = if ($Check) { 'would change' } else { 'installed' }
Write-Host ("{0}: {1} new, {2} {3}, {4} already current  ->  {5}" -f $WikiRoot, $new, $updated, $verb, $same, $destDir)
if ($Check -and ($new + $updated) -gt 0) { exit 1 }
