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
  ready?: () => void;
  expand?: () => void;
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

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

const TELEGRAM_READY_TIMEOUT = 3_000;
const TELEGRAM_READY_POLL_INTERVAL = 50;

export async function waitForTelegram(
  timeout: number = TELEGRAM_READY_TIMEOUT
): Promise<TelegramWebApp | null> {
  const deadline = Date.now() + Math.max(timeout, TELEGRAM_READY_POLL_INTERVAL);
  while (Date.now() <= deadline) {
    const telegram = resolveTelegram();
    if (telegram) {
      try {
        telegram.ready?.();
      } catch {
      }
      return telegram;
    }
    await delay(TELEGRAM_READY_POLL_INTERVAL);
  }
  return null;
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
