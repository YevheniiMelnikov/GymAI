import type { Locale } from './api/types';

type TelegramUser = { language_code?: string };
type TelegramInitData = { user?: TelegramUser };

type TelegramThemeParams = {
  bg_color?: string;
  secondary_bg_color?: string;
};

type TelegramWebApp = {
  initData?: string;
  initDataUnsafe?: TelegramInitData;
  ready?: () => void;
  expand?: () => void;
  close?: () => void;
  platform?: string;
  setBackgroundColor?: (color: string) => void;
  setHeaderColor?: (color: string | 'bg_color' | 'secondary_bg_color') => void;
  themeParams?: TelegramThemeParams;
  BackButton?: TelegramBackButton;
};

type TelegramBackButton = {
  isVisible: boolean;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
  show: () => void;
  hide: () => void;
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

export function closeWebApp(): void {
  try {
    const webApp = getWebApp();
    if (webApp?.close) {
      webApp.close();
      return;
    }
  } catch {}
  try { window.close(); } catch {}
}

export function showBackButton(): void {
  try { getWebApp()?.BackButton?.show(); } catch {}
}

export function hideBackButton(): void {
  try { getWebApp()?.BackButton?.hide(); } catch {}
}

export function onBackButtonClick(cb: () => void): void {
  try { getWebApp()?.BackButton?.onClick(cb); } catch {}
}

export function offBackButtonClick(cb: () => void): void {
  try { getWebApp()?.BackButton?.offClick(cb); } catch {}
}

const HEX_COLOR_PATTERN = /^#?(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i;

function normalizeHexColor(value: string | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;
  if (!HEX_COLOR_PATTERN.test(trimmed)) return null;
  return trimmed.startsWith('#') ? trimmed : `#${trimmed}`;
}

export function tmeMatchBackground(): void {
  const webApp = getWebApp();
  if (!webApp) return;

  const primary = normalizeHexColor(webApp.themeParams?.bg_color);
  const fallback = normalizeHexColor(webApp.themeParams?.secondary_bg_color);
  const color = primary ?? fallback;
  if (!color) return;

  try { webApp.setBackgroundColor?.(color); } catch {}
  try { webApp.setHeaderColor?.('secondary_bg_color'); } catch {}

  try {
    if (primary) {
      document.documentElement.style.setProperty('--tg-theme-bg-color', primary);
    }
    if (fallback) {
      document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', fallback);
    } else if (primary) {
      document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', primary);
    }
    document.documentElement.style.backgroundColor = color;
    document.body.style.backgroundColor = color;
  } catch {}
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
