# Install the llm-wiki-toolkit skills into your Claude Code skills directory.
# Re-run after `git pull` to update. Copies skills\*.md and skills\*.py to ~\.claude\skills\.
$ErrorActionPreference = 'Stop'

$src  = Join-Path $PSScriptRoot 'skills'
$dest = Join-Path $HOME '.claude\skills'

New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path (Join-Path $src '*.md'), (Join-Path $src '*.py') -Destination $dest -Force

$count = (Get-ChildItem -Path $src -Include *.md, *.py -Recurse).Count
Write-Host "Installed $count skill files to $dest"
Write-Host "Next: pip install -r requirements.txt   (for the PDF engine)"
