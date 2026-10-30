# KrushiSarthi

Early warning for crop pests, diseases and weather threats. A mobile-first web app (installable on the phone) with a Python backend.

**What is inside**

| Feature | Where it lives |
|---|---|
| Login, many farms per account | Clerk (login) and `backend/app/main.py` |
| Draw the farm on a map, pick crop and sowing date | `frontend/src/pages/Farms.jsx`, `components/DrawMap.jsx` |
| Satellite growth (NDVI, moisture, chlorophyll) vs the expected curve | `backend/app/satellite.py` (Google Earth Engine, Sentinel-2) |
| Weather and weather-linked threat alerts | `backend/app/weather.py` (Open-Meteo), `alerts.py` |
| Why growth is low (checks weather, water, soil and photos together) | `backend/app/diagnosis.py` |
| **Weekly photo checkup panel, 30 to 40 photos** | `frontend/src/pages/Checkup.jsx`, backend `/api/checkups` |
| Leaf scan, weekly photo analysis and soil report reading | `backend/app/vision.py` (same AI provider as the chat) |
| AI assistant, voice, Hindi and Marathi | `backend/app/assistant.py`, `pages/Assistant.jsx` |
| Notifications: in-app list, phone push, weekly reminder | `backend/app/push.py`, `jobs.py`, `frontend/public/sw.js` |

## 1. Run it now (no keys needed)

You need Python 3.10 or newer.

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate        Mac/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open http://localhost:8000. The app is already built (it is in `backend/static`).

With no keys it runs in **demo mode**: login is skipped, satellite and weather data are simulated, photo results are simulated, and the assistant is a basic helper. Everything else is real.

**Demo tip:** add a farm, pick a *Demo data pattern* (for example "Low nitrogen after heavy rain") and a sowing date 45 to 60 days ago. The satellite chart dips below the expected curve and the app explains why. Then open Alerts and tap "Run daily check now" to create alerts. Try the Checkup tab: start a checkup, then use "Add several photos at once" to add 30 photos.

Check the backend any time with `python scripts/smoke_test.py`.

## 2. Add your keys

Copy `backend/.env.example` to `backend/.env` and fill in the lines below. Restart `python run.py` after each change. Keys go only in this file, never in the frontend.

### Step 1: Login (Clerk)
1. Go to clerk.com, create an application, and choose the sign-in methods you want (phone or email).
2. Open **API keys** and copy the **Publishable key** (it starts with `pk_test_`).
3. Put it in `.env`: `CLERK_PUBLISHABLE_KEY=pk_test_...`
4. Restart. The app now shows the Clerk sign-in screen, and every farm belongs to the signed-in user.

You do not need the Clerk secret key. The backend checks the login token with the public keys that Clerk publishes for your app.

### Step 2: Satellite (Google Earth Engine)
Use the Cloud project you registered as non-commercial. Keep it for the hackathon and demo only (see the licensing note in section 5).
1. In Google Cloud Console, open that project and make sure the **Earth Engine API** is enabled.
2. Put the project ID in `.env`: `EE_PROJECT=your-project-id`
3. Pick one:
   - **On your laptop:** run `earthengine authenticate` once (the library is already in requirements). Leave the next two settings empty.
   - **On a server:** in IAM, create a service account and give it the roles **Service Usage Consumer** and **Earth Engine Resource Viewer**. Create a JSON key and save it as `backend/ee-key.json`. Then set `EE_SERVICE_ACCOUNT=name@your-project.iam.gserviceaccount.com` and `EE_KEY_FILE=./ee-key.json`.
4. Restart. The hero card on Home changes from "Demo satellite data" to "Sentinel-2 satellite". If Earth Engine fails, the app keeps working with demo data and shows the error on that card.

The app reads one Sentinel-2 value per pass for the whole farm (cheap on the free quota) and caches it for 12 hours.

### Step 3: Weather (Open-Meteo)
Nothing to add. It needs no key and works as soon as the server has internet. If it cannot reach the service, it shows sample weather and says so on the card. Open-Meteo is free for non-commercial use only.

### Step 4: AI assistant, leaf scan and soil report reading
One AI provider powers everything: the assistant chat, the leaf scan, the 30 to 40 weekly checkup photos, and soil-report reading. You need only one key.

**Option A, Claude:** create an API key at platform.claude.com, add credit, and set `ANTHROPIC_API_KEY=sk-ant-...` in `.env`. Restart.

**Option B, Gemini or another OpenAI-compatible provider:**
```
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_API_KEY=your key from Google AI Studio
LLM_MODEL=a current Gemini model name from Google's model list
```
The model must support **tool calling** (for the chat) and **image input** (for the photo features). To use a cheaper model for the 30 to 40 weekly photos, set `LLM_TRIAGE_MODEL`. To use a different model for scans and soil reports, set `LLM_VISION_MODEL`. Other examples (OpenAI, a local Ollama model) are in `.env.example`. Reasoning ("thinking") models can use up the answer budget on thinking and return nothing. If photo results show an error about an empty reply, choose a non-reasoning model for `LLM_VISION_MODEL` and `LLM_TRIAGE_MODEL`.

**Check your setup with real calls:** `python scripts/check_ai.py` (it prints PASS or FAIL for each step).

