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
  open_from_telegram: 'Open this page from Telegram.'
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

export function t<K extends keyof typeof fallbackEn>(key: K): string {
  return (messages[key] ?? fallbackEn[key]) as string;
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
