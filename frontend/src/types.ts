export type CalEvent = {
  id: string;
  title: string;
  start: string;
  end: string;
  allDay: boolean;
  guests: string[];
  decision?: "now" | "later";
  score?: number;
  choice?: number;
};

export type CalendarPhase = "idle" | "calling" | "ready" | "empty" | "error";