#### What the assistant does
- Answers open agriculture questions in English, Hindi or Marathi, using the model's general knowledge, and says when an answer is general knowledge.
- **Searches a knowledge base** of documents you ingest (below) and cites passages as numbered sources. The citation numbers are checked by the server: a source the model did not really retrieve is removed from the answer.
- **Calls tools** for this farm only: farm profile, weather forecast and history, satellite status, soil test, diagnosis, photo checkups and scans, alerts, and the small built-in crop reference. The chat screen shows which tools were used and which failed.
- Says plainly when no source was found, when a tool failed, and when data is simulated demo data.
- Asks a follow-up question when key information is missing, and never invents pesticide names or doses.

#### Add trusted documents (the knowledge base)
The assistant is only as well grounded as the documents you give it. Add official material from ICAR, state agricultural universities, Krishi Vigyan Kendras and the state agriculture department. Only add material you are allowed to use.
```bash
cd backend
python scripts/ingest.py --url https://LINK-TO-A-PDF-OR-PAGE --title "Title" --publisher "Who published it" --published 2023-06 --crops cotton
python scripts/ingest.py --file kb/my-document.pdf --title "Title" --publisher "Publisher" --url https://where-it-came-from
python scripts/ingest.py --manifest kb/sources.json     # many at once, see kb/sources.example.json
python scripts/ingest.py --list                         # what is loaded
python scripts/ingest.py --delete 3                     # remove one
```
PDFs, web pages and text files work. Scanned PDFs without a text layer are rejected, so run OCR first. Each passage keeps its title, publisher, date, link and page number, and the chat shows them.

Search is keyword-based (SQLite) with no extra setup. For meaning-based search, which helps when the farmer asks in Hindi or Marathi, set `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL` and `EMBEDDING_API_KEY` (any OpenAI-compatible embeddings API), then ingest again. The model writes English search queries itself, so keyword search already works for most Hindi and Marathi questions about documents written in English.

#### Run the tests
```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```
The tests cover ordinary questions, follow-ups, retrieval, fake citations, missing sources, tool failures, provider errors, rate limits, and the existing farm features. They replace only the model API with a scripted stand-in. Everything else (database, search, tools, parsing) is real.

### Step 5: Notifications
In-app alerts work without setup. For phone notifications when the app is closed:
1. Run `python scripts/gen_vapid.py` and paste the two lines it prints into `.env`.
2. Set `VAPID_SUBJECT=mailto:you@your-email.com`.
3. Restart, open the app on the phone, go to **Alerts**, tap **Turn on notifications**, then **Send a test**.

Phone push needs HTTPS (see section 3). On iPhone, first add the app to the Home Screen (Share, then Add to Home Screen) and open it from there.

The server checks every farm each morning at 7:00 India time for weather warnings, growth below normal, and the weekly checkup reminder on the day the farmer chose. On hosting that goes to sleep, call `https://YOUR-APP/api/cron/run?key=YOUR_SECRET` once a day from a free cron service and set `CRON_SECRET=YOUR_SECRET`.

## 3. Use it on a phone

Camera, location, voice and push only work on **HTTPS** (or localhost). Two easy ways:
- **Quick test:** run a tunnel, for example `cloudflared tunnel --url http://localhost:8000`, and open the https link on the phone.
- **Deploy:** any host that runs Python works (Render, Railway, a small VPS). Build command `pip install -r backend/requirements.txt`, start command `cd backend && python run.py`. Set the `.env` values as environment variables, set `APP_ENV=production`, and keep `DATA_DIR` on a persistent disk (it holds the database and photos).

Open the site on the phone and choose **Add to Home Screen** to install it.

## 4. Change the frontend

The built app is in `backend/static`. To edit the screens:
```bash
cd frontend
npm install
npm run dev        # live preview on http://localhost:5173 (needs the backend running)
npm run build      # rebuilds and copies into backend/static
```

## 5. Things to know (be honest with judges)

- **Calibrate before real use.** The expected growth curves (`app/data/crops.json`), weather thresholds (`alerts.py`), soil ratings and diagnosis scores (`diagnosis.py`) are sensible starting values, not validated agronomy. Replace them with values from your state agriculture university and IMD agromet advisories.
- **Treatment advice** comes from `app/data/knowledge.json` and has no pesticide names or doses on purpose. Extend it with advice reviewed by an agronomist.
- **Satellite is near real time, not live.** Sentinel-2 revisits about every 5 days and clouds block it. Radar (Sentinel-1) would help in the monsoon.
- **Photo AI can be wrong.** The app shows confidence and sends low-confidence cases to the agriculture officer.
- **Priority spots** in the weekly checkup come from the lowest-NDVI pixels when Earth Engine is connected. In demo mode they are simulated.
- **Alert texts** are in English. The assistant and the main screen labels follow the chosen language.
- **Farm monitoring covers six crops** (soybean, cotton, wheat, rice, maize, tomato) because the growth curves are built in. The assistant itself can answer questions about any crop. Adding a crop to monitoring means adding a curve to `app/data/crops.json`.
- **Weather history** uses the Open-Meteo archive, which lags real time by about two days.
- **The assistant can be wrong.** Citations prove which passage was retrieved, not that the model summarised it perfectly. Open the source from the chat to check.
- **Licensing.** Earth Engine non-commercial use fits a hackathon prototype. If you start charging farmers, move to a commercial Earth Engine project or switch `satellite.py` to another Sentinel-2 source. Open-Meteo's free tier is also non-commercial.
- **Database.** SQLite is fine for a demo. Move to PostgreSQL for many users.
