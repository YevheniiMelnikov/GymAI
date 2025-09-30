export type LangCode = 'en' | 'ru' | 'uk';
export const LANG_MAP: Record<string, LangCode> = { eng: 'en', en: 'en', ru: 'ru', ua: 'uk', uk: 'uk' };

function resolveLangCode(raw?: string): LangCode {
  if (!raw) return 'en';
  const normalized = raw.toLowerCase();
  const direct = LANG_MAP[normalized];
  if (direct) return direct;
  const [base] = normalized.split('-');
  return LANG_MAP[base] ?? 'en';
}

export const fallbackEn = {
  history: 'History',
  created: 'Created',
  ai_label: 'AI',
  service_unavailable: 'Service temporarily unavailable',
  unauthorized: 'Unauthorized',
  not_found: 'Not found',
  server_error: 'Server error',
  unexpected_error: 'Unexpected error',
  no_programs: 'No programs found',
  sort_newest: 'Sort: Newest',
  sort_oldest: 'Sort: Oldest',
  show_ai: 'Show AI workout plans',
  back: 'Back',
  open_from_telegram: 'Open this page from Telegram.',
  'program.title': 'Workout Program',
  'program.created': 'Created: {date}',
  'program.view_history': 'History',
  'program.week': 'Week {n}',
  'program.day': 'Day {n} — {title}',
  'program.day.rest': 'Rest Day',
  retry: 'Retry',
  'page.program': 'Program',
  'page.history': 'History'
} as const;

export type TranslationKey = keyof typeof fallbackEn;
export type TemplateVars = Record<string, string | number>;

type Messages = Partial<Record<TranslationKey, string>>;
let messages: Messages = {};

async function loadMessages(code: LangCode): Promise<void> {
  const base = (window as any).__STATIC_PREFIX__ || '/static/';
  try {
    const res = await fetch(`${base}i18n/${code}.json`, { cache: 'no-store' });
    messages = res.ok ? ((await res.json()) as Messages) : { ...fallbackEn };
  } catch {
    messages = { ...fallbackEn };
  }
}

function interpolate(template: string, vars?: TemplateVars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = vars[key];
    return value === undefined || value === null ? '' : String(value);
  });
}

export function t<K extends TranslationKey>(key: K, vars?: TemplateVars): string {
  const template = messages[key] ?? fallbackEn[key];
  return interpolate(template, vars);
}

export async function applyLang(): Promise<LangCode>;
export async function applyLang(raw: string | undefined): Promise<LangCode>;
export async function applyLang(raw?: string): Promise<LangCode> {
  let incoming = raw;
  try {
    const tg = (window as any).Telegram?.WebApp;
    if (!incoming && tg?.initDataUnsafe?.user?.language_code) {
      incoming = tg.initDataUnsafe.user.language_code;
    }
  } catch {
  }

  const code = resolveLangCode(incoming);
  document.documentElement.lang = code;
  await loadMessages(code);
  return code;
}

export function formatDate(ts: number, locale: string): string {
  return new Date(ts * 1000).toLocaleDateString(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });
}
