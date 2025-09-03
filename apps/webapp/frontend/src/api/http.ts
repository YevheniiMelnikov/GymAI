import { t } from '../i18n/i18n';

export const API = {
  program: '/webapp/api/program/',
  programs: '/webapp/api/programs/',
  subscription: '/webapp/api/subscription/'
} as const;

let inflight: AbortController | null = null;

export async function getJSON<T>(url: string): Promise<{ ok: true; data: T } | { ok: false; status: number }> {
  if (inflight) inflight.abort();
  inflight = new AbortController();
  try {
    const resp = await fetch(url, { signal: inflight.signal });
    if (!resp.ok) return { ok: false, status: resp.status };
    const data = (await resp.json()) as T;
    return { ok: true, data };
  } catch (e: unknown) {
    if ((e as any)?.name === 'AbortError') return { ok: false, status: 0 };
    console.error('Fetch failed', e);
    return { ok: false, status: 500 };
  } finally {
    inflight = null;
  }
}

export function statusToMessage(status: number): string {
  if (status === 403) return t('unauthorized');
  if (status === 404) return t('not_found');
  if (status >= 500 || status === 0) return t('server_error');
  return t('unexpected_error');
}
