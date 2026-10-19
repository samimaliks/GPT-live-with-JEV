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

function jevTag(event: CalEvent): { percent: number; short: string; full: string } | null {
  if (event.decision === "now") {
    const percent = Math.round((event.choice ?? event.score ?? 0) * 100);
    return { percent, short: "Now", full: `Attend now ${percent}%` };
  }
  if (event.decision === "later") {
    const percent = Math.round((event.score ?? 0) * 100);
    return { percent, short: "Later", full: `Attend later ${percent}%` };
  }
  return null;
}

function JevTag({ event }: { event: CalEvent }) {
  const tag = jevTag(event);
  if (!tag) return null;
  return (
    <span className="jev-tag" title={tag.full}>
      <b>{tag.percent}%</b> {tag.short}
    </span>
  );
}

/** Split width only among events that overlap in time; non-overlapping events use full width. */
function layoutDayEvents(dayEvents: CalEvent[]) {
  const span = (HOUR_END - HOUR_START) * 60;
  const items = dayEvents
    .map((event) => {
      const start = parseWhen(event.start);
      const end = parseWhen(event.end);
      const startMinutes = start.getHours() * 60 + start.getMinutes();
      const endMinutes = Math.max(end.getHours() * 60 + end.getMinutes(), startMinutes + 30);
      return { event, startMinutes, endMinutes };
    })
    .sort((a, b) => a.startMinutes - b.startMinutes || a.endMinutes - b.endMinutes);

  const colEnds: number[] = [];
  const placed = items.map((item) => {
    let col = colEnds.findIndex((end) => end <= item.startMinutes);
    if (col === -1) {
      col = colEnds.length;
      colEnds.push(item.endMinutes);
    } else {
      colEnds[col] = item.endMinutes;
    }
    return { ...item, col };
  });

  return placed.map((item) => {
    const overlapping = placed.filter(
      (other) => other.startMinutes < item.endMinutes && other.endMinutes > item.startMinutes,
    );
    const cols = Math.max(...overlapping.map((other) => other.col), item.col) + 1;
    const top = Math.max(0, ((item.startMinutes - HOUR_START * 60) / span) * 100);
    const height = Math.min(100 - top, ((item.endMinutes - item.startMinutes) / span) * 100);
    return {
      event: item.event,
      top,
      height,
      left: (item.col / cols) * 100,
      width: 100 / cols,
    };
  });
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
                    <JevTag event={event} />
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
                {layoutDayEvents(
                  events.filter((event) => !event.allDay && sameDay(parseWhen(event.start), day)),
                ).map(({ event, top, height, left, width }) => (
                  <article
                    key={event.id}
                    className={event.decision === "now" ? "event now" : "event later"}
                    style={{
                      top: `${top}%`,
                      height: `${Math.max(height, 10)}%`,
                      left: `${left}%`,
                      width: `calc(${width}% - 4px)`,
                      marginLeft: "2px",
                    }}
                    title={event.guests.join(", ")}
                  >
                    <strong>{event.title}</strong>
                    <JevTag event={event} />
                  </article>
                ))}
              </div>
            </div>
          ))}
        </div>
        {(() => {
          const weekEnd = addDays(days[0], 14);
          const outside = events.filter((event) => {
            const start = parseWhen(event.start);
            if (Number.isNaN(start.getTime())) return false;
            if (days.some((day) => sameDay(start, day))) return false;
            // Keep near-term overflow only; skip far-future birthdays years out.
            return start < weekEnd;
          });
          if (!outside.length) return null;
          return (
            <div className="outside">
              {outside.map((event) => (
                <article key={event.id} className={event.decision === "now" ? "block now" : "block later"}>
                  <strong>{event.title}</strong>
                  <JevTag event={event} />
                  <em style={{ fontSize: 10, opacity: 0.9 }}>{event.start}</em>
                </article>
              ))}
            </div>
          );
        })()}
      </div>
    </section>
  );
}
