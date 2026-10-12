import { FormEvent, useState } from "react";

const EMAIL = /^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$/;

function addresses(value: string): string[] {
  const found: string[] = [];
  for (const part of value.split(/[\s,;]+/)) {
    const email = part.trim().toLowerCase();
    if (!email || found.includes(email)) continue;
    found.push(email);
  }
  return found;
}

export function EmailBox({ onSubmit }: { onSubmit: (emails: string) => void }) {
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const guests = addresses(value);
    if (!guests.length || guests.some((email) => !EMAIL.test(email))) {
      setProblem("Type normal email addresses, separated by commas.");
      return;
    }
    if (guests.length > 10) {
      setProblem("Add up to 10 guest emails.");
      return;
    }
    setProblem("");
    onSubmit(guests.join(", "));
  }

  return (
    <form className="email-box" onSubmit={submit}>
      <label htmlFor="guest-email">Guest emails</label>
      <div>
        <input
          id="guest-email"
          value={value}
          placeholder="one@company.com, two@company.com"
          onChange={(event) => setValue(event.target.value)}
          autoFocus
        />
        <button type="submit">Enter</button>
      </div>
      {problem ? <p className="banner error">{problem}</p> : null}
    </form>
  );
}
