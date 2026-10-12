import type { CalendarPhase, CalEvent } from "../types";

const HOUR_START = 7;
const HOUR_END = 21;
const HOURS = Array.from({ length: HOUR_END - HOUR_START }, (_, index) => HOUR_START + index);

function parseWhen(value: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T00:00:00`);
  return new Date(value);
}

function mondayOf(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  const weekday = copy.getDay();
  const shift = weekday === 0 ? -6 : 1 - weekday;
  copy.setDate(copy.getDate() + shift);
  return copy;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function headerMonth(days: Date[]): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const inWeek = days.find((day) => sameDay(day, today));
  const first = days[0];
  const last = days[days.length - 1];
  const focus = inWeek ?? days[3] ?? first;

  if (first.getMonth() !== last.getMonth() || first.getFullYear() !== last.getFullYear()) {
    if (inWeek) {
      return inWeek.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    }
    const left = first.toLocaleDateString(undefined, {
      month: "long",
      ...(first.getFullYear() !== last.getFullYear() ? { year: "numeric" as const } : {}),
    });
    const right = last.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    return `${left} – ${right}`;
  }

  return focus.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function hourLabel(hour: number): string {
  const suffix = hour < 12 ? "AM" : "PM";
  const value = hour % 12 || 12;
  return `${value} ${suffix}`;
}

function label(event: CalEvent): string {
  if (event.decision === "now") {
    const score = Math.round((event.choice ?? event.score ?? 0) * 100);
    return `Attend now ${score}%`;
  }
  if (event.decision === "later") {
    return `Attend later ${Math.round((event.score ?? 0) * 100)}%`;
  }
  return "";
}

export function CalendarBoard({
  phase,
  events,
  error,
}: {
  phase: CalendarPhase;
  events: CalEvent[];
  error: string;
}) {
  const today = new Date();
  const firstEvent = events.length ? parseWhen(events[0].start) : today;
  const anchor = Number.isNaN(firstEvent.getTime()) ? today : firstEvent;
  // Prefer this week when any loaded event lands in it; otherwise follow the first event.
  const thisWeek = mondayOf(today);
  const eventWeek = mondayOf(anchor);
  const week =
    events.length === 0 ||
    events.some((event) => {
      const start = parseWhen(event.start);
      if (Number.isNaN(start.getTime())) return false;
      const day = new Date(start);
      day.setHours(0, 0, 0, 0);
      return day >= thisWeek && day < addDays(thisWeek, 7);
    })
      ? thisWeek
      : eventWeek;
  const days = Array.from({ length: 7 }, (_, index) => addDays(week, index));
  const month = headerMonth(days);

  return (
    <section className="calendar">
      <header className="calendar-head">
        <div>
          <p className="eyebrow">Google Calendar</p>
          <h2>{month}</h2>
        </div>
        {phase === "calling" ? <span className="pill">Agent is calling calendar</span> : null}
      </header>
      <div className={`calendar-frame ${phase === "calling" ? "is-calling" : ""}`}>
        {phase === "calling" ? (
          <div className="calling">
            <span className="spinner" />
            <strong>The agent is calling Google Calendar</strong>
            <p>Events will appear here when the results come back.</p>
          </div>
        ) : null}
        {phase === "error" ? <p className="banner error">{error || "The calendar could not be read."}</p> : null}
        {phase === "empty" ? <p className="banner">No upcoming events on this calendar.</p> : null}
        {error && phase === "ready" ? <p className="banner error">{error}</p> : null}
        <div className="all-day">
          <span>All day</span>
          {days.map((day) => (
            <div key={day.toISOString()}>
              {events
                .filter((event) => event.allDay && sameDay(parseWhen(event.start), day))
                .map((event) => (
                  <article key={event.id} className={event.decision === "now" ? "block now" : "block later"}>
                    <strong>{event.title}</strong>
                    <em>{label(event)}</em>
                  </article>
                ))}
            </div>
          ))}
        </div>
        <div className="week">
          <div className="hours">
            <div />
            {HOURS.map((hour) => (
              <div key={hour}>{hourLabel(hour)}</div>
            ))}
          </div>
          {days.map((day) => (
            <div className="day" key={day.toISOString()}>
              <header>
                <span>{day.toLocaleDateString(undefined, { weekday: "short" })}</span>
                <strong>{day.getDate()}</strong>
              </header>
              <div className="slots">
                {HOURS.map((hour) => (
                  <div key={hour} className="slot" />
                ))}
                {events
                  .filter((event) => !event.allDay && sameDay(parseWhen(event.start), day))
                  .map((event, index, dayEvents) => {
                    const start = parseWhen(event.start);
                    const end = parseWhen(event.end);
                    const startMinutes = start.getHours() * 60 + start.getMinutes();
                    const endMinutes = Math.max(end.getHours() * 60 + end.getMinutes(), startMinutes + 30);
                    const span = (HOUR_END - HOUR_START) * 60;
                    const top = Math.max(0, ((startMinutes - HOUR_START * 60) / span) * 100);
                    const height = Math.min(100 - top, ((endMinutes - startMinutes) / span) * 100);
                    const width = 100 / dayEvents.length;
                    return (
                      <article
                        key={event.id}
                        className={event.decision === "now" ? "event now" : "event later"}
                        style={{
                          top: `${top}%`,
                          height: `${Math.max(height, 8)}%`,
                          left: `${index * width}%`,
                          width: `${width}%`,
                        }}
                        title={event.guests.join(", ")}
                      >
                        <strong>{event.title}</strong>
                        <em>{label(event)}</em>
                      </article>
                    );
                  })}
              </div>
            </div>
          ))}
        </div>
        {events.filter((event) => !days.some((day) => sameDay(parseWhen(event.start), day))).length ? (
          <div className="outside">
            {events
              .filter((event) => !days.some((day) => sameDay(parseWhen(event.start), day)))
              .map((event) => (
                <article key={event.id} className={event.decision === "now" ? "block now" : "block later"}>
                  <strong>{event.title}</strong>
                  <em>
                    {label(event)} {event.start}
                  </em>
                </article>
              ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
