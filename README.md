# Nowa — know when to leave home

Proof recordings (owner to supply): **booking → SMS: pending** · **full evening → nearest day: pending** · **chest pain → 123 and booking stopped: pending**.

Nowa tells each patient when to leave home for a private clinic in Egypt.
The doctor's “on my way” tap and visit taps drive the queue, timing and messages.
Waiting of ~229 minutes → ~21 minutes is **simulated on assumed inputs**, not measured patient results.

## Run in under 5 minutes

Install Python **3.12** first. From the cloned repository:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m nowa demo
```

On Windows, activate with `.venv\Scripts\activate`. The command upgrades the database,
loads the shipped health library, seeds the fictional clinic, starts the worker and server,
and opens the front page at **http://127.0.0.1:8000** after `/health` succeeds.
No API key is needed. With `python -m nowa demo --no-browser`, open
**http://127.0.0.1:8000** yourself; use this exact host because the Origin check refuses other hosts.
Stop with Ctrl+C. If port 8000 is busy, stop the other server first.

## What to click

- **Watch an evening:** play, pause, change speed, or restart. Karim's drawn phone appears first.
  The doctor leaves at 19:10; a cancellation, silent patient, no-show, walk-in and long visits
  run through the real engine. Open the evening report at the end or the copy's doctor dashboard.
- **Book without AI:** choose one of three fictional patients, a day and an area, then confirm.
  Read the SMS on the drawn phone and open its private link. The last four phone digits shown
  on that phone verify cancellation or a change of day. The emergency banner stays visible.
- **Judge code (hosted instance):** use the private code supplied in the submission to create
  a practice clinic through the real sign-up. To show the judge box locally, set `JUDGE_CODES`
  to any value before starting, for example: `JUDGE_CODES=local-practice python -m nowa demo`.
  AI requires configured keys; watch and public booking remain offline.

## Real and simulated

Bookings, queue order, timing rules, persistent timers, fixed message templates, verification,
copy isolation, doctor sessions and the evening report use the real application code.
The evening's people, doctor taps, visits and patient reactions are scripted.
Travel is fixed per Cairo area; messages appear on drawn phones, with no SMS sent.
The health answer is a shipped, source-checked recording, labelled “recorded”.

`nowa demo` defaults `DEMO_NO_NETWORK` to 1: Telegram, Mapbox and the Mac relay are disabled.
Explicitly setting `DEMO_NO_NETWORK=0` enables configured real adapters for the owner's
clinic; with `MAPBOX_TOKEN`, that clinic uses live traffic. Demo copies always use fixed travel.
AI keys do not enable AI in watch or public booking mode.

Local data persists in `nowa-demo.db`; generated server/link secrets persist in
`.nowa-secrets`. Both are gitignored. The seeded fictional doctor's mobile is
`+201000000001`, password `demo1234` (override with `DEMO_DOCTOR_PASSWORD`).
Demo mode is for a local laptop; hosted deployments refuse it.

## Checks

```sh
pytest -q
ruff check nowa tests
mypy nowa
```

The offline suite needs no keys or network. Postgres tests require `TEST_DATABASE_URL`
pointing to a disposable test database; CI requires them.
`python -m nowa aitest --runs 3` is the separate live AI gate and needs configured keys.

Environment names: `DATABASE_URL`, `DEMO_MODE`, `SERVER_SECRET`, `LINK_SECRET`,
`PUBLIC_BASE_URL`, `DEMO_NO_NETWORK`, `WORKER_IN_PROCESS`, `GEMINI_API_KEY`,
`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `MAPBOX_TOKEN`, `JUDGE_CODES`.
and [.env.example](.env.example). Never publish credential values or judge codes.

## Deploy

1. GitHub: enable secret scanning and push protection; scan the full history with gitleaks.
2. Supabase: turn Data API off (fallback: RLS enabled, with no policies on every table).
3. Render: deploy only after green CI, one instance, `WORKER_IN_PROCESS=1`,
   `DEMO_MODE` unset, `TRUSTED_PROXY_HOPS` unset.
4. UptimeRobot: check `/health` every 5 minutes and alert the owner on failure.
Production uses Postgres; run `python -m nowa migrate`, then `python -m nowa serve`.

## Design and credit

[Vision](docs/vision.md) · [Architecture](docs/architecture.md) ·
Parts build on the owner's earlier clinic assistant prototype, **Tarek**.
The proof recordings and deployment acceptance remain the owner's lane.
