# Scanner

Scanner is a Flutter app for capturing document pages, cropping and reviewing them, creating PDFs, reading saved documents, and asking questions about their contents. The connected version uses Supabase for accounts and private PDF storage, plus a Python/FastAPI backend for PDF text extraction, OCR, chat, summaries, notes, and quizzes.

There are two ways to run it:

| Mode | What you need | What works |
| --- | --- | --- |
| Demo | Flutter only | Explore the UI with local sample data; the Android/iOS app can use the device camera. No cloud account or AI processing. |
| Connected | Flutter, Supabase project, Python backend, OpenAI API key | Real accounts, private PDF uploads, document processing, and AI features. |

These commands use **PowerShell on Windows**. Open the `Scanner` folder in VS Code, then use **Terminal > New Terminal**. On this computer, the VS Code project is `C:\Users\ARUVINTEN RAMANATAHN\Dropbox\Scanner`; use that folder, not the similarly named OneDrive copy. Commands below assume the terminal starts at the project root unless they include `Set-Location`.

## 1. Prerequisites

- [Flutter SDK](https://docs.flutter.dev/get-started/install) on your `PATH` (this computer previously used `C:\Users\Public\flutter`); open a **new terminal** after changing `PATH`.
- Chrome for the web preview, or [Android Studio/Android SDK and a connected Android device](https://docs.flutter.dev/platform-integration/android/setup) for Android. Enable Developer options and USB debugging on a physical phone, and accept the phone's connection prompt.
- For the connected version only: Python 3 (the backend has been tested with Python 3.13), a [Supabase](https://supabase.com/docs/guides/getting-started/quickstarts/flutter) project, and an OpenAI API key.
- To build or run the iOS app, use a Mac with Xcode and Flutter. iOS builds cannot be made on Windows.

Check the tools before starting:

```powershell
flutter doctor
flutter devices
py -3 --version  # Only needed for the connected backend
```

Fix any relevant `flutter doctor` errors first. If Android licenses are pending, run `flutter doctor --android-licenses`.

## 2. Fastest start: demo mode

No Supabase project, `.env`, Python backend, or OpenAI key is needed.

```powershell
Set-Location "C:\Users\ARUVINTEN RAMANATAHN\Dropbox\Scanner\mobile"
flutter pub get
flutter run -d chrome --dart-define=DEMO_MODE=true
```

Keep the terminal open while the app runs. Press `r` for Flutter hot reload or `Ctrl+C` to stop it.

To try the **document camera**, use a connected Android phone or Android emulator with a usable camera instead of Chrome:

```powershell
flutter devices
flutter run -d YOUR_DEVICE_ID --dart-define=DEMO_MODE=true
```

Replace `YOUR_DEVICE_ID` with the ID listed by `flutter devices`. Allow camera access when prompted. Camera capture, cropping, page review, and PDF creation are native Android/iOS features; the Chrome preview does **not** provide camera scanning. On a Mac, the same `flutter run -d YOUR_IOS_DEVICE_ID --dart-define=DEMO_MODE=true` command can target a configured iPhone or iOS simulator.

## 3. Connected setup: create the database and private storage

1. Create a Supabase project and wait for it to finish provisioning.
2. In its Dashboard, open **SQL Editor**, create a new query, paste the entire contents of [`supabase/schema.sql`](supabase/schema.sql), and run it. Do not paste the SQL into a PowerShell terminal. The script creates the tables, access policies, and private `pdfs` Storage bucket.
3. Confirm the project's **Data API** is enabled for the `public` schema; the app needs the tables exposed with the grants and Row Level Security policies in the script. Do not disable RLS.
4. From the project's **Connect** dialog or **Settings > API Keys**, copy its project URL and publishable key. Copy a **secret** key separately for the backend. The publishable key goes into Flutter; the secret key must remain server-only. Supabase's [API-key guide](https://supabase.com/docs/guides/getting-started/api-keys) explains the difference.
5. If email confirmation is enabled in Supabase Auth, confirm the email address before signing in to the app.

Use a fresh project for first-time setup. The SQL file is the source of truth for this app's schema; do not substitute the sample SQL from a general Supabase tutorial.

## 4. Connected setup: configure and start the backend

Open **Terminal 1** at the project root:

```powershell
Set-Location "C:\Users\ARUVINTEN RAMANATAHN\Dropbox\Scanner\backend"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

In `backend/.env`, replace the example placeholders with your own values:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
SUPABASE_SECRET_KEY=YOUR_SERVER_SECRET_KEY
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
```

Keep the remaining settings from `.env.example` unless you need to change them. `SUPABASE_SECRET_KEY` and `OPENAI_API_KEY` are **never** Flutter `--dart-define` values. Do not commit or share `.env`. Because this project is in Dropbox, remember that Dropbox can sync `.env` even though Git ignores it; use a separate secret store for production.

Check configuration, then start the API in Terminal 1:

```powershell
.\.venv\Scripts\python.exe check_configuration.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

In another terminal, verify the local server:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

`/health` shows that the process is running. `/ready` should say `ready`; `not_configured` means a required key or URL is still missing. For optional read-only provider checks, run `.\.venv\Scripts\python.exe check_configuration.py --live` from `backend`. Development API documentation is at `http://127.0.0.1:8000/docs`. Leave Terminal 1 running while using the connected app.

## 5. Connected setup: start Flutter

Open **Terminal 2**:

```powershell
Set-Location "C:\Users\ARUVINTEN RAMANATAHN\Dropbox\Scanner\mobile"
flutter pub get
flutter devices
```

For an **Android emulator** running on the same computer, use its ID from `flutter devices`:

```powershell
flutter run -d YOUR_EMULATOR_ID `
  --dart-define=SUPABASE_URL=https://YOUR_PROJECT.supabase.co `
  --dart-define=SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY `
  --dart-define=API_BASE_URL=http://10.0.2.2:8000/api
```

`10.0.2.2` is the Android emulator's address for the host computer. Do not use it for a physical phone. If Android blocks the local HTTP connection under its network policy, use an HTTPS backend endpoint instead of disabling transport security for a release build.

For the **Chrome preview**, fix the web port so it matches the backend's default allowed origin (`http://localhost:5173`):

```powershell
flutter run -d chrome --web-port 5173 `
  --dart-define=SUPABASE_URL=https://YOUR_PROJECT.supabase.co `
  --dart-define=SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY `
  --dart-define=API_BASE_URL=http://127.0.0.1:8000/api
```

For a **physical Android phone or iPhone**, the phone cannot reach the computer's `127.0.0.1` or the emulator-only `10.0.2.2` address. Use a backend HTTPS URL reachable by the phone, and set `API_BASE_URL` to that URL ending in `/api`:

```powershell
flutter run -d YOUR_PHONE_ID `
  --dart-define=SUPABASE_URL=https://YOUR_PROJECT.supabase.co `
  --dart-define=SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY `
  --dart-define=API_BASE_URL=https://YOUR_BACKEND_DOMAIN/api
```

Do not send bearer tokens or document text over public cleartext HTTP. The Windows commands are for local development; hosting the backend securely for a phone requires HTTPS, proper network controls, and a server-side secret store. In any connected command, **omit** `--dart-define=DEMO_MODE=true`. If the Supabase URL or publishable key is missing, the client automatically enters demo mode.

## 6. Check the complete workflow

1. Register or sign in with an email and password. Confirm the email first if your Supabase project requires it.
2. Import a PDF. On Android/iOS, you can instead capture pages with the camera, crop/rotate them, review the pages, and create a PDF.
3. Wait for document processing to complete. Text PDFs are extracted locally by the backend; image-only pages may require OpenAI transcription.
4. Open the document, ask a question, or generate a summary, notes, or a quiz.

The client uploads PDFs to the private Supabase `pdfs` bucket. The backend processes the user's document and sends selected excerpts or scan images to OpenAI for AI features. Demo data is local and does not verify this connected workflow.

## 7. Run checks after changes

From `mobile`:

```powershell
flutter analyze
flutter test
```

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

The backend tests use synthetic documents and mocked providers; they do not require real credentials. See [`backend/README.md`](backend/README.md) for API endpoints, configuration details, and deployment limits.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `flutter` is not recognized | Open a new terminal after installing Flutter or use `C:\Users\Public\flutter\bin\flutter.bat` on this computer. Run `flutter doctor`. |
| No Android device appears | Enable USB debugging, accept the phone's prompt, install any needed USB driver, and rerun `flutter devices`. |
| `/ready` reports `not_configured` | Check `backend/.env` for real Supabase URL, publishable/secret keys, and OpenAI key. Restart the backend after editing it. |
| The app shows demo data unexpectedly | Supply both Flutter Supabase values and remove `DEMO_MODE=true`. |
| Sign-in or upload fails | Confirm the email, verify that Flutter and the backend use the same Supabase project, and ensure `supabase/schema.sql` was applied. Check that the Data API is enabled. |
| Browser reports a CORS error | Run Chrome with `--web-port 5173`, or add its exact origin to `ALLOWED_ORIGINS` in `backend/.env` and restart the backend. |
| A phone cannot reach the API | `127.0.0.1` refers to the phone itself; use a reachable HTTPS backend URL. |
| Camera is unavailable | Use the Android/iOS app and grant camera permission; Chrome does not support this app's native camera workflow. |
| AI processing fails | Check backend logs, `/ready`, provider availability, the OpenAI key/model, and the document's size/format. See `backend/README.md` for limits. |

## Project layout and security notes

- [`mobile/`](mobile/) — Flutter UI, document camera, PDF reader, and Supabase/API clients.
- [`backend/`](backend/) — FastAPI routes, PDF extraction/OCR, retrieval, AI services, and tests.
- [`supabase/schema.sql`](supabase/schema.sql) — PostgreSQL schema, ownership policies, grants, and private storage bucket.

The backend limits document size and processing work, verifies user tokens and document ownership, and avoids logging document contents or credentials. OpenAI requests disable response storage, but provider policies may still apply. Do not ship the Supabase secret key or OpenAI API key in the app, commit `.env`, expose the development API publicly, or assume demo mode tests cloud security. Review [`backend/README.md`](backend/README.md) before deployment.
