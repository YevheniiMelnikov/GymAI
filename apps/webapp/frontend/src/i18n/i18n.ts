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
  history: 'Archive',
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
  'program.created': '📅 Created: {date}',
  'program.view_history': 'Archive',
  'program.week': 'Week {n}',
  'program.day': 'Day {n}',
  'program.day.rest': 'Rest Day',
  'program.exercise.replace': '🔄 Replace exercise',
  'program.exercise.edit': 'Edit',
  'program.exercise.replace_dialog.title': 'Need an alternative?',
  'program.exercise.replace_dialog.body':
    'We can generate another exercise for this slot at no extra cost. Use it when you lack equipment or want a different variation. The number of such generations within a single program is limited.',
  'program.exercise.replace_dialog.confirm': 'Yes',
  'program.exercise.replace_dialog.cancel': 'Cancel',
  'program.exercise.edit_dialog.close': 'Close',
  'program.exercise.technique.button': '🏋️‍♂️ Show technique',
  'program.exercise.technique.title': 'Technique not available',
  'program.exercise.technique.body': 'No videos yet. We will add them soon.',
  'program.exercise.technique.close': 'Close',
  'program.exercise.edit_dialog.set': 'Set',
  'program.exercise.edit_dialog.reps': 'Reps',
  'program.exercise.edit_dialog.weight': 'Weight',
  'program.exercise.edit_dialog.add_set': 'Add set',
  'program.exercise.edit_dialog.delete_set': 'Delete set',
  'program.exercise.edit_dialog.save': 'Save',
  'program.exercise.edit_dialog.saving': 'Saving...',
  'program.exercise.edit_dialog.cancel': 'Cancel',
  'program.create_new': 'Create new',
  'program.action_error': 'Unable to start the flow. Try again later.',
  retry: 'Retry',
  'tabs.switch_label': 'Section switcher',
  'tabs.program': 'Programs',
  'tabs.subscriptions': 'Subscriptions',
  'subscriptions.title': 'Subscriptions',
  'subscriptions.empty': 'You have no active subscriptions yet',
  'subscriptions.replace_confirm.title': 'Replace current subscription?',
  'subscriptions.replace_confirm.body':
    'You already have an active subscription. If you create a new one, the current subscription will be moved to Archive and stop updating. Continue?',
  'subscriptions.replace_confirm.confirm': 'Continue',
  'subscriptions.replace_confirm.cancel': 'Cancel',
  'intro.title': 'How it works',
  'intro.program': 'Program: a list of exercises with technique tips, tailored to you.',
  'intro.subscription':
    'Subscription: personal coaching with weekly plan updates based on your progress.',
  'intro.ok': 'OK',
  'page.program': 'Program',
  'page.history': 'Archive',
  'page.subscriptions': 'Subscriptions',
  'payment.title': 'Payment',
  'payment.amount': 'Amount: {amount} {currency}',
  'payment.loading': 'Loading payment info...',
  'payment.launch': 'Launching payment...',
  'payment.open': 'Open Payment',
  'payment.unavailable': 'Payment service unavailable',
  'faq.title': 'FAQ',
  'faq.placeholder.title': 'Answers are on the way',
  'faq.placeholder.body': 'We are preparing the FAQ page. Please check back soon.',
  'weekly_survey.title': 'Weekly Survey',
  'weekly_survey.loading': 'Preparing your weekly survey...',
  'weekly_survey.no_data': 'We need a structured workout plan to show this survey.',
  'weekly_survey.no_workouts': 'No workout days found for the week yet.',
  'weekly_survey.day_title': 'Day {n}',
  'weekly_survey.context': 'How challenging was each exercise?',
  'weekly_survey.edit_exercise': 'Edit exercise',
  'weekly_survey.exercise_difficulty': 'Exercise difficulty',
  'weekly_survey.scale.easy': 'Easier',
  'weekly_survey.scale.hard': 'Harder',
  'weekly_survey.skip_day': 'No workout',
  'weekly_survey.next_day': 'Next day',
  'weekly_survey.send': 'Send',
  'weekly_survey.sending': 'Sending...',
  'weekly_survey.comment.add': 'Add comment',
  'weekly_survey.comment.edit': 'Edit comment',
  'weekly_survey.comment.placeholder': 'You can leave any information that might help your coach'
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
