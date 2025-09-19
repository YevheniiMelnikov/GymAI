import { Locale, Program } from './types';

export class HttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function statusToMessage(status: number): string {
  switch (status) {
    case 401:
    case 403:
      return 'unauthorized';
    case 404:
      return 'not_found';
    case 500:
      return 'server_error';
    default:
      return 'unexpected_error';
  }
}

export type LoadedProgram =
  | { kind: 'structured'; program: Program; locale: Locale }
  | { kind: 'legacy'; programText: string; locale: Locale; createdAt?: string | null };

export async function getJSON<T>(url: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
  return (await resp.json()) as T;
}

type GetProgramOpts = {
  initData: string;
  source: 'direct' | 'subscription';
  signal?: AbortSignal;
};

export async function getProgram(
  programId: string,
  locale: Locale,
  opts: GetProgramOpts
): Promise<LoadedProgram> {
  const url = `/api/program/${encodeURIComponent(programId)}?locale=${locale}&source=${opts.source}`;
  const headers: Record<string, string> = {};
  if (opts.initData) headers['X-Telegram-InitData'] = opts.initData;

  const data = await getJSON<any>(url, { headers, signal: opts.signal });

  if (typeof data === 'string') {
    return { kind: 'legacy', programText: data, locale, createdAt: null };
  }
  return { kind: 'structured', program: data as Program, locale };
}
