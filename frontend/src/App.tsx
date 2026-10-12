import { useEffect, useRef, useState } from "react";
import { clearSession, fetchMe, logout, saveSession, sessionId } from "./api";
import { CallAudio } from "./audio";
import { CalendarBoard } from "./components/CalendarBoard";
import { EmailBox } from "./components/EmailBox";
import { Home } from "./components/Home";
import { WeatherCard, type WeatherPhase, type WeatherReading } from "./components/WeatherCard";
import type { CalendarPhase, CalEvent } from "./types";

export function App() {
  const [email, setEmail] = useState("");
  const [connected, setConnected] = useState(false);
  const [authError, setAuthError] = useState("");
  const [status, setStatus] = useState("Connect Google Calendar, then start the call.");
  const [you, setYou] = useState("");
  const [rep, setRep] = useState("");
  const [jev, setJev] = useState<string[]>([]);
  const [live, setLive] = useState(false);
  const [needGuests, setNeedGuests] = useState(false);
  const [eventDone, setEventDone] = useState(false);
  const [phase, setPhase] = useState<CalendarPhase>("idle");
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [calendarError, setCalendarError] = useState("");
  const [searching, setSearching] = useState(false);
  const [weatherPhase, setWeatherPhase] = useState<WeatherPhase>("idle");
  const [weatherCity, setWeatherCity] = useState("");
  const [weatherTemperature, setWeatherTemperature] = useState("");
  const [weatherConditions, setWeatherConditions] = useState("");
  const [weatherIcon, setWeatherIcon] = useState("");
  const [weatherError, setWeatherError] = useState("");
  const [weatherReadings, setWeatherReadings] = useState<WeatherReading[]>([]);
  const socket = useRef<WebSocket | null>(null);
  const audio = useRef<CallAudio | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session");
    const problem = params.get("auth_error");
    if (sid) saveSession(sid);
    if (problem) setAuthError(problem);
    if (sid || problem) window.history.replaceState({}, "", "/");
    void fetchMe().then((me) => {
      setConnected(me.connected);
      setEmail(me.email);
      if (me.connected) setStatus("Ready to start.");
    });
  }, []);

  function stopCall() {
    socket.current?.send(JSON.stringify({ type: "hangup" }));
    socket.current?.close();
    socket.current = null;
    audio.current?.stop();
    audio.current = null;
    setLive(false);
  }

  async function startCall() {
    if (!sessionId() || live) return;
    setYou("");
    setRep("");
    setJev([]);
    setNeedGuests(false);
    setEventDone(false);
    setSearching(false);
    setWeatherPhase("idle");
    setWeatherCity("");
    setWeatherTemperature("");
    setWeatherConditions("");
    setWeatherIcon("");
    setWeatherError("");
    setWeatherReadings([]);
    setStatus("Connecting. Use headphones so the mic does not hear the assistant.");
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${window.location.host}/api/call?session=${encodeURIComponent(sessionId())}`);
    ws.binaryType = "arraybuffer";
    socket.current = ws;
    const player = new CallAudio();
    audio.current = player;
    ws.onmessage = (message) => {
      if (message.data instanceof ArrayBuffer) {
        player.play(message.data);
        return;
      }
      const payload = JSON.parse(String(message.data)) as {
        type: string;
        text?: string;
        user?: string;
        agent?: string;
        line?: string;
        phase?: CalendarPhase | WeatherPhase | "searching" | "idle";
        events?: CalEvent[];
        error?: string;
        city?: string;
        temperature?: string;
        conditions?: string;
        icon?: string;
        open?: boolean;
      };
      if (payload.type === "status" || payload.type === "event_created") setStatus(payload.text ?? "");
      if (payload.type === "transcript") {
        setYou(payload.user ?? "");
        setRep(payload.agent ?? "");
      }
      if (payload.type === "jev" && payload.line) setJev((lines) => [...lines.slice(-12), payload.line!]);
      if (payload.type === "need_email") setNeedGuests(payload.open !== false);
      if (payload.type === "event_created") {
        setNeedGuests(false);
        setEventDone(true);
      }
      if (payload.type === "error") setStatus(payload.text ?? "Something went wrong.");
      if (payload.type === "calendar") {
        setPhase((payload.phase as CalendarPhase) ?? "ready");
        setEvents(payload.events ?? []);
        setCalendarError(payload.error ?? "");
      }
      if (payload.type === "weather") {
        const next = (payload.phase as WeatherPhase) ?? "calling";
        setWeatherPhase(next);
        setWeatherCity(payload.city ?? "");
        setWeatherError(payload.error ?? "");
        setWeatherTemperature(next === "ready" ? payload.temperature ?? "" : "");
        setWeatherConditions(next === "ready" ? payload.conditions ?? "" : "");
        setWeatherIcon(next === "ready" ? payload.icon ?? "" : "");
        if (next === "ready" && payload.city) {
          const reading: WeatherReading = {
            city: payload.city,
            temperature: payload.temperature ?? "",
            conditions: payload.conditions ?? "",
            icon: payload.icon ?? "",
          };
          setWeatherReadings((items) => [
            ...items.filter((item) => item.city.toLowerCase() !== reading.city.toLowerCase()),
            reading,
          ]);
        }
      }
      if (payload.type === "search") setSearching(payload.phase === "searching");
      if (payload.type === "closed") {
        setLive(false);
        setSearching(false);
        setStatus(payload.text ?? "Call ended.");
      }
    };
    ws.onclose = () => {
      setLive(false);
      player.stop();
    };
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("The call could not connect."));
    });
    try {
      await player.startMic((pcm) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(pcm);
      });
      setLive(true);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "The microphone could not start.");
      stopCall();
    }
  }

  async function disconnect() {
    stopCall();
    await logout();
    setConnected(false);
    setEmail("");
  }

  return (
    <main>
      <header className="top">
        <div>
          <p className="eyebrow">Personal agent</p>
          <h1>Your assistant</h1>
        </div>
        {connected ? (
          <div className="account">
            <span>{email}</span>
            <button type="button" onClick={() => void disconnect()}>
              Disconnect
            </button>
          </div>
        ) : (
          <a className="primary" href="/api/auth/google">
            Connect Google Calendar
          </a>
        )}
      </header>
      {authError ? <p className="banner error">{authError}</p> : null}
      {!connected ? <Home /> : (
        <>
          {needGuests && !eventDone ? (
            <EmailBox
              onSubmit={(guests) => {
                socket.current?.send(JSON.stringify({ type: "guests", emails: guests }));
                setStatus("Adding those guests to the event.");
              }}
            />
          ) : null}
          {eventDone ? <p className="banner ok">{status}</p> : null}
          <div className="workspace">
            <section className="call">
              <div className="call-top">
                <p className="eyebrow">Call</p>
                <span className={live ? "state on" : "state"}>{live ? "On call" : "Idle"}</span>
              </div>
              <div className="call-actions">
                <button type="button" className="primary" disabled={live} onClick={() => void startCall()}>
                  Start call
                </button>
                <button type="button" className="hangup" disabled={!live} onClick={stopCall}>
                  Hang up
                </button>
              </div>
              <p className="status">{status}</p>
              <div className="transcript">
                <article>
                  <h2>You</h2>
                  <p className={you ? undefined : "muted"}>{you || "No speech yet."}</p>
                </article>
                <article>
                  <h2>Assistant</h2>
                  <p className={rep ? undefined : "muted"}>{rep || "No speech yet."}</p>
                </article>
              </div>
              <div className="scores">
                <h2>Jev</h2>
                {jev.length ? <pre>{jev.join("\n")}</pre> : <p>Scores appear after someone speaks.</p>}
              </div>
            </section>
            <div className="beside">
              {searching ? <p className="search-line">Agent is searching the web</p> : null}
              <WeatherCard
                phase={weatherPhase}
                city={weatherCity}
                temperature={weatherTemperature}
                conditions={weatherConditions}
                icon={weatherIcon}
                error={weatherError}
                earlier={weatherReadings.filter((item) => item.city.toLowerCase() !== weatherCity.toLowerCase())}
              />
              <CalendarBoard phase={phase} events={events} error={calendarError} />
            </div>
          </div>
        </>
      )}
    </main>
  );
}
