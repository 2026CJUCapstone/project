// Storage partition only; server authorization must always validate the JWT.
export function getAuthOwner(): string {
  const token = typeof window === 'undefined' ? null : localStorage.getItem('authToken');
  if (!token) return 'guest';
  try {
    const encoded = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
    const { sub } = JSON.parse(new TextDecoder().decode(bytes));
    return typeof sub === 'string' && sub ? `account:${encodeURIComponent(sub)}` : 'invalid';
  } catch {
    return 'invalid';
  }
}

export function setAuthToken(token: string | null) {
  if (token) localStorage.setItem('authToken', token);
  else localStorage.removeItem('authToken');
  window.dispatchEvent(new Event('auth-identity-change'));
}

export function subscribeAuthIdentity(listener: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === 'authToken' || event.key === null) listener();
  };
  window.addEventListener('auth-identity-change', listener);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener('auth-identity-change', listener);
    window.removeEventListener('storage', onStorage);
  };
}
