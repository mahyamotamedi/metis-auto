# Decision router quickstart (Windows first)

Status: **complete through R8** (2026-11-03); the fresh-clone walkthrough was skipped (TODO-19). Inline routing is rules only: THX-01 and Jev are too slow on this machine and network, so they run in shadow and offline evaluation (A-118). The decision router ([ADR-XXXX (system-one-decision-router)](../adr/draft-system-one-decision-router.md)) is being built in phases; this guide grows with it. What works today: the cascade in the pipeline with a fake backend, the frozen dev slice and its replay, and THX-01 (in process) and a local `/v1/systemone` server as backends, with their model files pinned and a latency benchmark. Nothing here changes serving: `router.mode = "off"` is the default.

Commands are PowerShell, run from the repository root (`C:\Users\<you>\Desktop\metis-auto-jev`).

## 1. Install (Python 3.13, python.org build, never conda)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements-db.lock -r runs\win-extra.txt
.venv\Scripts\python -m pip install -e . --no-deps --no-build-isolation
.venv\Scripts\python scripts\fetch_tokenizer_assets.py
.venv\Scripts\python -m pytest -q
```

**Windows lock workaround (TODO-16).** The lock files were compiled on macOS and miss two Windows-only dependencies, so `--require-hashes` fails on a fresh Windows clone. Until the locks are regenerated, create the git-ignored file `runs\win-extra.txt` with exactly these two pins (sha256 from PyPI, checked 2026-11-02; wheel and source archive):

```text
colorama==0.4.6 \
    --hash=sha256:4f1d9991f5acc0ca119f9d443620b77f9d6b33703e51011c16baf57afb285fc6 \
    --hash=sha256:08695f5cb7ed6e0531a20572697297273c47b8cae5a63ffc6d6ed5c201be6e44
tzdata==2026.6 \
    --hash=sha256:0a10eec6e13ef16b627fabed9a5f2ba61a62b1c67f327305f4e7e412a70b4aec \
    --hash=sha256:85d2cd9c09f81f0bb29db27759fc83af4f1e620efb814f8c5bf8b4cc4feece6d
