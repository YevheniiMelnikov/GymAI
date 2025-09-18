// Language mapping and i18n loader
// Accept legacy values we may get from backend: eng, ru, ua, en, ru, uk

export type LangCode = 'en' | 'ru' | 'uk';
export const LANG_MAP: Record<string, LangCode> = { eng: 'en', en: 'en', ru: 'ru', ua: 'uk', uk: 'uk' };

let messages: Record<string, string> = {};
export const fallbackEn: Record<string, string> = {
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
  retry: 'Retry',
  'program.title': 'Workout Program',
  'program.created': 'Created: {date}',
  'program.origin.ai': 'AI',
  'program.origin.coach': 'Coach',
  'program.week': 'Week {n}',
  'program.day': 'Day {n}: {title}',
  'program.day.rest': 'Rest',
  'program.view_history': 'View History',
  'program.ex.sets_reps': '{sets} × {reps}',
  'program.ex.weight': '{w} {unit}',
  'program.ex.bodyweight': 'Bodyweight',
  'program.ex.more': 'Details',
  'program.ex.unit.kg': 'kg',
  'program.ex.unit.lb': 'lb'
};

async function loadMessages(code: LangCode): Promise<void> {
  const base = (window as any).__STATIC_PREFIX__ || '/static/';
  try {
    const res = await fetch(`${base}i18n/${code}.json`, { cache: 'no-store' });
    messages = res.ok ? await res.json() : fallbackEn;
  } catch {
    messages = fallbackEn;
  }
}

export type TemplateParams = Record<string, string | number>;

export function t<K extends keyof typeof fallbackEn>(key: K, params?: TemplateParams): string {
  const template = (messages[key] ?? fallbackEn[key]) as string;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, token: string) => {
    if (Object.prototype.hasOwnProperty.call(params, token)) {
      return String(params[token]);
    }
    return '';
  });
}

export async function applyLang(raw: string | undefined): Promise<LangCode> {
  const code: LangCode = LANG_MAP[raw ?? ''] ?? 'en';
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
