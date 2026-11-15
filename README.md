# Orbit

**Care that circles around your parent.** Orbit is an elder-care and medication platform for a parent who can no longer manage a phone. They get one big button by the bed. Their family, nurse and doctor share everything else: who gives each dose, what was missed, how they are, what is running out, and who to call.

Built for **Catalyst: Solo AI Hackathon** (Makers Need More × PromptWars, Hack2skill).

**Live:** https://orbit-care.onrender.com (free Render instance: the first load after a quiet spell can take up to a minute) · **Try it:** press **See a sample family**. It creates a private sample with a week of history. A bar at the bottom switches between the family, nurse, doctor and bedside views in one tap.

## Chosen vertical

**Elderly Care & Medication Management Platform.**

**Persona:** an older person too unwell to manage their own care, plus the people around them.

- **The sample family:** Papa has Parkinson's and brain microbleeds, is on heavy medication with side effects, finds it hard to follow what is happening, and cannot speak clearly. His wife runs a business, his children live elsewhere, and a nurse comes in for part of the day.
- **Users:** the elder at the bedside, family members, a nurse or caretaker, and the doctor.

## Approach and logic

A reminder app does not help someone who cannot use a phone. What helps is the people around them knowing, every day, **whether someone actually gave Papa the 1 pm dose**, and hearing quickly when nobody did. So Orbit has two very different sides:

| For the elder: the bedside screen | For the circle: family, nurse, doctor |
|---|---|
| An old phone or tablet on a stand, set up once by the family. No reading, no typing, no menus. | A shared profile behind a passcode for each person. Each person's role decides what they can see and change. |
| At dose time it speaks ("Papa, it's time for your medicine") and the whole screen turns into one button showing the tablet's colour. | Every dose has a named person who gives it. They mark it **given** or **skipped (with the reason)**. |
| **Hold for Help** (2 seconds) emails the whole circle at once and shows one-tap calls for the ambulance and each person. | Reminders go to the person giving the dose first, then the whole family if it is still not marked. |
| One picture question a day: 😊 Good / ☹️ Not good. The answer goes into the record. | Side-effect notes in one tap: tremor, confusion, fall, sleepy, nausea, pain, not eating, calm. |

**The logic: decisions come from context, and fixed code makes them.** Each row below is a rule in `app/rules.py` or `app/routes/`, and each is covered by a test.

| Context | Decision |
|---|---|
| A dose is 15 minutes away | Email the person assigned to give it (or the family, if nobody is assigned) |
| Not marked 30 minutes after it was due | The dose counts as **missed**; remind the giver |
| Still not marked after 60 minutes | Tell **everyone else in the circle** (family and caretakers) |
| Marked given or skipped | No more reminders. A given dose takes one off the stock count; undo puts it back |
| Tablets left ÷ daily use ≤ 5 days | Email the family a refill warning, with chemist and pharmacy shortcuts on screen |
| Last visit to a doctor + repeat interval is within a week, and nothing is booked | "Checkup due, nothing booked" email with the clinic's number |
| Appointment in under 7 days / under 1 day | Email the family and the person going along |
| 20:00 in the elder's time zone | Evening update to the family (Gemini wording, template fallback) |
| Viewer's role | Doctor: read-only. Bedside: confirm a dose, answer "how are you", Help. Caretaker: doses, medicines, visits, notes. Family: all of that, plus people, settings, sent emails and history |
| Local time between 21:00 and 06:00 | The bedside screen switches to low-glare amber night mode |
| Help held for 2 seconds (once a minute at most) | Email everyone in the circle and show the call buttons |
| Model text contains a number that is not in the record | Throw it away and use the template |

Thresholds are per family, under People & settings. Adherence is counted only for doses that are given, skipped or missed, so a dose that is not due yet never lowers the figure.

## Assumptions

