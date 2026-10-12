const points = [
  ["Call", "You speak with your assistant."],
  ["Calendar", "Ask what is already booked. Jev marks one event to attend now."],
  ["Event", "Give the title, day, time, and length. Type guest emails only if you ask to add guests."],
  ["Weather", "Name a place. The card shows that reading."],
  ["Search", "Ask a current question. The page looks it up on the web."],
  ["Scores", "Jev shows the call scores beside the transcript."],
];

export function Home() {
  return (
    <section className="home">
      <div className="home-intro">
        <h2>Your assistant</h2>
        <p>Connect your Google Calendar, then start the call. Use headphones. Say bye to end.</p>
      </div>
      <ul>
        {points.map(([title, text]) => (
          <li key={title}>
            <strong>{title}</strong>
            <span>{text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
