# Demo quickstart (for teammates)

A step-by-step guide to running the Metis-Auto demo on your own computer, written for someone new to the project. It takes about 15 minutes. You need no API key to start: the free fake mode works out of the box.

> **Status (2026-10-18).** The command-line chat (`scripts/chat.py`) works today, in fake and real-model mode. The **demo UI** (Streamlit) and its routing, compression, and cache toggles arrive with the **Demo milestone**. Its sections below are marked *(Demo milestone)* and will be completed then; this guide is a required deliverable of that milestone ([progress](../project/progress.md), [owner brief](../project/live_testing_and_demo_brief.md) §10, §12).

Deeper background, if you want it: [local development guide](local_development.md) (setup, configuration, Docker), [configuration.md](../architecture/configuration.md) (all the layers), [ADR-0018](../adr/0018-live-calls-for-development-under-a-lifetime-budget.md) (the budget).

---

## 1. What the demo is and what it shows

Metis-Auto is **cost-reducing middleware** between a chat application and LLM providers. For each message it decides how to answer it as cheaply as possible without hurting quality, and it shows where the money went. The demo is a chat window over the real Metis-Auto pipeline that makes those decisions visible:

| Feature | What you see |
|---|---|
| **Routing** | Which model answered (`served_by`, `model`). Today you pick one fixed model; the Demo milestone adds rule-based and "sticky" routing across the five test models (`gpt-5-nano`, `gpt-4.1-nano`, `gpt-4o-mini`, `deepseek-v4-flash`, `mimo-v2.5`). |
| **Caching** | Repeat a question and it is answered from Metis-Auto's own cache: `served_by: cache`, no model call, cost about 0. Providers' own prompt caches also show up, as cached input tokens and a "provider cache saving". |
| **Compression** *(Demo milestone)* | An experimental toggle that shortens long context before sending it, with the saving shown separately. |
| **Cost panel** | After every answer: tokens, cost, what a premium model (`gpt-5.4`) would have cost (an estimate, never a call), the savings by category, Metis-Auto's own overhead, and how much of the budget is used. §7 explains how to read it. |

All conversations in the demo must use **your own or synthetic messages**, never real user data (ADR-0018).

## 2. Setup from a fresh clone

You need **Python 3.13**, a real installation rather than conda's. On macOS with Homebrew: `brew install python@3.13`. On other systems, any non-conda Python 3.13 works.

```sh
git clone <repo-url> metis-auto
cd metis-auto

# 1. A virtual environment from Python 3.13 (not conda)
/opt/homebrew/bin/python3.13 -m venv .venv      # or: python3.13 -m venv .venv

# 2. Install the exact, hash-checked versions from the lockfile
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pip install -e . --no-deps

# 3. Fetch the tokenizer files once (public files, ~17 MB; no key, no cost)
.venv/bin/python scripts/fetch_tokenizer_assets.py

# 4. Check that everything works (offline, about 10 seconds)
.venv/bin/python -m pytest -q
```

- **Lockfiles:** `requirements-dev.lock` pins every package with a hash. `--require-hashes` refuses anything else. Use the lockfile, not `pip install <package>`.
- **Tokenizer files:** these let Metis-Auto count tokens exactly as each provider does. They go to `data/tokenizers/` (ignored by git), and each is checked against a pinned sha256. Without them everything still runs, but token counts are labelled approximations.
- **Expected test result:** all tests pass, and one network test is skipped. Tests never call a model and never need a key.

## 3. Two ways to run it

| | **Fake mode** | **Real-model mode** |
|---|---|---|
| Answers | canned `[SYNTHETIC] fake answer …` text | real answers from the models |
| Cost | none; the cost panel shows what the fake answer *would* cost | real money, from the shared budget (§6) |
| Needs | nothing | your Metis key in `.env` (§4) **and** `config/local.toml` with live calls switched on (§5) |
| Start | `.venv/bin/python scripts/chat.py --fake` | `.venv/bin/python scripts/chat.py --model gpt-4o-mini` |

Start with fake mode: it shows the whole pipeline, including the cache and the cost panel, for free.

## 4. Your Metis key and the `.env` file (real-model mode only)

- **What `.env` is:** a small text file in the project's root folder that holds **secrets**: values that must never be shared or committed. Metis-Auto reads it at start-up. It is listed in `.gitignore`, so git never commits it. Never paste the key anywhere else: not in a config file, a commit, a chat, or a screenshot.
- **Your own key:** every model is reached through the Metis gateway with one Metis API key. Create a key in your Metis account's dashboard, in its API-keys section (the exact steps are on Metis's site and are not repeated here). If you use the project's shared Metis account, ask the project owner for a key instead. The key is for **development and testing only**.
- **Where to paste it:**

  ```sh
  cp .env.example .env        # only if .env does not exist yet
  ```

  Open `.env` and put the key after the `=` of the `METIS_API_KEY=` line, with no quotes and no spaces:

  ```
  METIS_API_KEY=<your key here>
  ```

  Leave everything else in `.env` as it is. `.env.example` (committed, placeholders only) explains every other variable; you don't need any of them.