- **Someone else gives the medicine.** The elder may tap "taken" on the bedside screen, but Orbit does not expect them to manage anything. A dose counts as given only when someone marks it.
- **A family member sets things up once:** the medicines, who gives each dose, the people and their passcodes, and the bedside tablet (signed in once with its own passcode).
- **Doses have fixed times.** "As needed" medicines and tapering doses are not modelled yet.
- **Times are in the elder's time zone**, Asia/Kolkata by default.
- **Email is the alert channel**, as the challenge asks. Calls are tap-to-call buttons, because a web page cannot place a phone call by itself.
- **Stock counts tablets given through Orbit.** After buying more, the family updates the number in hand.
- **Sign-in is passcode-based**, as the challenge asks: an orbit code shared by the family plus a personal passcode for each person. There are no separate email-and-password accounts.
- **Emergency numbers default to India's 112 and 108** and can be changed for each family.
- **Gemini is optional.** Without a key, every summary uses a fixed template and all features still work.
- **It is not a medical device** and gives no medical advice.

## What the challenge asks, and where it is

| Challenge asks for | In Orbit | Code |
|---|---|---|
| Elder, caretakers and family share one healthcare profile | One "orbit" per elder; members with roles `family`, `caretaker`, `doctor`, `elder` (bedside) | `app/auth.py` (`allow(...)` on every route) |
| Secure, passcode-based access | Each person has their own 6–12 digit passcode, stored only as a salted scrypt hash. Weak codes like `123456` are refused, and the orbit locks for 15 minutes after 5 wrong tries. Sessions use signed HttpOnly SameSite=Strict cookies. A removed person loses access immediately. | `app/security.py` |
| View, add, edit, manage medication schedules | Medicines with several times a day, a named person for each time, tablet colour, instructions and stock. Stopping a medicine keeps its history. | `app/routes/medicines.py` |
| Track adherence | Each dose is given, skipped, missed, due or upcoming. Adherence is shown by medicine and by time of day (morning, afternoon, evening, night) for 7, 14 or 30 days. | `app/rules.py` (`adherence`) |
| Monitor upcoming doctor appointments | Each visit records who goes along, an optional repeat interval for regular checkups, a tap-to-call clinic number and an **Add to Google Calendar** link | `app/routes/visits.py`, `static/js/circle.js` |
| Proactive email for **upcoming doses** | 15 minutes before a dose, to the person giving it | `app/rules.py` (`plan_notifications`) |
| Proactive email for **missed medications** | 30 minutes after, to the giver; 60 minutes after, to the whole family | same |
| Proactive email for **appointments** | A week before and the day before; also when a **regular checkup is due and nothing is booked** | same |
| Go beyond a reminder app | The bedside screen, Help, refill countdown with buy shortcuts, a doctor call or home-visit request carrying their current medicines and notes, "About them" for every new nurse, an evening update for the children, and a history of who changed what | throughout |
| Elder at the centre of their own decisions | The bedside screen asks how they are and records the answer; "About them" (what they like, what calms them) is the first thing a new nurse sees. Bedside access can only confirm a dose; it cannot skip or change anything. | `static/bedside.html` |

## How the solution works

```
 Bedside screen ─┐                          ┌─ PostgreSQL (Render) or Firestore (Google Cloud)
 Family / nurse ─┼─► FastAPI web service ───┤
 Doctor (read) ──┘          ▲               └─ Gemini API (words only, checked)
                            │ every 5 min
   GitHub Actions schedule  ┘ (or Cloud Scheduler) ──► /tasks/tick ──► email (Brevo API or SMTP)
```

1. **One Python service** serves the three screens and the API. It runs on Render's free plan (`render.yaml`) or on Google Cloud Run (`deploy.sh`).
2. **One storage interface with three backends:** PostgreSQL on Render, Firestore on Google Cloud, and in-memory storage for local runs. Every test runs against memory and against a real PostgreSQL. Storage holds each elder's profile, people, medicines, doses, visits, notes, feelings, outbox and history. Passcodes are stored only as hashes.
3. **A schedule calls `/tasks/tick` every five minutes** with a secret header: a GitHub Actions workflow on Render (`.github/workflows/tick.yml`), or Cloud Scheduler on Google Cloud. **Fixed rules** in `app/rules.py` decide what is due, what is missed and who is told. Every email has a stable key and is created only once, so a repeated tick never sends it twice.
4. **Gemini only writes words**: the evening update for the family, the summary before a doctor's visit, and tags suggested from a free-text care note. Every number comes from code. If the model's text contains a number that is not in the facts it was given, the text is thrown away and a plain template is used. The same happens when the model is slow or down, so the app works fully without it.
5. **Secrets** (session key, scheduler token, Gemini key, email key) live in the host's environment settings: Render environment variables, or Secret Manager on Google Cloud. None are in the repository.

