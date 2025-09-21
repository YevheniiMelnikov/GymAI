import { Locale, Program, ProgramResp, ProgramStructuredResponse } from './types';

const KNOWN_LOCALES: readonly Locale[] = ['en', 'ru', 'uk'];
const LOCALE_ALIASES: Record<string, Locale> = { ua: 'uk' };

function normalizeLocale(raw: string | null | undefined, fallback: Locale): Locale {
  if (!raw) return fallback;
  const lower = raw.toLowerCase();
  if (lower in LOCALE_ALIASES) {
    return LOCALE_ALIASES[lower];
  }
  if ((KNOWN_LOCALES as readonly string[]).includes(lower)) {
    return lower as Locale;
  }
  return fallback;
}

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
  const init: RequestInit = { credentials: 'include', ...options };
  const resp = await fetch(url, init);
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

function isStructuredProgram(data: ProgramResp): data is ProgramStructuredResponse {
  return typeof data === 'object' && data !== null && 'days' in data;
}

export async function getProgram(
  programId: string,
  opts: GetProgramOpts
): Promise<LoadedProgram>;
export async function getProgram(
  programId: string,
  locale: Locale,
  opts: GetProgramOpts
): Promise<LoadedProgram>;
export async function getProgram(
  programId: string,
  a: Locale | GetProgramOpts,
  b?: GetProgramOpts
): Promise<LoadedProgram> {
  let locale: Locale = 'en';
  let opts: GetProgramOpts;

  if (typeof a === 'string') {
    locale = a;
    opts = b as GetProgramOpts;
  } else {
    try {
      const tg = (window as any).Telegram?.WebApp;
      const lc = tg?.initDataUnsafe?.user?.language_code;
      if (lc && (['en', 'ru', 'uk'] as Locale[]).includes(lc)) {
        locale = lc as Locale;
      }
    } catch {
    }
    opts = a;
  }

  const params = new URLSearchParams({ locale, source: opts.source });
  if (programId) {
    params.set('program_id', programId);
  }
  const url = new URL('api/program/', window.location.href);
  params.forEach((value, key) => {
    url.searchParams.set(key, value);
  });
  const headers: Record<string, string> = {};
  if (opts.initData) headers['X-Telegram-InitData'] = opts.initData;

  const data = await getJSON<ProgramResp>(url.toString(), { headers, signal: opts.signal });

  const fromResponse = (data as { language?: string | null }).language;
  const resolvedLocale = normalizeLocale(fromResponse ?? (data as { locale?: string }).locale, locale);

  if (isStructuredProgram(data)) {
    const programLocale = normalizeLocale(data.locale, resolvedLocale);
    return {
      kind: 'structured',
      program: {
        ...data,
        locale: programLocale,
        created_at: data.created_at ?? null,
        weeks: data.weeks ?? [],
        days: data.days ?? []
      },
      locale: programLocale
    };
  }

  const createdAtRaw = data.created_at;
  let createdAt: string | null = null;
  if (typeof createdAtRaw === 'number') {
    createdAt = new Date(createdAtRaw * 1000).toISOString();
  } else if (typeof createdAtRaw === 'string') {
    createdAt = createdAtRaw;
  }

  return { kind: 'legacy', programText: data.program, locale: resolvedLocale, createdAt };
}
