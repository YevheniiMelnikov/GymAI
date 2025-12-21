export type LangCode = 'en' | 'ru' | 'uk';
export const LANG_MAP: Record<string, LangCode> = { eng: 'en', en: 'en', ru: 'ru', ua: 'uk', uk: 'uk' };
export const LANG_CHANGED_EVENT = 'app:lang-changed';

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
  no_programs: 'You have no programs yet',
  sort_newest: 'Sort: Newest',
  sort_oldest: 'Sort: Oldest',
  show_ai: 'Show AI workout plans',
  back: 'Back',
  open_from_telegram: 'Open this page from Telegram.',
  'program.title': 'My Workouts',
  'program.created': 'Created: {date}',
  'program.view_history': 'History',
  'program.week': 'Week {n}',
  'program.day': 'Day {n}',
  'program.day.rest': 'Rest Day',
  'program.exercise.replace': 'Request alternative exercise',
  'program.exercise.replace_dialog.title': 'Need an alternative?',
  'program.exercise.replace_dialog.body':
    'We can generate another exercise for this slot at no extra cost. Use it when you lack equipment or want a different variation. The number of such generations within a single program is limited.',
  'program.exercise.replace_dialog.confirm': 'Generate',
  'program.exercise.replace_dialog.cancel': 'Cancel',
  'program.create_new': 'Create new',
  'program.action_error': 'Unable to start the flow. Try again later.',
  retry: 'Retry',
  'tabs.switch_label': 'Section switcher',
  'tabs.program': 'Programs',
  'tabs.subscriptions': 'Subscriptions',
  'subscriptions.title': 'Subscriptions',
  'subscriptions.empty': 'You have no subscriptions yet',
  'page.program': 'Program',
  'page.history': 'History',
  'page.subscriptions': 'Subscriptions',
  'payment.title': 'Payment',
  'payment.amount': 'Amount: {amount} {currency}',
  'payment.loading': 'Loading payment info...',
  'payment.launch': 'Launching payment...',
  'payment.open': 'Open Payment',
  'payment.unavailable': 'Payment service unavailable',
  'faq.title': 'FAQ',
  'faq.placeholder.title': 'Answers are on the way',
  'faq.placeholder.body': 'We are preparing the FAQ page. Please check back soon.'
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
  await loadMessages(code);
  document.documentElement.lang = code;
  try {
    window.dispatchEvent(new CustomEvent(LANG_CHANGED_EVENT, { detail: { code } }));
  } catch {
  }
  return code;
}

export function formatDate(ts: number, locale: string): string {
  return new Date(ts * 1000).toLocaleDateString(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });
}