"Let the model describe, let deterministic code decide."

## Measured

All numbers below come from our own runs on 2026-11-15.

- **The model never adds a number.** We ran the real summary path 20 times on the sample week with `gemini-3.1-flash-lite`. 18 replies passed the number check and were shown, 0 were rejected, and 2 timed out and fell back to the template. The median reply took 0.81 s. The check itself is tested with a fake model that invents a number (`tests/test_summary.py`).
- **From a missed dose to the whole family knowing: at most 65 minutes**, with the default rules: 60 minutes, plus up to 5 minutes until the next scheduler run. Families can shorten this under People & settings. The full sequence (giver reminded, then family told, nothing sent twice) is tested in `tests/test_api.py::test_missed_dose_escalates_by_email_exactly_once`.
- **Confirming a dose at the bedside takes one tap**, with no sign-in once the screen is set up.
- **We have no measured baseline** for how long a missed dose goes unnoticed in a family without Orbit. The way to get one is to ask caregiving families to log, for two weeks, each missed dose and when someone other than the giver first learned of it, then compare with Orbit's outbox times.

## Google services used

- **Gemini API** (`gemini-3.1-flash-lite`) writes the summaries and suggests note tags, and its text is checked before it is shown.
- **Google Maps** links find nearby pharmacies and hospitals.
- **Google Calendar** links add visits to a calendar.
- **Google Cloud deploy path** (`deploy.sh`): Cloud Run, Firestore (`app/store_firestore.py`, tested against the Firestore emulator), Cloud Scheduler, Secret Manager and Cloud Build.

## Security

Full details are in [SECURITY.md](SECURITY.md).

- Passcodes are hashed with salted scrypt and compared in constant time. A keyed HMAC fingerprint finds the right person, so sign-in runs one slow hash, not one per member. Weak passcodes are refused, the orbit locks after 5 wrong tries, and sign-in and creation are rate-limited per address.
- An unknown orbit code and a wrong passcode get the same answer, so a guesser learns nothing.
- Every route checks the role. Doctors can only read. The bedside screen can only confirm a dose, answer "how are you" and press Help.
- Cookies are HttpOnly, Secure and SameSite=Strict, with the `__Host-` prefix in production. Every state-changing request also needs a custom header, which blocks cross-site request forgery.
- The Content-Security-Policy allows only the app's own scripts (no inline script) and Google Fonts. HSTS, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, and same-origin COOP/CORP are set.
- All server text is inserted into pages with `textContent`, never as HTML.
- Request bodies are strict Pydantic models with length and pattern limits, and unknown fields are rejected. Email headers are stripped of line breaks.
- Sample orbits never send real email and are deleted after 24 hours. Each orbit also has a daily email cap.
- The container runs as a non-root user.
- Dependencies are pinned and checked with `pip-audit` on every CI run (no known vulnerabilities on 2026-11-15).

## Accessibility

- **Bedside, for shaking hands and tired eyes:**
  - The whole screen is one button, with the tablet drawn in its real colour and a "Repeat" button for the spoken prompt (Web Speech API).
  - Help needs a 2-second hold, so a brushing hand never raises a false alarm (Enter also works).
  - Warm amber night mode from 21:00 to 06:00.
  - A "Connected to family" status that changes to "Offline" when the network drops.
  - A soft chime and vibration when a dose is taken, and a confirmation naming who can see it.
- **Care circle:**
  - Doses are grouped into morning, afternoon, evening and night, each with the giver's avatar.
  - Refills show as supply bars.
  - Every dose mark can be undone for 10 seconds.
  - Empty states tell a new family what to do first.
  - The doctor's brief prints on one page, with doses and symptoms on the same day-by-day timeline.