- **Having a key does not switch live calls on.** That is the job of the second switch (§5).

## 5. `config/local.toml`: the second safety switch

**Why it exists.** A real call needs **two keys**, like a bank vault:
1. the program asks for real answers (`chat.py` does this when you don't pass `--fake`), **and**
2. *this computer* allows it, in `config/local.toml`.

Your Metis key alone is never enough. A fresh clone therefore cannot spend money by accident, and you can switch live calls off without touching your key.

**What it is.** `config/local.toml` holds settings for **this computer only**. It is ignored by git (never committed), and it holds no secrets. The committed file `config/local.example.toml` is its template, and its comments are the in-file reference for every section.

**Create it**, in one of two ways. Don't do both:

- **(a) Copy and edit** (recommended):

  ```sh
  cp config/local.example.toml config/local.toml
  ```

  Open `config/local.toml`, find the existing `[live]` section, and remove the `#` in front of `enabled = true`:

  ```toml
  [live]
  # Second key for live calls ...
  enabled = true
  ```

- **(b) Replace the whole content** with just what you need:

  ```toml
  [live]
  enabled = true

  [budget]
  run_cap = "0.10"
  ```

> **Don't add a second `[live]` (or `[budget]`) section.** If you copy the example and then paste `[live] enabled = true` at the end, the file has two `[live]` headings, and every command fails with `Cannot declare ('live',) twice` (§8). Each section may appear only once: edit the existing one.

**What each section means:**

| Section | Meaning | Usually |
|---|---|---|
| `[paths]` | where run records and the spend ledger live on this computer | leave commented out |
| `[logging]` | how much the programs log (`"DEBUG"`, `"INFO"`, …) | leave commented out |
| `[live]` | `enabled = true` allows real calls on this computer (the second key) | `true` only while you want real answers |
| `[budget]` | lower caps for this computer: `run_cap` (per run) and `lifetime_cap` (in total); they can never exceed the 20 USD ceiling (the shared default lifetime cap is 10 USD) | e.g. `run_cap = "0.10"` |

**Check it:** `.venv/bin/python scripts/show_budget.py` prints the budget and `live_blocked_by`. With `.env` and `local.toml` set up, the only reason left should be `experiment.counterfactual_source is not 'live'`. That is expected: `chat.py` supplies that key itself.

**Turn live calls off again:** set `enabled = false` (or put `#` back in front of it), or delete `config/local.toml`. Fake mode keeps working either way.

## 6. The budget

- **10 USD lifetime cap; 20 USD for the whole project, for good.** The *lifetime cap* (`budget.lifetime_cap`, 10 USD in `config/defaults.toml`) matches the spending limit the owner set on the Metis dashboard for the project key (Q-29, 2026-10-18). The *ceiling* of 20 USD is the project maximum: only `config/defaults.toml` can set it, and no local setting can raise a cap above it.
- **Per-run cap:** 1 USD by default for each run (one `chat.py` session is one run). Your `local.toml` can lower it, e.g. `run_cap = "0.10"`.
- **The spend guard:** before every real call, Metis-Auto estimates the call's maximum cost and refuses the call if it would go over either cap. You see `failure: budget_exhausted`. Every answered call is charged at its actual cost.
- **The ledger:** `data/spend/ledger.jsonl` records every charge (amount, time, run ID; no messages). **Never delete or edit it**: deleting it resets the lifetime total to zero on this computer, and a damaged file blocks all real calls.
- **Show the budget at any time** (makes no call):

  ```sh
  .venv/bin/python scripts/show_budget.py
  ```

- **The ledger is per computer.** Your ledger counts only the calls made *from your computer*. If several teammates use **one Metis account**, each ledger allows up to the 10 USD lifetime cap, so together you could spend more than the budget. Coordinate in one of two ways:
  1. **Preferably,** the account owner sets a **spending limit in the Metis dashboard**, which covers everyone (the owner's key has a 10 USD limit); and/or
  2. **split the budget:** each person lowers their own lifetime cap in `config/local.toml`, e.g. for four people sharing the 10 USD:

     ```toml
     [budget]
     lifetime_cap = "2.5"
     run_cap = "0.10"
     ```

  Each teammate with their *own* Metis account and key pays their own bill; the 20 USD project budget is the owner's.

## 7. Start the demo and read the cost panel

### The command-line chat (works today)

```sh
# Free: fake answers, no key, nothing to configure
.venv/bin/python scripts/chat.py --fake

# Real answers from one fixed model (needs §4 and §5)
.venv/bin/python scripts/chat.py --model gpt-4o-mini
.venv/bin/python scripts/chat.py --model deepseek-v4-flash --instructions "You are a helpful shop assistant. Answer briefly."
```

Type a message and press Enter. The chat keeps the conversation history. Commands:

| Command | Does |
|---|---|
| `/models` | list the models (and which are disabled) |
| `/model gpt-5-nano` | switch the model; history and cache are kept |
| `/reset` | forget the history |
| `/budget` | show the budget |
| `/quit` | leave (or Ctrl-D) |

Try this in fake mode: send a message, `/reset`, then send the **same** message again. The second answer is `served_by: cache`, and its cost is 0.

### The demo UI *(Demo milestone)*

The Streamlit UI arrives with the Demo milestone: a chat window, a bot-setup sidebar with synthetic presets, and toggles for routing mode, compression, and cache scope (owner brief §10). The command to start it, a screenshot, and a walkthrough of the toggles are added to this section then.

### Reading the cost panel

After each answer, the chat prints a block like this one (fake mode, numbers illustrative):

```
served_by: model   model: gpt-4o-mini   provider-reported model: -
tokens: input 28 (approximation), output 17 (exact_local), cached_input not reported, reasoning not reported, template_overhead 11 (approximation)
cost: 0.000016 USD  [template_overhead_approximated]
premium-baseline estimate: 0.000374 USD  [answer_length_assumed, reasoning_not_counted, template_overhead_approximated]
savings (this message | session):
  premium_baseline                   0.000374 USD | 0.000374 USD
  routing_saving                     0.000358 USD | 0.000358 USD
  compression_saving                 0.000000 USD | 0.000000 USD
  cache_saving                       0.000000 USD | 0.000000 USD
  provider_cache_saving              0.000000 USD | 0.000000 USD
  extra_cost                         0.000000 USD | 0.000000 USD
  actually_paid                      0.000016 USD | 0.000016 USD
overhead: 0.84 ms, cost 0.000000 USD
budget: 0 of 10 USD used (0.00%); this run 0 of 1
```

| Line | Meaning |
|---|---|
| `served_by` | `model` (a model answered), `cache` (Metis-Auto's own cache, no call), or `none` (no answer; see `failure`) |
| `model` / `provider-reported model` | the model Metis-Auto chose / the exact model version the provider says it used (real mode only) |
| `tokens` | input and output tokens. In brackets: how each was obtained. `provider_reported` = from the provider's bill; `exact_local` = counted with the model's own tokenizer; `approximation` = estimated. `cached_input` = input tokens the *provider* served from its cache (cheaper). `reasoning` = hidden "thinking" tokens, billed as output. `template_overhead` = formatting tokens around each message. |
| `cost` | what this message cost, with known caveats in brackets |
| `premium-baseline estimate` | what the premium model `gpt-5.4` would have cost for the same message and answer: an **estimate**, never a call, so always labelled with its caveats |
| `savings` | where the money went, for this message and the whole session. It always adds up: `premium_baseline − routing − compression − cache − provider_cache + extra_cost = actually_paid` |
| `routing_saving` | saved by using a cheaper model than the premium one |
| `compression_saving` | saved by shortening the context *(Demo milestone; 0 until then)* |
| `cache_saving` | saved by answering from Metis-Auto's cache (the whole call avoided) |
| `provider_cache_saving` | the provider's cached-input discount |
| `extra_cost` | anything else paid: retries, failed attempts, small counting differences |
| `overhead` | Metis-Auto's own processing time (not the model's) and the cost of any helper calls |
| `budget` | lifetime spend vs the lifetime cap (10 USD), and this run vs the per-run cap |

In fake mode, costs are what the fake answer *would* cost; nothing is charged and the budget does not move.

## 8. Troubleshooting

| You see | It means | Fix |
|---|---|---|
| `cannot start: live calls refused: live.enabled is false in the runtime configuration` | the second key is off | §5: `enabled = true` in `config/local.toml`, or use `--fake` |
| `cannot start: live calls refused: METIS_API_KEY is not set` | no key in `.env` (or the line is empty) | §4: paste the key after `METIS_API_KEY=`, with no quotes |
| `… local.toml: Cannot declare ('live',) twice (at line …)` | a section appears twice in `config/local.toml` | keep one `[live]` (and one `[budget]`): edit the existing section, §5 |
| `Extra inputs are not permitted [type=extra_forbidden …]` | a misspelt key, e.g. `enable` instead of `enabled` | fix the spelling; unknown keys are refused on purpose |
| `budget.lifetime_cap 25 exceeds the ceiling 20` | a cap above the 20 USD ceiling | use a value of at most 20 (lower is fine) |
| `failure: budget_exhausted` | the spend guard refused the call: it would go over the per-run or lifetime cap | `show_budget.py`; start a new run (per-run cap) or ask the owner (lifetime cap) |
| `LIVE CALLS STOPPED: actual cost not computed …` | a call failed without reporting its cost; its estimate was charged and live calls stopped for this run, to be safe | restart the chat; if it repeats, check your key and connection |
| `failure: no_eligible_model` | the model can't be used: it is disabled (`/models` shows which) or its limits are unknown | pick another model with `/model` |
| `cannot start: unknown model '…'` | a model name not in the catalogue | `/models`, or use one of the five test models |
| `spend ledger … is malformed …; live calls are refused` | the ledger file was edited or damaged | don't edit it; ask the project owner (never delete it to "fix" it) |
| Token counts say `approximation` everywhere | tokenizer files missing | `.venv/bin/python scripts/fetch_tokenizer_assets.py` |

Still stuck? `show_budget.py` lists every reason live calls are blocked. The [local development guide](local_development.md) has the details.
