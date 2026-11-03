# Decision quality, first signal: rules vs THX-01 vs Jev on 100 SYNTHETIC requests
# with the owner's frozen labels (jev-synth-v1, 2026-11-03).
#
#   powershell -ExecutionPolicy Bypass -File experiments\routing\exp-route-013-decision-router\synthetic_v1\run.ps1
#
# 1. plan: Jev's upper-bound cost for 100 calls vs the 0.02 USD run cap (no call);
# 2. local: rules, plain rule_based, the fast gate, THX-01 (no network; ~10 min);
# 3. Jev live, only if the key is set and the plan fits: live switched on for this
#    step only (run cap 0.02 USD, through the spend guard and data\spend\ledger.jsonl),
#    switched off afterwards even on error (~6 min);
# 4. report: reports\routing\exp-route-013\synthetic_v1\report.md (and report.json);
#    per-row outputs in runs\jev_synth_eval\ (git-ignored). Never opens .env itself.
param([switch]$KeepMarker)

$ErrorActionPreference = "Continue"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\.."))
$env:PYTHONIOENCODING = "utf-8"
$py = ".venv\Scripts\python.exe"
$script = "experiments\routing\exp-route-013-decision-router\synthetic_v1\run.py"
$dir = "runs\jev_synth_eval"
$rep = "reports\routing\exp-route-013\synthetic_v1"
$extra = @(); if ($KeepMarker) { $extra += "--keep-marker" }

Write-Host "`n=== 1. plan (no call) ===" -ForegroundColor Cyan
& $py $script plan @extra
if ($LASTEXITCODE -ne 0) { Write-Host "plan failed; stopping" -ForegroundColor Red; exit 1 }
$plan = Get-Content -Raw -Encoding UTF8 "$dir\plan.json" | ConvertFrom-Json

Write-Host "`n=== 2. rules, rule_based, gate, THX-01 (local) ===" -ForegroundColor Cyan
& $py $script local @extra
if ($LASTEXITCODE -ne 0) { Write-Host "local step failed; stopping" -ForegroundColor Red; exit 1 }

Write-Host "`n=== 3. Jev via Metis (live, SYNTHETIC only) ===" -ForegroundColor Cyan
Remove-Item "$dir\jev.json" -ErrorAction SilentlyContinue
if ($plan.key_set -and $plan.fits) {
    try {
        $env:METIS__LIVE__ENABLED = "true"
        $env:METIS__BUDGET__RUN_CAP = "0.02"
        & $py $script jev --yes @extra
    } finally {
        Remove-Item Env:METIS__LIVE__ENABLED -ErrorAction SilentlyContinue
        Remove-Item Env:METIS__BUDGET__RUN_CAP -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "skipped: key_set=$($plan.key_set) fits=$($plan.fits)" -ForegroundColor Yellow
}
Write-Host ("live switched off afterwards: " + (-not [bool]$env:METIS__LIVE__ENABLED))

Write-Host "`n=== 4. report ===" -ForegroundColor Cyan
& $py $script report
$md = Get-Content -Encoding UTF8 "$rep\report.md"
$md | Select-Object -First 30 | ForEach-Object { Write-Host $_ }
Write-Host "`nFull report: $rep\report.md (and report.json); per-row data: $dir\local.json, $dir\jev.json"
