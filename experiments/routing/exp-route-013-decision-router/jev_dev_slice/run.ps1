# Jev on the 150 dev-slice records (exp-route-013; owner 2026-11-03 after
# Metis's written OK, Q-55). LIVE and PAID: about 0.01 USD at most.
#
#   powershell -ExecutionPolicy Bypass -File experiments\routing\exp-route-013-decision-router\jev_dev_slice\run.ps1
#
# 1. plan: the upper-bound cost and every blocking reason, no call;
# 2. Jev run: live, run cap 0.05 USD, router.real_data_approved, all three
#    switched on for this step only and off afterwards, even on error. Every
#    call goes through the spend guard and data\spend\ledger.jsonl;
# 3. a content-free CSV of the requests where Jev and the rules differ
#    (reports\routing\dev_slice_v1\jev_vs_rules_differences.csv);
# 4. summary of runs\jev_slice\shadow_jev.json (counts, shares, costs; no text).
# Never opens .env itself.

$ErrorActionPreference = "Continue"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\.."))
$env:PYTHONIOENCODING = "utf-8"
$py = ".venv\Scripts\python.exe"
$out = "runs\jev_slice\shadow_jev.json"
$diff = "reports\routing\dev_slice_v1\jev_vs_rules_differences.csv"
New-Item -ItemType Directory -Force -Path "runs\jev_slice" | Out-Null

Write-Host "`n=== 1. plan (no call) ===" -ForegroundColor Cyan
& $py scripts\evaluate_router_slice.py --backend jev --offline --plan

Write-Host "`n=== 2. Jev on the dev slice (live) ===" -ForegroundColor Cyan
Remove-Item $out -ErrorAction SilentlyContinue
try {
    $env:METIS__LIVE__ENABLED = "true"
    $env:METIS__BUDGET__RUN_CAP = "0.05"
    $env:METIS__ROUTER__REAL_DATA_APPROVED = "true"
    & $py scripts\evaluate_router_slice.py --backend jev --offline --yes --out $out --differences-out $diff | Out-Null
} finally {
    Remove-Item Env:METIS__LIVE__ENABLED -ErrorAction SilentlyContinue
    Remove-Item Env:METIS__BUDGET__RUN_CAP -ErrorAction SilentlyContinue
    Remove-Item Env:METIS__ROUTER__REAL_DATA_APPROVED -ErrorAction SilentlyContinue
}
Write-Host ("switches off afterwards: " + (-not ([bool]$env:METIS__LIVE__ENABLED -or [bool]$env:METIS__ROUTER__REAL_DATA_APPROVED)))

Write-Host "`n=== 3. summary ===" -ForegroundColor Cyan
if (-not (Test-Path $out)) { Write-Host "no result file: the run did not complete (see above)" -ForegroundColor Red; exit 1 }
$r = Get-Content -Raw -Encoding UTF8 $out | ConvertFrom-Json
Write-Host ("Jev cost: {0} USD; versions: {1}; ledger left (run cap): {2}" -f $r.decision_cost_usd, ($r.model_revisions | ConvertTo-Json -Compress), $r.ledger_remaining_usd)
$all = $r.splits.all.balanced
Write-Host ("decisions: {0}; tier mix rules {1} router {2}; agreement {3}" -f ($all.decision_status | ConvertTo-Json -Compress), ($all.tier_mix_rules | ConvertTo-Json -Compress), ($all.tier_mix_router | ConvertTo-Json -Compress), $all.agreement)
foreach ($variant in "logged_tokens", "with_expected_reasoning") {
    foreach ($split in "all", "tune", "check") {
        $c = $r.costs.$variant.$split
        if (-not $c) { continue }
        Write-Host ("cost {0}/{1}: priced {2}/{3}; USD today {4} rules {5} router {6}; router saves {7} vs today, {8} vs rules; moved {9}; router models {10}" -f $variant, $split, $c.priced, $c.records, $c.total_usd.today, $c.total_usd.rules, $c.total_usd.router, $c.router_saving_vs_today_share, $c.router_saving_vs_rules_share, $c.router_moved_from_today, ($c.router_models | ConvertTo-Json -Compress))
    }
}
Write-Host ("skips: " + ($r.skips | ConvertTo-Json -Compress -Depth 5))
foreach ($variant in "logged_tokens", "with_expected_reasoning") {
    $n = $r.net_of_decision_cost.$variant
    if ($n) { Write-Host ("net of Jev's own cost {0}: router incl. decisions {1} USD; saves {2} USD = {3} vs rules, {4} vs today" -f $variant, $n.router_incl_decision_usd, $n.saving_vs_rules_usd, $n.saving_vs_rules_share, $n.saving_vs_today_share) }
}
if (Test-Path $diff) { Write-Host ("differences CSV: {0} rows -> {1}" -f ((Import-Csv $diff | Measure-Object).Count), $diff) }
Write-Host "`nFull result: $out"
