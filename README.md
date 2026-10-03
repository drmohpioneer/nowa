# Nowa: know when to leave home

Nowa is a waiting-room agent for private clinics in Egypt.

In a typical private clinic everyone is told to come at 7 pm, the doctor arrives late from the hospital, and patients sit for hours. With Nowa a patient books a day and a queue number, the doctor taps **on my way** once and **who comes in** after each visit, and Nowa tells every patient on Telegram the minute to leave home.

The AI only talks: it understands the patient, triages, and answers from approved health pages. Code decides everything else: bookings, the queue, times, messages and limits.

Demo video (2:26, recorded from this demo): [docs/submission/nowa-demo.mp4](docs/submission/nowa-demo.mp4)
Impact slides: [docs/submission/nowa-impact-slides.pdf](docs/submission/nowa-impact-slides.pdf)

## Run it in 5 minutes, no keys

You need Python 3.12 or newer.

```sh
git clone https://github.com/drmohpioneer/nowa && cd nowa
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m nowa demo
```

The browser opens http://127.0.0.1:8000 (use this exact host, the server checks the Origin). The pages open in English unless your browser is set to Arabic; the link in the top bar switches language.

Press **See Nowa working**. The demo hub has four doors:

1. **Live evening.** Press play. One Tuesday evening of a fictional cardiology clinic runs through the real engine: 18 bookings, a cancellation, a silent patient, a no-show, a walk-in and long visits. You see the clinic clock, the doctor's state, the queue tiles changing, every Telegram message as it lands, and the evening report at the end. Speed x1, x2 or x4.
2. **Try booking as a patient.** Pick a fictional patient, a day and an area. The booking message lands on the drawn Telegram. Open its private link, tap "I'm on my way", cancel or change the day.
3. **Doctor's board.** Log in as the demo doctor (mobile `01000000001`, password `demo1234`) and run the evening yourself: on my way, who comes in, walk-in, undo, close.
4. **Evening report.** The numbers the doctor receives when the evening closes.

The AI chat at `/c/dr-hesham` needs a Gemini key: `GEMINI_API_KEY=... python -m nowa demo`. Everything else works without any key.

Stop with Ctrl+C. To use another port, set `PORT` and `PUBLIC_BASE_URL` together.

## What is real and what is simulated

Real application code: bookings, queue order, expected-time rules, persistent timers, the six fixed message templates, verification and lockouts, doctor sessions, triage layers, the health library, and the evening report.

Scripted: the people of the Live evening, the doctor's taps and the patients' reactions. The engine computes everything that follows from them.

Simulated: the headline numbers. Waiting about 229 minutes today against about 21 minutes with Nowa comes from a queue simulator on assumed inputs ([docs/reference/sim.py](docs/reference/sim.py)). It was not measured on patients.

Stand-ins in the demo: the drawn Telegram replaces the real bot (the same outbox feeds the Telegram Bot API when a token is set), and travel time is fixed per Cairo area (production uses Mapbox traffic). The demo makes no network calls.

Not yet proven: a live clinic. No real patient has used Nowa. The Telegram bot path (contact share proves the phone number, then messages go to the patient's own chat) is covered by offline tests against a fake Bot API, not by a field test.

## How it works

```
Patient (web chat, Telegram)      Doctor (board, Telegram)
              |                            |
        API layer: validation, sessions, rate limits
              |
   Conversation layer: Gemini with structured output, emergency
   layer first, then the specialty's triage rules. Produces
   candidates only; it has no tool that acts.
              |
   Core engine: booking, queue, timing, outbox, timers.
   Deterministic. Owns the truth.
              |
   Postgres (SQLite in the demo) -> Telegram sender, timer worker
```

Rules the code enforces:

- A booking is a day, a queue number and an expected time. The expected time only moves later, only by 20 minutes or more, and freezes after "leave now".
- Every message is one of six fixed templates filled from the database, in the patient's language (Arabic, English or Franco-Arabic).
- An emergency gets the fixed "call 123" message and booking is disabled for that chat.
- A Telegram chat is linked to a phone number only after the user shares their own contact and it matches.
- Every action is safe to repeat. Names and phones live only in the identity tables.

## Checks

```sh
python -m pytest -q        # offline, no keys
ruff check nowa tests
mypy nowa
```

CI: the GitHub Actions workflow (lint, types, offline tests, Postgres tests) is kept at [docs/ci/github-workflow.yml](docs/ci/github-workflow.yml). Copy it to `.github/workflows/ci.yml` to enable it. It has not run on this repository yet, so the Postgres-only tests (27, skipped locally) are unverified for the last two slices.

## How it was built

Nowa was designed and built by Dr Mohamed Mostafa, cardiologist, Cairo.


Built by Dr Mohamed Mostafa (cardiologist, Cairo) for Agents at Work 2026. Code written 30 September to 3 October 2026.