- Semantic HTML with labels on every field, a skip link, keyboard-navigable tabs (arrow keys), visible focus rings, and `aria-live` for updates.
- Every text colour meets WCAG AA contrast (4.5:1) in light, dark and bedside night mode. The one alarm colour (terracotta) always means "needs someone now". There is extra contrast for `prefers-contrast: more`, and Windows high-contrast mode is supported.
- Animation stops entirely under `prefers-reduced-motion`. Pages work at phone width without sideways scrolling.
- **Checked with axe-core 4.10** (WCAG 2.1 A/AA and best practice) on 18 page states on 2026-11-15, with **0 violations**:
  - the landing page, the sample dialog, the 3-step start, an empty new circle, the add-medicine dialog;
  - Today, Summary and People in light and dark;
  - the bedside screen in light, dark and night.

## Run it locally

```bash
pip install -r requirements-dev.txt
ORBIT_COOKIE_SECURE=0 ORBIT_INPROCESS_TICK=1 uvicorn app.main:app --reload --port 8080
# open http://localhost:8080 and press "See a sample family"
python -m pytest --cov=app   # 106 tests; with ORBIT_TEST_DATABASE_URL=postgresql://... every API and storage test
                             # also runs on PostgreSQL: 165 tests, 92% line coverage (2026-11-15)
```

Without settings, data is kept in memory and emails stay in the in-app outbox. See `.env.example` for every setting.

## Deploy on Render (free)

1. Render → **New → Blueprint** → pick this repository. `render.yaml` creates a free web service and a free PostgreSQL database.
2. Fill in the values it asks for:
   - `ORBIT_TICK_TOKEN`: any long random string.
   - `GEMINI_API_KEY`: optional; without it, summaries use the plain template.
   - `BREVO_API_KEY` and `MAIL_FROM`: optional; needed for real emails. Render's free plan blocks outgoing SMTP, so email goes over Brevo's HTTPS API.
3. In GitHub → Settings → Secrets and variables → Actions, add `ORBIT_URL` (the Render URL) and the same `ORBIT_TICK_TOKEN`. The `reminder-tick` workflow then runs the reminder rules every 5 minutes.

## Deploy to Google Cloud

In Google Cloud Shell, from this folder: `gcloud config set project YOUR_PROJECT_ID` then `./deploy.sh`. The script turns on the APIs and creates the Firestore database. It gives the service account only the roles it needs, stores secrets in Secret Manager (it asks for the Gemini key and, optionally, a Gmail app password), deploys to Cloud Run, and creates the Cloud Scheduler job. It is safe to run again.

## Planned, not built

- **Smartwatch sync** (heart rate, falls, sleep): this needs each watch maker's API and a partnership.
- **Real phone calls and SMS** for Help and missed doses. Today Help sends email and shows tap-to-call buttons, because a web page cannot place a call by itself.
- **Booking an ambulance or a home visit through a provider's system.** Today it is a tap-to-call plus an emailed request to the saved doctor.
- **Spoken answers from the elder** ("I took it", "I feel dizzy"), for people who can still speak a little.
- Several languages on the bedside screen.

## Repository layout

```
app/
  rules.py        every decision: dose states, adherence, refills, checkups, who is emailed (pure functions)
  routes/         the HTTP API, one module per area: account, doses (and bedside, Help), medicines,
                  visits, people, reports, tasks; deps.py holds the shared role groups and checks
  auth.py         sessions, roles, rate limits      security.py   passcodes, tokens, lockout
  notify.py       emails, exactly once              summary.py    Gemini wording, checked
  care.py         facts and templates               models.py     strict request bodies
  store.py / store_postgres.py / store_firestore.py   one storage interface, three backends
static/     index.html (landing), circle.html (family, nurse, doctor), bedside.html (the elder)
tests/      rules, security, API flows, editing flows, every email kind, both email senders,
            the storage contract on memory and PostgreSQL, the model check
render.yaml Render Blueprint (free web service and PostgreSQL)
deploy.sh   one-command Google Cloud deploy
```

Orbit is a prototype. It does not replace medical advice or emergency services. In an emergency, call 112 (ambulance 108).

MIT licence.
