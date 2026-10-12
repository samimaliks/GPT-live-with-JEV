export type WeatherPhase = "idle" | "calling" | "ready" | "error";

export type WeatherReading = {
  city: string;
  temperature: string;
  conditions: string;
  icon: string;
};

export type WeatherIconName = "clear" | "partly" | "cloud" | "fog" | "rain" | "snow" | "storm";

function WeatherGlyph({ name }: { name: WeatherIconName }) {
  if (name === "clear") {
    return (
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="32" cy="32" r="12" fill="#f9ab00" />
        <g stroke="#f9ab00" strokeWidth="3" strokeLinecap="round">
          <path d="M32 8v6M32 50v6M8 32h6M50 32h6M14.8 14.8l4.2 4.2M45 45l4.2 4.2M14.8 49.2l4.2-4.2M45 19l4.2-4.2" />
        </g>
      </svg>
    );
  }
  if (name === "partly") {
    return (
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="24" cy="22" r="9" fill="#f9ab00" />
        <g stroke="#f9ab00" strokeWidth="2.5" strokeLinecap="round">
          <path d="M24 6v4M24 34v4M10 22h4M34 22h4M13.5 11.5l2.8 2.8M31.7 29.7l2.8 2.8M13.5 32.5l2.8-2.8M31.7 14.3l2.8-2.8" />
        </g>
        <path
          d="M28 40h20a8 8 0 0 0 0-16 12 12 0 0 0-22.5 3.2A7 7 0 0 0 28 40z"
          fill="#fff"
          stroke="#5f6368"
          strokeWidth="2"
        />
      </svg>
    );
  }
  if (name === "rain") {
    return (
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <path
          d="M18 36h26a9 9 0 0 0 1.2-17.9A13 13 0 0 0 20.2 22 8 8 0 0 0 18 36z"
          fill="#fff"
          stroke="#5f6368"
          strokeWidth="2"
        />
        <g stroke="#1a73e8" strokeWidth="2.5" strokeLinecap="round">
          <path d="M24 42l-3 8M32 42l-3 8M40 42l-3 8" />
        </g>
      </svg>
    );
  }
  if (name === "snow") {
    return (
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <path
          d="M18 34h26a9 9 0 0 0 1.2-17.9A13 13 0 0 0 20.2 20 8 8 0 0 0 18 34z"
          fill="#fff"
          stroke="#5f6368"
          strokeWidth="2"
        />
        <g fill="#7aa2d6">
          <circle cx="24" cy="44" r="2" />
          <circle cx="32" cy="48" r="2" />
          <circle cx="40" cy="43" r="2" />
        </g>
      </svg>
    );
  }
  if (name === "storm") {
    return (
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <path
          d="M16 34h28a9 9 0 0 0 .8-17.9A13 13 0 0 0 18.4 20 8 8 0 0 0 16 34z"
          fill="#5f6368"
        />
        <path d="M34 32l-8 12h7l-3 10 12-14h-7l3-8z" fill="#f9ab00" />
      </svg>
    );
  }
  if (name === "fog") {
    return (
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <g stroke="#80868b" strokeWidth="3" strokeLinecap="round">
          <path d="M14 26h36M18 34h28M14 42h36M20 50h24" />
        </g>
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <path
        d="M16 40h30a10 10 0 0 0 1-19.9A14 14 0 0 0 18.6 24 9 9 0 0 0 16 40z"
        fill="#fff"
        stroke="#5f6368"
        strokeWidth="2"
      />
    </svg>
  );
}

function isIcon(value: string): value is WeatherIconName {
  return value === "clear" || value === "partly" || value === "cloud" || value === "fog" || value === "rain" || value === "snow" || value === "storm";
}

export function WeatherCard({
  phase,
  city,
  temperature,
  conditions,
  icon,
  error,
  earlier,
}: {
  phase: WeatherPhase;
  city: string;
  temperature: string;
  conditions: string;
  icon: string;
  error: string;
  earlier: WeatherReading[];
}) {
  if (phase === "idle") return null;
  const tone = phase === "ready" && isIcon(icon) ? icon : "cloud";

  return (
    <section className={`weather-card tone-${phase === "ready" ? tone : "pending"}`}>
      <header className="weather-band">
        <div>
          <p className="eyebrow">Current weather</p>
          <h2>{city || "Weather"}</h2>
        </div>
        {phase === "calling" ? <span className="pill">Agent is calling weather</span> : null}
      </header>
      {phase === "calling" ? (
        <div className="weather-main">
          <span className="weather-icon weather-icon-pending">
            <span className="spinner" />
          </span>
          <div>
            <p className="weather-cond">Looking up current conditions</p>
            <p className="weather-place">Temperature appears when the result comes back.</p>
          </div>
        </div>
      ) : null}
      {phase === "error" ? <p className="banner error">{error || "The weather could not be read."}</p> : null}
      {phase === "ready" ? (
        <div className="weather-main">
          <span className="weather-icon">
            <WeatherGlyph name={tone} />
          </span>
          <div>
            <p className="weather-temp">{temperature}</p>
            <p className="weather-cond">{conditions}</p>
          </div>
        </div>
      ) : null}
      {earlier.length ? (
        <ul className="weather-earlier">
          {earlier.map((item) => (
            <li key={item.city}>
              <span className="weather-mini">
                <WeatherGlyph name={isIcon(item.icon) ? item.icon : "cloud"} />
              </span>
              <strong>{item.city}</strong>
              <span>{item.temperature}</span>
              <span>{item.conditions}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
