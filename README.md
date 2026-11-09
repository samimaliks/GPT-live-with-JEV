# Personal agent

A local page for a live personal assistant. You speak. gpt-live-1 is the assistant. The page can read that person's Google Calendar, look up weather, and search the web.

Open the page at [http://localhost:5173](http://localhost:5173). Do not start the old Streamlit app in `legacy/`.

## What you need

- Python 3.11 or newer
- Node.js 20 or newer
- An OpenAI API key with credits (the live call and web search)
- An OpenRouter API key (Jev scores and calendar ranking). A TypeSafe key works instead.
- A Google Cloud OAuth client (Calendar sign-in)

Weather uses Open-Meteo and does not need a key.

Use headphones. The microphone will hear the assistant through the speakers. Voice time bills at $0.05 per minute.

**Detailed instructions:** [Setup guide](https://docs.google.com/document/d/1t-2q9RuiZwg_9cx0P--rdr-YLwraKR4BeMePAmkl6fE/edit?tab=t.bja0r44sjema)


## Setup

From the repo root (Windows, macOS, or Linux):

```bash
python -m venv venv
python -m pip install -r requirements.txt
npm install
npm install --prefix frontend
cp .env.example .env
```

On Windows, use `copy .env.example .env` instead of `cp`. Use the venv’s Python for `pip` if your shell does not pick it up automatically (for example `venv\\Scripts\\python.exe -m pip install -r requirements.txt`).

Fill in `.env`:

```text
OPENAI_API_KEY=sk-your-key-here
OPENROUTER_API_KEY=sk-or-v1-your-key-here
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

`TYPESAFE_API_KEY` can replace `OPENROUTER_API_KEY`. Jev uses OpenRouter and `jev-1.13` when that key is set.

### Google OAuth

In Google Cloud, create a Web application OAuth client and enable the Google Calendar API.

Authorized redirect URI:

```text
http://localhost:8000/api/auth/google/callback
```


## Run

```bash
npm run dev
```

That starts FastAPI on port 8000 and the Vite page on port 5173. The page proxies `/api` to the API, including the call WebSocket.

1. Open [http://localhost:5173](http://localhost:5173).
2. Choose **Connect Google Calendar** and sign in with the Google account whose calendar the call should read.
3. Choose **Start call**. The assistant speaks first.

If port 5173 is already taken, Vite prints another port. Use that URL. The API still has to be on port 8000, because the OAuth redirect and the Vite proxy both point there.

Stop the process with Ctrl+C.

## What the page does

- **Call.** The assistant follows `backend/app/prompt.py`. It does not invent a calendar event, a weather reading, or a search result.
- **Calendar.** A list question loads that user's upcoming events, then Jev marks one to attend now. A create request asks for the title, day, time, and length, then adds the event to that calendar. Guest emails are asked for only when the user wants guests, and only by typing them into the box.
- **Weather.** A weather question looks the named place up with Open-Meteo. Karachi is used only when no place is named. Several places update the card one after another.
- **Web search.** Other current questions go to `gpt-5.6-luna` with OpenAI web search. That needs `OPENAI_API_KEY` and credits. It is not used for weather.
- **Jev.** Transcript scores show on the page. They do not change what the assistant says and they do not send invites.

Call behavior for people changing this product is in `.cursor/skills/personal-agent/SKILL.md`.

## Layout

| Path | What it is |
| --- | --- |
| `frontend/src/` | Vite page. Calendar, weather card, and email box are in `components/`. |
| `backend/app/` | FastAPI: Google sign-in, calendar, Jev, weather, and the live voice bridge. |
| `legacy/` | Old microphone script and Streamlit page. Do not start new work here. |
| `data/tokens/` | One Google refresh token per signed-in account. |
| `.env` | Local keys. Never commit this file. |

## Troubleshooting

- **`OPENAI_API_KEY` is missing.** The call socket checks `.env` in the repo root. Restart `npm run dev` after changing it.
- **Google sign-in fails.** The OAuth client must use `http://localhost:8000/api/auth/google/callback`. Calendar API must be enabled.
- **The page loads and the call does not.** Confirm the API log says Uvicorn is on port 8000. The browser talks to port 5173, which forwards `/api` to 8000.
- **Jev stays empty.** Put `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY` in `.env` and restart.
