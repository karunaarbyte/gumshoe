const KEY = 'gumshoe.admin';
let memory: string | null = null;

/** The admin token, for this tab only: sessionStorage (never localStorage, a cookie or a URL),
 * with memory as the fallback when storage is blocked. It is never logged. */
export function getAdminToken(): string | null {
  try {
    return sessionStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export function setAdminToken(token: string): void {
  memory = token;
  try {
    sessionStorage.setItem(KEY, token);
  } catch {
    // blocked storage: the memory copy is used
  }
}

export function clearAdminToken(): void {
  memory = null;
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // nothing to clear
  }
}
