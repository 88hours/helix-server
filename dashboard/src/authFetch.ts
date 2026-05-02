type TokenGetter = () => Promise<string>;
let _getToken: TokenGetter | null = null;

export function setTokenGetter(fn: TokenGetter) {
  _getToken = fn;
}

export async function getToken(): Promise<string | null> {
  if (!_getToken) return null;
  try { return await _getToken(); } catch { return null; }
}

export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  if (_getToken) {
    try {
      const token = await _getToken();
      init = {
        ...init,
        headers: { ...init.headers, Authorization: `Bearer ${token}` },
      };
    } catch {
      // proceed without auth — API will return 401 if token was required
    }
  }
  return fetch(url, init);
}
