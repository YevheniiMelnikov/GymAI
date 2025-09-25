import type { Locale } from './api/types';

type TelegramUser = { language_code?: string };
type TelegramInitData = { user?: TelegramUser };

type TelegramWebApp = {
  initData?: string;
  initDataUnsafe?: TelegramInitData;
  ready?: () => void;
  expand?: () => void;
  platform?: string;
};

type TelegramNamespace = { WebApp?: TelegramWebApp };
type TelegramWindow = Window & { Telegram?: TelegramNamespace };

function getWebApp(): TelegramWebApp | null {
  try {
    const win = window as TelegramWindow;
    return win.Telegram?.WebApp ?? null;
  } catch {
    return null;
  }
}

export function tmeReady(): void {
  try { getWebApp()?.ready?.(); } catch {}
}

export function tmeExpand(): void {
  try { getWebApp()?.expand?.(); } catch {}
}

export function readInitData(): string {
  return getWebApp()?.initData ?? '';
}

const LOCALE_MAP: Record<string, Locale> = { en: 'en', ru: 'ru', uk: 'uk' };

export function readLocale(fallback: Locale = 'en'): Locale {
  const raw = getWebApp()?.initDataUnsafe?.user?.language_code;
  if (raw && raw in LOCALE_MAP) return LOCALE_MAP[raw];
  return fallback;
}
