import { Locale, Program, ProgramOrigin, ProgramResponse } from './types';
import { LANG_MAP, t } from '../i18n/i18n';

export const API = {
  program: '/webapp/api/program/',
  programs: '/webapp/api/programs/',
  subscription: '/webapp/api/subscription/'
} as const;

export class HttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
  }
}

export async function getJSON<T>(url: string): Promise<{ ok: true; data: T } | { ok: false; status: number }> {
  const controller = new AbortController();
  try {
    const resp = await fetch(url, { signal: controller.signal });
    if (!resp.ok) return { ok: false, status: resp.status };
    const data = (await resp.json()) as T;
    return { ok: true, data };
  } catch (error: unknown) {
    if ((error as { name?: string } | null)?.name === 'AbortError') {
      return { ok: false, status: 0 };
    }
    console.error('Fetch failed', error);
    return { ok: false, status: 500 };
  }
}

export function statusToMessage(status: number): string {
  if (status === 403) return t('unauthorized');
  if (status === 404) return t('not_found');
  if (status >= 500 || status === 0) return t('server_error');
  return t('unexpected_error');
}

type ProgramRequestOptions = {
  readonly initData?: string;
  readonly source?: 'subscription';
  readonly signal?: AbortSignal;
};

export type LoadedProgram =
  | {
      readonly kind: 'structured';
      readonly program: Program;
      readonly locale: Locale;
    }
  | {
      readonly kind: 'legacy';
      readonly programText: string;
      readonly locale: Locale;
      readonly createdAt?: string;
      readonly origin?: ProgramOrigin | null;
      readonly programId?: string | null;
    };

export async function getProgram(id: string, locale: Locale): Promise<LoadedProgram>;
export async function getProgram(
  id: string,
  locale: Locale,
  options: ProgramRequestOptions
): Promise<LoadedProgram>;
export async function getProgram(
  id: string,
  locale: Locale,
  options: ProgramRequestOptions = {}
): Promise<LoadedProgram> {
  const params = new URLSearchParams();
  if (options.initData) params.set('init_data', options.initData);
  if (id) params.set('program_id', id);
  params.set('locale', locale);
  const baseUrl = options.source === 'subscription' ? API.subscription : API.program;
  let resp: Response;
  try {
    resp = await fetch(`${baseUrl}?${params.toString()}`, { signal: options.signal });
  } catch (error) {
    if ((error as { name?: string } | null)?.name === 'AbortError') {
      throw error;
    }
    console.error('Failed to fetch program', error);
    throw new HttpError(500, statusToMessage(500));
  }
  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
  let payload: ProgramResponse | null = null;
  try {
    payload = (await resp.json()) as ProgramResponse;
  } catch (error) {
    console.error('Failed to parse program response', error);
    throw new HttpError(500, statusToMessage(500));
  }
  if (!payload?.program) {
    throw new HttpError(500, statusToMessage(500));
  }
  const resolvedLocale = resolveLocale(payload.language, locale);
  const program = payload.program;
  if (isStructuredProgram(program)) {
    return {
      kind: 'structured',
      program: {
        ...program,
        locale: program.locale ?? resolvedLocale
      },
      locale: program.locale ?? resolvedLocale
    };
  }
  const createdAt = normalizeLegacyDate(payload.created_at);
  return {
    kind: 'legacy',
    programText: program,
    locale: resolvedLocale,
    createdAt,
    origin: normalizeLegacyOrigin(payload.coach_type),
    programId: payload.program_id ? String(payload.program_id) : null
  };
}

function isStructuredProgram(value: unknown): value is Program {
  return Boolean(value && typeof value === 'object' && 'id' in (value as Record<string, unknown>));
}

function resolveLocale(raw: string | null | undefined, fallback: Locale): Locale {
  if (!raw) return fallback;
  return LANG_MAP[raw] ?? fallback;
}

function normalizeLegacyDate(input: number | string | null | undefined): string | undefined {
  if (typeof input === 'number' && Number.isFinite(input)) {
    return new Date(input * 1000).toISOString();
  }
  if (typeof input === 'string' && input) {
    const ms = Date.parse(input);
    if (!Number.isNaN(ms)) {
      return new Date(ms).toISOString();
    }
  }
  return undefined;
}

function normalizeLegacyOrigin(raw: string | null | undefined): ProgramOrigin | null {
  if (!raw) return null;
  if (raw === 'ai_coach') return 'ai';
  return 'coach';
}
