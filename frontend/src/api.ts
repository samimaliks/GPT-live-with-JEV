const KEY = "sponsorship-session";

export function sessionId(): string {
  return sessionStorage.getItem(KEY) ?? "";
}

export function saveSession(id: string): void {
  sessionStorage.setItem(KEY, id);
}

export function clearSession(): void {
  sessionStorage.removeItem(KEY);
}

export async function fetchMe(): Promise<{ connected: boolean; email: string }> {
  const response = await fetch("/api/me", { headers: { "X-Session": sessionId() } });
  if (!response.ok) return { connected: false, email: "" };
  return response.json();
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", headers: { "X-Session": sessionId() } });
  clearSession();
}
