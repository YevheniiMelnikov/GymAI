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

function normalizeLocale(raw?: string): Locale | null {
  if (!raw) return null;
  const normalized = raw.toLowerCase();
  if (normalized in LOCALE_MAP) return LOCALE_MAP[normalized];
  const [base] = normalized.split('-');
  return LOCALE_MAP[base] ?? null;
}

export function readLocale(fallback: Locale = 'en'): Locale {
  const raw = getWebApp()?.initDataUnsafe?.user?.language_code;
  return normalizeLocale(raw) ?? fallback;
}
