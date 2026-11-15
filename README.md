# Orbit

**Care that circles around him.** Orbit is an elder-care and medication platform for the parent who can no longer manage a phone. He gets one big button by his bed. His wife, children, nurse and doctor share everything else: who gives each dose, what was missed, how he is, what is running out, and who to call.

Built for **Catalyst: Solo AI Hackathon** (Makers Need More × PromptWars, Hack2skill), challenge *Elderly Care & Medication Management Platform*.

**Live:** _added after deploy_ · **Try it:** open the live link and press **Open a sample family**. It creates a private sample with a week of history and shows the passcodes for each person, so you can see every view.

## Why it looks like this

Picture a father with Parkinson's and brain microbleeds, on heavy medication with side effects. He struggles to follow what is happening and cannot speak clearly. His wife runs a business. His children live elsewhere. A nurse comes in for part of the day.

He cannot use a reminder app, so a reminder app on his phone does not help him. What helps him is the people around him knowing, every day, **whether someone actually gave him the 1 pm dose**, and hearing quickly when nobody did.

So Orbit has two very different sides:

| For him: the bedside screen | For the circle: family, nurse, doctor |
|---|---|
| An old phone or tablet on a stand, set up once by the family. No reading, no typing, no menus. | A shared profile behind a passcode for each person. Each person's role decides what they can see and change. |
| At dose time it speaks ("Papa, it's time for your medicine") and the whole screen turns into one button showing the tablet's colour. | Every dose has a named person who gives it. They mark it **given** or **skipped (with the reason)**. |
| A big **Help** button emails the whole circle at once and shows one-tap calls for the ambulance (108) and each person. | Reminders go to the person giving the dose first, then the whole family if the dose is still not marked. |
| One picture question a day: 😊 Good / ☹️ Not good. His answer goes into the record. | Side-effect notes in one tap: tremor, confusion, fall, sleepy, nausea, pain, not eating, calm. |

## What the challenge asks, and where it is

| Challenge asks for | In Orbit | Code |
|---|---|---|
| Elder, caretakers and family share one healthcare profile | One "orbit" per elder; members with roles `family`, `caretaker`, `doctor`, `elder` (bedside) | `app/api.py` (`allow(...)` on every route) |
| Secure, passcode-based access | Each person has their own 6–12 digit passcode, stored only as a salted scrypt hash. Weak codes like `123456` are refused, and the orbit locks for 15 minutes after 5 wrong tries. Sessions use signed HttpOnly SameSite=Strict cookies. A removed person loses access immediately. | `app/security.py` |
| View, add, edit, manage medication schedules | Medicines with several times a day, a named person for each time, tablet colour, instructions and stock. Stopping a medicine keeps its history. | `app/api.py` (medicines) |
| Track adherence | Each dose is given, skipped, missed, due or upcoming. Adherence is shown by medicine and by time of day (morning, afternoon, evening, night) for 7, 14 or 30 days. | `app/rules.py` (`adherence`) |
| Monitor upcoming doctor appointments | Each visit records who goes with him, an optional repeat interval for regular checkups, a tap-to-call clinic number and an **Add to Google Calendar** link | `app/api.py`, `static/js/circle.js` |
| Proactive email for **upcoming doses** | 15 minutes before a dose, to the person giving it | `app/rules.py` (`plan_notifications`) |
| Proactive email for **missed medications** | 30 minutes after, to the giver; 60 minutes after, to the whole family | same |
| Proactive email for **appointments** | A week before and the day before; also when a **regular checkup is due and nothing is booked** | same |
| Go beyond a reminder app | The bedside screen, Help, refill countdown with buy shortcuts, a doctor call or home-visit request carrying his current medicines and notes, "About him" for every new nurse, an evening update for the children, and a history of who changed what | throughout |
| Elder at the centre of his own decisions | The bedside screen asks how he is and records his answer; "About him" (what he likes, what calms him) is the first thing a new nurse sees. Bedside access can only confirm a dose; it cannot skip or change anything. | `static/bedside.html` |

## How it works

```
 Bedside screen ─┐                         ┌─ Firestore (one document per elder,
 Family / nurse ─┼─► Cloud Run (FastAPI) ──┤   with sub-collections)
 Doctor (read) ──┘        ▲                └─ Gemini (words only, checked)
                          │ every 5 min
                   Cloud Scheduler ──► /tasks/tick ──► Gmail SMTP
```

1. **One Python service on Cloud Run** serves the three screens and the API.
2. **Firestore** holds each elder's profile, people, medicines, doses, visits, notes, feelings, outbox and history. Passcodes are stored only as hashes.
3. **Cloud Scheduler** calls `/tasks/tick` every five minutes with a secret header. **Fixed rules** in `app/rules.py` decide what is due, what is missed and who is told. Every email has a stable key and is created only once, so a repeated tick never sends it twice.
4. **Gemini only writes words**: the evening update for the family, the summary before a doctor's visit, and tags suggested from a free-text care note. Every number comes from code. If the model's text contains a number that is not in the facts it was given, the text is thrown away and a plain template is used. The same happens when the model is slow or down, so the app works fully without it.
5. **Secrets** (session key, scheduler token, Gemini key, Gmail app password) live in **Secret Manager**. None are in the repository.

