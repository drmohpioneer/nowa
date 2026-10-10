# Nowa

**Know when to leave home.**

Nowa is an AI assistant for a private clinic in Egypt. It talks with patients in Arabic, English or Franco, books, moves and cancels their visits, answers health questions only from approved medical sources, passes the rest to the doctor, and stops everything to send an emergency to 123. On clinic night it runs the queue from two taps by the doctor and tells each patient, on Telegram, the exact minute to leave home.

[![Watch the film (2:41)](docs/img/film.jpg)](https://youtu.be/CoW-QtdwgFg)

**Watch the film (2:41):** https://youtu.be/CoW-QtdwgFg
**Impact slides:** [docs/submission/nowa-impact-slides.pdf](docs/submission/nowa-impact-slides.pdf)
**Live:** https://nowa-bche.onrender.com

## The problem

In a private clinic in Egypt every patient is told the same time, and then the doctor is held up at the hospital. The room fills with people who are already unwell, and nobody can tell them how long they will wait. The secretary answers the same calls all evening: booking, prices, times, has the doctor arrived.

In a survey of colleagues who run private clinics in Cairo and Sharqia, 83% start late, by 15 to 60 minutes. Their patients wait 45 minutes at the median and 66 on average, and in a third of the clinics the wait passes an hour.

## What Nowa does

**The front desk, at any hour**

- **Talks like the secretary.** A patient opens the clinic's chat link (or scans the poster on the door) and writes the way they speak: Arabic, English or Franco, in the same conversation.
- **Books, moves and cancels.** For the patient or for someone else. Every booking is a day, a queue number and an expected time. One private link lets the patient change the day or cancel, and the chat finds any booking by name and the last four digits of the phone.
- **Answers health questions from approved sources only.** Replies come from a library of approved medical pages (NHS, MedlinePlus, CDC) and show the source. What the library cannot answer goes to the doctor, who answers once; Nowa reuses that answer for the next patient who asks.
- **Puts emergencies first.** A dangerous symptom gets a fixed "call 123" reply, the chat locks and booking stops. This check runs before anything else on every message.

**Clinic night**

- **Two taps by the doctor.** "On my way" when leaving the hospital, and "who comes in" after each visit. Nothing else to manage.
- **One message at the right minute.** From the doctor's drive, the pace of the queue and each patient's own travel time, Nowa sends every patient one Telegram message, "leave now", so they arrive just before their turn.
- **A full day is not a dead end.** A waiting list offers a freed place at once, with a one-tap take, and the clinic takes a few bookings over capacity from its own learned no-show rate.
- **The evening report.** Who came, who did not, walk-ins, the average visit and the average wait, on Telegram when the doctor closes the night.

**It learns the clinic**

- The visit length, how late the evening starts and who tends not to show, from each closed night, shown to the doctor in the settings and used for the next evening.
- Any place in Greater Cairo: 72 districts with Arabic, English and Franco spellings and typo tolerance; with a Mapbox token, any typed place is geocoded; a place off the map gets a safe travel allowance, never a refusal.
- Telegram on any device: a QR on a laptop, a button on a phone, the install explained when Telegram is missing, an expired link renewed, and a clear message when the numbers differ.

![The live evening: clinic clock, the patient in the room, the queue and the Telegram messages](docs/img/live-evening.jpg)

## Impact

| | Number | Basis |
|---|---|---|
| Wait on a full 30-patient evening | 229 min to 21 min (median) | Simulated, 300 evenings, assumed inputs |
| Wait in clinics today | 45 to 66 min | Colleague survey, Cairo and Sharqia |
| Patient-hours returned per clinic per month | 100 to 190 h | Assumed 15 patients a night over 17 nights, today's wait against the simulated 21 min |
| What the doctor does | 2 kinds of tap | By design |
| Cost to run | about 1.7 EGP per patient | Estimate |
| Price | 1,500 EGP per clinic per month, about two visit fees | Proposed |

Nowa is a working product that has not served a real clinic yet, so its wait results are simulated and the survey is the measurement. The first pilot is the next step.

## Try it hosted, nothing to install

Open https://nowa-bche.onrender.com and press **See Nowa working**. A judge code from the submission form opens a practice clinic with 12 fictional patients, a practice clock and a drawn Telegram phone that shows every message, so no Telegram account is needed. The first request can take up to a minute while the free server wakes.

## Run it in 5 minutes, no keys

You need Python 3.12 or newer.

```sh
git clone https://github.com/drmohpioneer/nowa && cd nowa
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m nowa demo
```

The browser opens http://127.0.0.1:8000 (use this exact host). Press **See Nowa working**.

1. **Watch a full evening.** Press play. One Tuesday evening of a fictional cardiology clinic runs through the real engine: 18 bookings, a cancellation, a silent patient, a no-show, a walk-in. You see the clinic clock, the doctor's state, who is in the room, every Telegram message as it lands, and the evening report at the end.
2. **Open the doctor's board** from that page. It is the board of the same evening: tap who comes in, add a walk-in, undo, close.
3. **Book as a patient.** Pick a patient, a day and an area. The confirmation lands on the drawn Telegram with a private link.

The story page, the demo hub and the Live evening open in English or Arabic by your browser language. The clinic chat, the patient page and the doctor's board are in Arabic, as Egyptian patients and doctors use them, and the Live evening labels every message in English.

The AI chat at `/c/dr-hesham` needs a Gemini key (`GEMINI_API_KEY=... python -m nowa demo`). Everything else runs with no key and no network.

## Proof it works

```sh
python -m pytest -q        # 1,968 tests, offline, no keys
ruff check nowa tests
mypy nowa
```

Three runs you can check yourself:

1. **A normal booking.** Book as a patient. The reply gives the day, the queue number and the expected time, and the drawn Telegram shows one confirmation with a private link.
2. **The same request twice does nothing twice.** Every command carries an idempotency key and a replay returns the first result: `python -m pytest -q tests/test_booking.py -k "idempotency or replay or duplicate"`.
3. **An emergency stops booking.** With a Gemini key, type "chest pain" in the clinic chat: the fixed "call 123" reply appears and no booking is offered (shown in the film). Without a key: `python -m pytest -q tests/test_message_goldens.py tests/test_messaging.py -k emergency`.

## How it works

```
Patient (web chat, Telegram)      Doctor (board, Telegram)
              |                            |
        API layer: validation, sessions, rate limits
              |
   Conversation layer: Gemini with structured output, emergency
   layer first, then the specialty's triage rules. It produces
   candidates only and has no tool that acts.
              |
   Core engine: booking, queue, timing, outbox, timers.
   Deterministic. Owns the truth.
              |
   Postgres (SQLite in the demo) -> Telegram sender, timer worker
```

The one rule between the layers: the AI talks, code decides. The model must answer in a strict schema (triage level, intent, the booking fields it understood, whether it is a health question, a reply) and has no tools. Code alone books, times and sends.

Rules the code enforces:

- A booking is a day, a queue number and an expected time. The expected time only moves later, only by 20 minutes or more, and freezes after "leave now".
- Every message a patient receives is one of a fixed set of approved templates, filled from the database in the patient's language (Arabic, English or Franco-Arabic).
- A Telegram chat is linked to a phone number only after the user shares their own contact and it matches.
- Every action is safe to repeat. Names and phones live only in the identity tables.

Built to fail safely:

- **The AI provider is slow or down.** The chat falls back through a chain of models to a fixed reply that gives the clinic's phone. Booking by buttons and the timing engine never need a model.
- **Telegram cannot deliver.** The message is marked failed and the doctor is alerted once.
- **The travel service fails.** Nowa uses a fixed travel time for the patient's area.
- **The doctor has not tapped by opening time.** Nowa reminds the doctor on Telegram.

In the demo, the people and their actions in the Live evening are scripted; the engine computes everything that follows. The drawn Telegram stands in for the real bot, and travel times are fixed per Cairo area. With keys configured, the same code uses the Telegram Bot API and live Mapbox traffic.

## Roadmap

1. **A first pilot** in a real clinic. Measure the real wait and how often doctors and patients tap. Test the price.
2. **SMS as a second channel** for patients who do not use Telegram, after a carrier contract and a field test. WhatsApp follows if the pilot shows the need.
3. **Data protection licences.** Egypt's Law 151 of 2020 requires them before holding real patient data. The design already keeps names and phones in separate identity tables.
4. **More specialties.** Cardiology triage rules are in place; other specialties follow after specialist review.
5. **Later.** A voice assistant that answers the clinic phone, and patient follow-up built on the visit history.

## Hosted instance

The hosted copy runs at https://nowa-bche.onrender.com (Render, Frankfurt; Postgres on Supabase, Frankfurt) with a real Telegram bot. A judge code opens a seven-day practice clinic; a doctor can also register a real clinic from the front page.

## More

- Environment names for your own instance: [.env.example](.env.example)
- The queue simulator behind the wait numbers: [docs/reference/sim.py](docs/reference/sim.py)
- Area coordinates: [docs/reference/greater-cairo-areas.json](docs/reference/greater-cairo-areas.json). Area coordinates © OpenStreetMap contributors, ODbL.
- Licence: all rights reserved, see [LICENSE](LICENSE). The code is published for review; running it locally to evaluate it is permitted.

Built by Dr Mohamed Mostafa, cardiologist, Cairo, for Agents at Work 2026.
