export async function api<T>(
  path: string,
  options?: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    signal,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {
      /* HTTP error without JSON */
    }
    throw new Error(message);
  }
  return response.json();
}
export function params(values: Record<string, string | number>) {
  return new URLSearchParams(
    Object.entries(values).map(([k, v]) => [k, String(v)]),
  ).toString();
}