```

Never install without `--require-hashes`. Since main of 2026-11-02, `requirements-dev.lock` and `requirements-router-local.lock` carry both pins with `sys_platform == "win32"` markers, so they need no `win-extra.txt`; the `db`, `compress` and `ui` locks still do (TODO-16 stays open for them).

## 2. Tell the code where the full dataset is (machine-local, never committed)

The repository's `data\full_data\raw` is an NTFS junction to the dataset folder; the default `full_data_root = "data/full_data/raw"` follows it. If your copy lives elsewhere, set it in the git-ignored `config\local.toml`:

```toml
[data]
full_data_root = "C:/Users/<you>/Desktop/metis-data"
```

or for one PowerShell session:

```powershell
$env:METIS__DATA__FULL_DATA_ROOT = "C:\Users\<you>\Desktop\metis-data"
```

## 3. Switch the router mode

`[router] mode` is `off`, `local`, `hosted`, `hybrid_local_first` or `hybrid_hosted_first`. Every backend in the chosen mode's chain must be enabled, or settings refuse to load. For one PowerShell session:

```powershell
$env:METIS__ROUTER__MODE = "local"
$env:METIS__ROUTER__BACKENDS__THX01__ENABLED = "true"
# back to normal:
Remove-Item Env:METIS__ROUTER__MODE, Env:METIS__ROUTER__BACKENDS__THX01__ENABLED
```

`router.real_data_approved` and `router.allow_unpriced` can be set only in `config\local.toml` or an environment variable. **Owner decision (2026-11-02):** `real_data_approved` stays `false`: no dataset text goes to a hosted backend.

## 4. Phases and where they are

| Phase | What you can use |
|---|---|
| R2 | The 150-record dev slice: §5 below and [router_dev_slice_v1.md](../evaluation/router_dev_slice_v1.md) |
| R4 | The cascade in the pipeline and the slice replay: §6 |
| R5 | THX-01 pinned (done 2026-11-03), the local backends and the latency benchmark: §7 |
| R6 | Jev via Metis, the LLM backup, and the live check: §9 |
| R7 | The decision router in `scripts\chat.py` and the demo UI: §10 |
| R8 | The shadow evaluation (exp-route-013): §11 |
| all | One script for every native step: §12 |

## 5. Build the routing dev slice (R2)

Needs the `db` lock (pyarrow) and the dataset path from §2. Prints counts, duration and peak memory only; text goes only to `data\derived\` and `runs\`.

```powershell
.venv\Scripts\python scripts\build_router_dev_slice.py plan     # counts only, no text read
.venv\Scripts\python scripts\build_router_dev_slice.py build    # about a minute or two
.venv\Scripts\python scripts\build_router_dev_slice.py verify   # PASS or FAIL
.venv\Scripts\python scripts\build_router_dev_slice.py report   # regenerate outputs
```

The review sheet for the two reviewers is `runs\routing\dev_slice_v1\review_LOCAL_ONLY.csv` (opens in Excel with Persian text). Import completed labels with `import-labels <file>`.

## 6. Replay the frozen dev slice (R4)

Fakes only: the fake answering client and fake decision backends. No network, no model weights, no key, no spend; the spend ledger is not touched. It first checks that the local records are the committed slice (`fingerprint.json`, `ids.csv`) and refuses otherwise; it never rebuilds the slice.

```powershell
.venv\Scripts\python scripts\replay_router_slice.py
.venv\Scripts\python scripts\replay_router_slice.py --scenario local --profile complex
```

Scenarios: `off` (router off), `local` (a fake local backend, two passes; the second shows router-cache hits), `hosted_refused` (a fake hosted backend first; every dataset state is refused before it because `real_data_approved` is false). It prints counts (decision status, gate rules, paths, tiers, target models, refusals), timings (decision step and request, p50/p95/max in ms) and peak memory: never text. The fake backend answers the same for every state, so the tiers say nothing about accuracy; the timings are the pipeline's own overhead on real Persian text.

## 7. Local router models and the latency benchmark (R5)

**1. Install the extra** (about 147 MB of Windows wheels, torch 2.14.1 being 124 MB; the same torch and transformers pins as the `compress` lock, plus `thx01` 1.0.0; no pin conflicts with the `db` lock, whose packages stay installed):

```powershell
.venv\Scripts\python -m pip install --require-hashes -r requirements-router-local.lock
.venv\Scripts\python -m pip install -e . --no-deps --no-build-isolation
```

`--no-build-isolation` uses the setuptools already installed from the lock, so the editable install never needs the network.

**2. See the download size, then pin** (the project's own network cannot reach the Hugging Face Hub, so the pins are made here, on your machine). THX-01 is the model at the root of `doofz/THX-01` (the multilingual mmBERT model; there is no separate multilingual folder): six files, about 680 MB, of which `model.safetensors` is 644 MB and `tokenizer\tokenizer.json` 34 MB. The repository's demo and training folders are never listed or fetched. `plan` reads the Hub's metadata only and prints every file and its size; nothing is downloaded. If the Hub answers with an error, `plan` prints the URL and the HTTP status. `pin --yes` downloads exactly those files at that commit, checks each one against the Hub's own tree at that commit (the LFS sha256 for large files, the git blob ID for small ones; nothing is trusted on first download), and writes the commit and every file's sha256 into `config\reference\routers.toml`. The previous file is saved under `runs\routers\`. **If your connection drops**, each file is retried up to five times and resumed where it stopped; if `pin` still fails, run the same command again: verified files are kept, and a partial file resumes.

```powershell
.venv\Scripts\python scripts\fetch_router_assets.py plan
.venv\Scripts\python scripts\fetch_router_assets.py pin --yes
.venv\Scripts\python scripts\fetch_router_assets.py check
```

Files go to `data\routers\thx01\<commit>\` (git-ignored); `pin`, `fetch` and `check` print `disk_mb` (about 680). Later, on another machine with the same `routers.toml`, `fetch` downloads the pinned files and checks sha256. At load, THX-01 checks every sha256 again and runs offline from `data\routers\thx01\<commit>.work\`, where only the small files it may rewrite are copied (a few KB) and the weights and tokenizer are hard links to the pinned files, so the weights are never duplicated and its tokenizer-config fix never changes a pinned file (the benchmark's `load` block shows `work_dir_extra_kb`).

**3. Benchmark against the 60 ms p95 budget** (offline; counts, timings and memory only):

```powershell
.venv\Scripts\python scripts\measure_router_overhead.py
.venv\Scripts\python scripts\measure_router_overhead.py --from-slice
.venv\Scripts\python scripts\measure_router_overhead.py --from-slice --threads 2
.venv\Scripts\python scripts\measure_router_overhead.py --from-slice --threads 8
.venv\Scripts\python scripts\measure_router_overhead.py --from-slice --threads 4
.venv\Scripts\python scripts\measure_router_overhead.py --from-slice --max-message-chars 300
.venv\Scripts\python scripts\measure_router_overhead.py --from-slice --state-format json
.venv\Scripts\python scripts\replay_router_slice.py --scenario thx01   # the real THX-01 in the pipeline
```

Add `--out runs\finish_router\<name>.json` to keep a copy of the output. **Decision rule (owner, 2026-11-03):** if any setting gives p95 ≤ 60 ms on `--from-slice`, the best one becomes the default and `local` is the inline mode. Otherwise inline routing is rules only, and THX-01 runs in shadow and offline evaluation (no ONNX conversion now).

The report gives load and sha256 time, latency p50/p90/p95/p99/max overall and by message length, the share over 60 ms, `meets_budget_p95`, the model's input tokens per call (THX-01 runs one sequence per question, five per request), errors by kind, and the share of answers below the confidence gate. If THX-01 misses 60 ms p95: try thread counts and shorter states; then ONNX int8 (built only if needed); else inline routing stays rules only and THX-01 runs in shadow (ADR-XXXX (system-one-decision-router) point 4).

**4. Optional, skipped for now (A-117): Mizan on your own llama-server** (shadow and offline evaluation only, never inline on CPU). The GGUF is about 2.7 GB (model card); `plan` prints the exact size first:

```powershell
.venv\Scripts\python scripts\fetch_router_assets.py plan --asset mizan-1.5-4b-q4-k-m
.venv\Scripts\python scripts\fetch_router_assets.py pin --yes --asset mizan-1.5-4b-q4-k-m
```

Install llama.cpp build b11443 or newer yourself (its Windows release from GitHub), start it on loopback with the pinned file, then benchmark it:

```powershell
llama-server.exe -m data\routers\mizan-1.5-4b-q4-k-m\<commit>\mizan-1.5-4b-Q4_K_M.gguf --host 127.0.0.1 --port 8080
.venv\Scripts\python scripts\measure_router_overhead.py --backend mizan_http --synthetic 50
```

Check the model card for any extra `llama-server` flags. Whether llama-server applies Mizan's fitted calibration is not documented, so the backend reports itself uncalibrated.

## 9. Jev via Metis and the live check (R6)

Jev is a System-One decision model. It is **not** a chat model: it answers routing questions and never answers users ([jev_model_note.md](../references/jev_model_note.md)).

**Before any live call:**
- Check the Metis dashboard.
- Make sure `config\local.toml` has, under its one `[budget]` section, `lifetime_cap = "9.99"`. Main's default is now 20 USD, and 9.99 covers the earlier spend on your old machine.
- Never create or edit `data\spend\ledger.jsonl` by hand.

```powershell
.venv\Scripts\python scripts\router_live_check.py plan
```

`plan` prints each call's upper-bound cost and the total. It makes no call and needs no key.

To run the check (one SYNTHETIC state each to Jev, gpt-4.1-nano, gpt-4o-mini, mimo-v2.5, plus a `json_schema` probe; under 0.05 USD):

```powershell
$env:METIS__LIVE__ENABLED = "true"; $env:METIS__BUDGET__RUN_CAP = "0.05"
.venv\Scripts\python scripts\router_live_check.py run --yes --out runs\finish_router\live_run.json
Remove-Item Env:METIS__LIVE__ENABLED, Env:METIS__BUDGET__RUN_CAP
```

`METIS_API_KEY` comes from your `.env`; without it the run is skipped and says so. `diagnose` (same switches) makes at most three tiny SYNTHETIC calls: two to `mimo-v2.5`, to tell a request-format problem from a retired model, and the `json_schema` probe on gpt-4o-mini. To use Jev in a run, set `[router.backends.jev_metis] enabled = true` and a hosted or hybrid mode. Hosted backends never receive dataset text (`real_data_approved` stays false).

## 10. The decision router in the chat and the demo UI (R7)

```powershell
.venv\Scripts\python scripts\chat.py --fake --mode decision_router --router-mode local
.venv\Scripts\python scripts\demo_ui.py   # Routing: "Decision router", then "Decision backends"
```

`--router-mode` is `off` (rules only), `local` (THX-01), `hosted` (Jev; live mode only), `hybrid_local_first` or `hybrid_hosted_first`. Typed messages are your own text. The demo seed is sample content, so hosted backends refuse it. The decision router is a placeholder demo component, not evidence.

## 11. Shadow evaluation on the dev slice (R8, exp-route-013)

```powershell
.venv\Scripts\python scripts\evaluate_router_slice.py --out runs\finish_router\shadow_eval.json
```

The script compares rules only with THX-01 on every frozen slice record. For all records, the tune split and the check split, each balanced and traffic-weighted, and per language group (Persian first), it reports:
- the tier mix and agreement;
- the decision status and the gate's share;
- the share below the confidence gate (mapping questions, Q-61);
- the path mix, confidence, and the decision step's p95.

No labels exist yet, so agreement is not accuracy.

**Use `--offline` for THX-01** (the evaluation mode: 60 s per request, no router cache, the gate off). With the inline settings, THX-01 misses the 60 ms deadline on a CPU, every decision falls back to the rules, and the comparison is the rules against themselves. The offline output adds each question's confidence and probability distribution and the provisional gate proposal.

```powershell
.venv\Scripts\python scripts\evaluate_router_slice.py --offline --out runs\finish_router_2\shadow_offline.json
``` Details: `experiments\routing\exp-route-013-decision-router\README.md`.

## 12. Everything native in one go

```powershell
powershell -ExecutionPolicy Bypass -File runs\finish_router.ps1
```

The script runs these steps in order and keeps going when one fails:
1. tests and ruff;
2. the asset check;
3. every benchmark variant;
4. the THX-01 slice replay;
5. the shadow evaluation;
6. the live check: plan, then run only if `METIS_API_KEY` is set, with live switched off again afterwards.

Each step's content-free output goes to `runs\finish_router\<step>.json`, and a short summary is printed at the end.

The follow-up run (2026-11-03), about 40 minutes, does only what the first run left open: the previously failing tests, the full tests, one benchmark with a per-call breakdown, the offline shadow evaluation, and the live diagnostics.

```powershell
powershell -ExecutionPolicy Bypass -File runs\finish_router_2.ps1
```

## 13. Troubleshooting

- `invalid settings: router.mode = 'local': chain backends not enabled`: enable the backend under `[router.backends.<name>]` or with `METIS__ROUTER__BACKENDS__<NAME>__ENABLED=true`.
- `'router.real_data_approved' may be set only in config/local.toml or an environment override`: approvals are per machine and per run; remove the key from `defaults.toml` or the experiment file.
- **PyPI connections drop** (`SSL: UNEXPECTED_EOF_WHILE_READING`, read timeouts): add `--retries 10 --timeout 60` to the `pip install` command; or use a VPN; or download the failing wheel in a browser into `runs\wheels\` and add `--find-links runs\wheels` (keep `--require-hashes`: pip still checks the wheel against the lock's sha256, so a browser download is as safe as pip's own). Example: `.venv\Scripts\python -m pip install --require-hashes --retries 10 --timeout 60 --find-links runs\wheels -r requirements-router-local.lock -r runs\win-extra.txt`.
- **Hugging Face connections drop during `pin` or `fetch`**: run the same command again; verified files are kept and partial ones resume. A VPN also helps.
- **`plan` prints `"http_status": 404` with a URL**: the repository, revision or folder in `config\reference\routers.toml` does not exist on the Hub; open the URL's repository in a browser and compare.
- `"available": false, "reason": "missing_extra"`: install the `router-local` lock (§7 step 1).
- `"reason": "missing_assets"`: run `fetch_router_assets.py plan` then `pin --yes` (§7 step 2), or `fetch` if `routers.toml` is already pinned. If the `load` block's `detail` says the weights could not be linked, keep `data\routers` on one NTFS volume (the weights are never copied).
- `"reason": "sha_mismatch"`: a pinned file changed on disk; run `fetch_router_assets.py fetch` (it re-downloads and checks).
- `systemone_http serves local models only`: `base_url` must point at `127.0.0.1`, `localhost` or `::1`.