"Let the model describe, let deterministic code decide."

## Measured

All numbers below come from our own runs on 2026-11-15.

- **The model never adds a number.** We ran the real summary path 20 times on the sample week with `gemini-3.1-flash-lite`. 18 replies passed the number check and were shown, 0 were rejected, and 2 timed out and fell back to the template. The median reply took 0.81 s. The check itself is tested with a fake model that invents a number (`tests/test_summary.py`).
- **From a missed dose to the whole family knowing: at most 65 minutes**, with the default rules: 60 minutes, plus up to 5 minutes until the next scheduler run. Families can shorten this under People & settings. The full sequence (giver reminded, then family told, nothing sent twice) is tested in `tests/test_api.py::test_missed_dose_escalates_by_email_exactly_once`.
- **Confirming a dose at the bedside takes one tap**, with no sign-in once the screen is set up.
- **We have no measured baseline** for how long a missed dose goes unnoticed in a family without Orbit. The way to get one is to ask caregiving families to log, for two weeks, each missed dose and when someone other than the giver first learned of it, then compare with Orbit's outbox times.

## Google services used

- **Cloud Run** hosts the app.
- **Firestore** stores the data.
- **Cloud Scheduler** runs the reminder checks.
- **Secret Manager** holds the secrets.
- **Cloud Build** builds the container from source.
- **Gemini API** (`gemini-3.1-flash-lite`) writes the summaries and suggests note tags.
- **Google Maps** links find nearby pharmacies and hospitals.
- **Google Calendar** links add visits to a calendar.

## Security

- Passcodes are hashed with salted scrypt and compared in constant time. Weak passcodes are refused, the orbit locks after 5 wrong tries, and sign-in and creation are rate-limited per address.
- An unknown orbit code and a wrong passcode get the same answer, so a guesser learns nothing.
- Every route checks the role. Doctors can only read. The bedside screen can only confirm a dose, answer "how are you" and press Help.
- Cookies are HttpOnly, Secure and SameSite=Strict. Every state-changing request also needs a custom header, which blocks cross-site request forgery.
- The Content-Security-Policy allows only the app's own scripts and styles; there is no inline script.
- All server text is inserted into pages with `textContent`, never as HTML.
- Request bodies are strict Pydantic models with length and pattern limits, and unknown fields are rejected. Email headers are stripped of line breaks.
- Sample orbits never send real email and are deleted after 24 hours. Each orbit also has a daily email cap.
- The container runs as a non-root user.

## Accessibility

- Bedside: very large targets, no reading needed, spoken prompts (Web Speech API, turned on once), a tablet-colour dot, and one question at a time.
- Semantic HTML with labels on every field, a skip link, keyboard-navigable tabs (arrow keys), visible focus rings, and `aria-live` for updates.
- High-contrast colours in both light and dark themes. The one accent colour (coral) always means "needs someone now".
- Respects reduced motion. Works at phone width without sideways scrolling.

## Run it locally

```bash
pip install -r requirements-dev.txt
ORBIT_COOKIE_SECURE=0 ORBIT_INPROCESS_TICK=1 uvicorn app.main:app --reload --port 8080
# open http://localhost:8080 and press "Open a sample family"
python -m pytest        # 52 tests
```

Without settings, data is kept in memory and emails stay in the in-app outbox. See `.env.example` for every setting.

## Deploy to Google Cloud

In Google Cloud Shell, from this folder: `gcloud config set project YOUR_PROJECT_ID` then `./deploy.sh`. The script turns on the APIs and creates the Firestore database. It gives the service account only the roles it needs, stores secrets in Secret Manager (it asks for the Gemini key and, optionally, a Gmail app password), deploys to Cloud Run, and creates the Cloud Scheduler job. It is safe to run again.

## Planned, not built

- **Smartwatch sync** (heart rate, falls, sleep): this needs each watch maker's API and a partnership.
- **Real phone calls and SMS** for Help and missed doses. Today Help sends email and shows tap-to-call buttons, because a web page cannot place a call by itself.
- **Booking an ambulance or a home visit through a provider's system.** Today it is a tap-to-call plus an emailed request to the saved doctor.
- **Voice answers from him** ("I took it", "I feel dizzy") for people who can speak a little.
- Several languages on the bedside screen.

## Repository layout

```
app/        FastAPI app: rules.py (all decisions), api.py (routes and roles), security.py,
            notify.py (emails exactly once), summary.py (Gemini, checked), store*.py (memory / Firestore)
static/     index.html (landing), circle.html (family, nurse, doctor), bedside.html (him)
tests/      52 tests: rules, security, API flows, the model check
deploy.sh   one-command Google Cloud deploy
```

Orbit is a prototype. It does not replace medical advice or emergency services. In an emergency, call 112.

MIT licence.
