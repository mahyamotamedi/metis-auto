# Team setup: build the database and the 300 records on your computer

For teammates who have never used Docker or PostgreSQL. No experience needed. Copy each command, run it, and compare with **You should see**.

> **How far this guide has been tested (2026-11-01).** Followed on a Mac from a clean copy with a fresh `.venv` and an empty database, ending in `PASS`. **Not run:** the `hf download` in step 4 (no token was used; the existing download was linked in) and every Windows command.

## What you will end up with

- A database on your own computer holding the Metis data. Nobody else can reach it.
- The same 300 evaluation records as everyone else, proven by a check that prints `PASS`.

There is no shared server, and we never pass the data or the database around. Everyone downloads and rebuilds.

## What you must not do

- **Do not share the data**, the database, or any file containing messages. The licence covers Rahnama College's educational use only and forbids redistribution. It applies to everyone who downloads the data.
- **Do not commit** data, `.env`, or tokens. `git status` must never show anything under `data/` or `runs/`.
- **Do not paste messages** into a chatbot, a website, a ticket or a chat.
- **Do not edit** `reports/evaluation/golden_v1/fingerprint.json` or `config/evaluation/golden_v1.toml` to make a check pass. A `FAIL` means your copy should not be used yet: ask for help.

## What you need

| Thing | Where to get it |
|---|---|
| About 10 GB of free disk | The data is about 1.3 GB and the finished database 2.6 GB (measured once on a Mac). |
| Git | [git-scm.com](https://git-scm.com) |
| Python 3.13 | [python.org](https://www.python.org/downloads/). On Windows, tick "Add to PATH". |
| Docker Desktop | [docker.com](https://www.docker.com/products/docker-desktop/). Open it and wait until it says it is running. |
| Access to the private dataset | Ask the project lead to add your Hugging Face account, then make a read token in your Hugging Face settings. Keep it private. |

## Steps

Commands are for macOS. Where Windows differs, its version follows, for PowerShell.

### 1. Get the code

```bash
git clone <repository URL> metis-auto
```
```bash
cd metis-auto
```
```bash
git checkout golden-dataset
```

### 2. Install Python packages

```bash
python3.13 -m venv .venv
```
```bash
.venv/bin/pip install --require-hashes -r requirements-db.lock
```
```bash
.venv/bin/pip install -e . --no-deps
```

Windows: `py -3.13 -m venv .venv`, then use `.venv\Scripts\pip` and, in later steps, `.venv\Scripts\python`.

**You should see:** `Successfully installed …` at the end of the last two commands. The install took about a minute.

### 3. Choose a database password

Make up a long password just for this. Create a file named `.env` in the `metis-auto` folder containing one line, with your password after the `=`:

```
METIS_DB_PASSWORD=your-long-password
```

Git ignores this file. Do not share it.

### 4. Download the data

macOS:

```bash
HF_TOKEN=your-token .venv/bin/hf download poriniki/metis --repo-type dataset --revision 30f578f283b903cdbd06cd1b5f7f962f76452ded --local-dir data/full_data/raw
```

Windows: run `$env:HF_TOKEN="your-token"`, then the same command with `.venv\Scripts\hf`.

**You should see:** files under `data/full_data/raw/data`, including `users.parquet`.

### 5. Start the database

```bash
docker compose --profile db up -d postgres
```

**You should see:** `Started` or `Running`. If it stops immediately with "Refusing to start", step 3 is not right.

### 6. Check everything

```bash
.venv/bin/python scripts/db_ingest.py --preflight
```

**You should see:** `[ ok ]` lines and `Ready.` A `[skip]` for `HF_TOKEN` is fine after the download.

### 7. Load the data

```bash
.venv/bin/python scripts/db_ingest.py
```

Took about 5 minutes on a Mac (285 s, measured once; yours may differ). You can stop it and run it again: it continues without damage.

**You should see:** `Run 1: ok.` with `2404351 rows inserted in this run.`

### 8. Build the 300 records

```bash
.venv/bin/python scripts/build_eval_dataset.py all
```

Took about 5 minutes on a Mac (298 s, measured once; yours may differ). Also safe to stop and re-run.

**You should see:** `Dataset golden-v1: 300 records, 150 reserves, status annotated_provisional.`

### 9. Prove you have the same records

```bash
.venv/bin/python scripts/build_eval_dataset.py verify
```

**You should see:** `PASS`. Done.

### 10. Build golden-v2 (the same 300 records without attachment images)

golden-v2 replaces the 23 records that carry an image with text-only ones ([golden_v2.md](../evaluation/golden_v2.md), [ADR-0029](../adr/0029-evaluation-dataset-golden-v2.md)). Do this after step 9 passed, because it is built from your golden-v1. If your copy of the repository is older than golden-v2, run `git pull` first.

```bash
git pull
```
```bash
.venv/bin/python scripts/build_eval_dataset.py --config config/evaluation/golden_v2.toml all
```
```bash
.venv/bin/python scripts/build_eval_dataset.py --config config/evaluation/golden_v2.toml verify
```

Windows: use `.venv\Scripts\python` as before.

**You should see:** `Dataset golden-v2: 300 records, 133 reserves, status annotated_provisional.`, then `PASS`. It takes about a minute, because the requests are already built. If it says "Refused … differs from the one this dataset derives from", your golden-v1 is not the team's: run step 9 and send the line to the lead.

### 11. Get reviewed labels, when there are some

After `git pull`, if `reports/evaluation/golden_v1/reviewed_labels.jsonl` exists:

```bash
.venv/bin/python scripts/build_eval_dataset.py import-labels reports/evaluation/golden_v1/reviewed_labels.jsonl
```

Labels are done once and shared through git, as IDs and labels with no text. For golden-v2, after importing the golden-v1 labels, carry them over with `.venv/bin/python scripts/build_eval_dataset.py --config config/evaluation/golden_v2.toml carry-labels reports/evaluation/golden_v1/reviewed_labels.jsonl`; the 23 replacement records need review.

## When a step fails

| What you see | What to do |
|---|---|
| `Docker is not running` or "cannot connect to the Docker daemon" | Open Docker Desktop and wait, then retry. |
| `METIS_DB_PASSWORD is not set` | Check the `.env` file from step 3: its name, its folder, and the line. |
| `Port 5432 is used by another program` | Another PostgreSQL is running. Stop it, or ask for help. |
| `The dataset is missing` or `revision is …` | Repeat step 4 with the exact revision. |
| `password authentication failed` | You changed the password after the first start. Ask for help; the fix deletes your local database. |
| 401 or 403 from Hugging Face | Your account has no access, or the token is wrong. Ask the lead. |
| `verify` prints `FAIL: config…` | Your code differs: `git status`, then `git pull`. |
| `golden-v2` says `Refused: golden-v1 is not built` or `differs from the one this dataset derives from` | Build and verify golden-v1 first (steps 8 and 9). If that passes and this remains, send the line to the lead. |
| `verify` prints `FAIL: dataset revision…` or `record ids…` | Do not use this copy. Send the printed line to the lead. It holds no messages. |

**Who to ask:** the project lead. Send the command and the error. Never send data.

## Stopping and removing

```bash
docker compose --profile db stop
```

To delete your local database too (you can rebuild it in steps 5 to 8):

```bash
docker compose --profile db down -v
```
