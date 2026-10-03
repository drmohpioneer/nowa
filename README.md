# Nowa: know when to leave home

Nowa is a waiting-room agent for private clinics in Egypt.

In a typical private clinic everyone is told to come at 7 pm, the doctor arrives late from the hospital, and patients sit for hours. With Nowa a patient books a day and a queue number, the doctor taps **on my way** once and **who comes in** after each visit, and Nowa tells every patient on Telegram the minute to leave home.

The AI only talks: it understands the patient, triages, and answers from approved health pages. Code decides everything else: bookings, the queue, times, messages and limits.

Status: a working prototype, tested offline and in simulation. It has not been used in a real clinic yet; a pilot in one clinic is the next step.

Impact slides: [docs/submission/nowa-impact-slides.pdf](docs/submission/nowa-impact-slides.pdf)

## Run it in 5 minutes, no keys

You need Python 3.12 or newer.

```sh
git clone https://github.com/drmohpioneer/nowa && cd nowa
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m nowa demo
```

The browser opens http://127.0.0.1:8000 (use this exact host, the server checks the Origin). The story page, the demo hub, the Live evening and the sign-up page open in English unless your browser is set to Arabic; the link in the top bar switches language. The clinic chat, the patient page and the doctor's board are in Arabic, the way Egyptian patients and doctors use them; the Live evening labels every message in English.

Press **See Nowa working**. The demo hub has four doors:

1. **Live evening.** Press play. One Tuesday evening of a fictional cardiology clinic runs through the real engine: 18 bookings, a cancellation, a silent patient, a no-show, a walk-in and long visits. You see the clinic clock, the doctor's state, the queue tiles changing, every Telegram message as it lands, and the evening report at the end. Speed x1, x2 or x4.
2. **Try booking as a patient.** Pick a fictional patient, a day and an area. The booking message lands on the drawn Telegram. Open its private link, tap "I'm on my way", cancel or change the day.
3. **Doctor's board.** The quickest way is the button **Open the doctor's board** on the Live evening: it opens the board of that same evening, mid-run, and you can tap who comes in, add a walk-in, undo and close. You can also log in as the demo doctor (mobile `+201000000001`, password `demo1234`); that clinic follows the real calendar and is open on Sunday, Tuesday and Thursday evenings, so on other days its board is empty.
4. **Evening report.** The numbers the doctor receives when the evening closes.

The AI chat at `/c/dr-hesham` needs a Gemini key: `GEMINI_API_KEY=... python -m nowa demo`. Everything else works without any key.

Stop with Ctrl+C. To use another port, set `PORT` and `PUBLIC_BASE_URL` together.

## What is real and what is simulated

Real application code: bookings, queue order, expected-time rules, persistent timers, the six fixed message templates, verification and lockouts, doctor sessions, triage layers, the health library, and the evening report.

Scripted: the people of the Live evening, the doctor's taps and the patients' reactions. The engine computes everything that follows from them.

Simulated: the headline numbers. A median wait of about 229 minutes on a full 30-patient evening where everyone arrives at opening, against about 21 minutes with Nowa, comes from a queue simulator on assumed inputs ([docs/reference/sim.py](docs/reference/sim.py)). It was not measured on patients. The clinics we surveyed (6 colleagues) report 45 to 66 minutes today. No revenue or cost saving is claimed as measured.

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

## Three runs you can check

1. **A normal booking, no key.** Demo hub, "Book as a patient", pick a patient, a day and an area. Expected: the reply gives the day, the queue number and the expected time; the drawn Telegram shows one confirmation with a private link; opening the link shows the patient page.
2. **The same request twice does nothing twice.** Every command carries an idempotency key and a replay returns the first result. Expected: `python -m pytest -q tests/test_booking.py -k "idempotency or replay or duplicate"` passes (4 tests): one booking, no second message.
3. **An emergency stops booking.** With a Gemini key, type "chest pain" in the clinic chat. Expected: the fixed "call 123" reply and no booking offer (this is the step shown in the film). Without a key: `python -m pytest -q tests/test_message_goldens.py tests/test_messaging.py -k emergency` passes (32 tests).

## When things fail

- **The AI provider is slow or down.** The chat falls back through a chain (two Gemini models, a third model, then a fixed reply) with a 12 second deadline per provider. Booking by buttons and the whole timing engine never need a model.
- **Telegram cannot deliver a message.** The message is marked failed and the doctor is alerted once. Nothing loops.
- **The travel service fails.** Nowa uses a fixed travel time for the patient's area.
- **The doctor has not tapped by opening time.** Nowa reminds the doctor on Telegram (you see this in the Live evening at 19:00).
- **A request arrives twice.** The second one returns the first result.

Money, stated plainly: nothing here is measured revenue. The proposed price is 1,500 EGP per clinic per month. The running cost is about 1.7 EGP per patient plus about 1,700 EGP per month shared by all clinics (both estimates), so the shared cost is covered from the second paying clinic.

## What is next

Nowa is a prototype today. This is the path to a product clinics can use, in order:

1. **A first pilot with three doctors.** Measure the real wait, whether doctors tap, and whether patients tap "I'm on my way". The simulator says that tap rate matters more than any tuning. Test the proposed price of 1,500 EGP per clinic per month.
2. **SMS for patients without Telegram.** Telegram is the only channel in this build. SMS is the planned second channel. It needs a carrier contract and a field test first, and Nowa does not ship a channel that has not been field-tested. WhatsApp follows if the pilot shows it is needed.
3. **Permission to hold real patient data.** Egypt's data protection law (151/2020) requires licences for health data and for a database hosted abroad, written consent and fixed retention periods. The design already keeps names and phones in separate identity tables. The licences come before the first real patient.
4. **More specialties.** Cardiology triage rules are approved; rules for other specialties are drafted and wait for a specialist's review.
5. **Later.** A voice assistant that answers the clinic phone, and patient follow-up built on the visit history.

The full list, including what was rejected and why, is in [docs/backlog.md](docs/backlog.md).

## How it was built

Nowa was designed and built by Dr Mohamed Mostafa, cardiologist, Cairo.


Built by Dr Mohamed Mostafa (cardiologist, Cairo) for Agents at Work 2026. Code written 30 September to 3 October 2026.
