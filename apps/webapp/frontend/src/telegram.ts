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

let readyPromise: Promise<TelegramWebApp | null> | null = null;
let readyCalled = false;

function notifyReady(app: TelegramWebApp): void {
  if (readyCalled) return;
  readyCalled = true;
  try {
    app.ready?.();
  } catch {
  }
}

export function whenTelegramReady(): Promise<TelegramWebApp | null> {
  if (readyPromise) return readyPromise;

  readyPromise = new Promise((resolve) => {
    const initial = resolveTelegram();
    if (initial) {
      notifyReady(initial);
      resolve(initial);
      return;
    }

    const timeout = window.setTimeout(() => {
      window.clearInterval(interval);
      resolve(null);
    }, 3000);

    const interval = window.setInterval(() => {
      const app = resolveTelegram();
      if (!app) {
        return;
      }
      window.clearInterval(interval);
      window.clearTimeout(timeout);
      notifyReady(app);
      resolve(app);
    }, 50);
  });

  return readyPromise;
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
