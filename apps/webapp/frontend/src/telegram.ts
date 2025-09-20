import type { Locale } from './api/types';

type TelegramUser = {
  language_code?: string;
};

type TelegramInitData = {
  user?: TelegramUser;
};

type TelegramWebApp = {
  initData?: string;
  initDataUnsafe?: TelegramInitData;
};

type TelegramNamespace = {
  WebApp?: TelegramWebApp;
};

type TelegramWindow = Window & {
  Telegram?: TelegramNamespace;
};

function resolveTelegram(): TelegramWebApp | null {
  try {
    const win = window as TelegramWindow;
    return win.Telegram?.WebApp ?? null;
  } catch {
    return null;
  }
}

export function readInitData(): string {
  const telegram = resolveTelegram();
  return telegram?.initData ?? '';
}

const LOCALE_MAP: Record<string, Locale> = { en: 'en', ru: 'ru', uk: 'uk' };

export function readLocale(fallback: Locale = 'en'): Locale {
  const telegram = resolveTelegram();
  const raw = telegram?.initDataUnsafe?.user?.language_code;
  if (raw && raw in LOCALE_MAP) {
    return LOCALE_MAP[raw];
  }
  return fallback;
}
