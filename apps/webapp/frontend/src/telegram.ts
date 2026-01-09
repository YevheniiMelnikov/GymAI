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
  requestFullscreen?: () => void;
  disableVerticalSwipes?: () => void;
  enableVerticalSwipes?: () => void;
  close?: () => void;
  openTelegramLink?: (url: string) => void;
  openLink?: (url: string) => void;
  platform?: string;
  setBackgroundColor?: (color: string) => void;
  setHeaderColor?: (color: string | 'bg_color' | 'secondary_bg_color') => void;
  themeParams?: TelegramThemeParams;
  BackButton?: TelegramBackButton;
  HapticFeedback?: TelegramHapticFeedback;
};

type TelegramBackButton = {
  isVisible: boolean;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
  show: () => void;
  hide: () => void;
};

type TelegramHapticFeedback = {
  impactOccurred?: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
  selectionChanged?: () => void;
  notificationOccurred?: (type: 'error' | 'success' | 'warning') => void;
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

function isMobilePlatform(platform?: string): boolean {
  return platform === 'android' || platform === 'ios';
}

export function tmeReady(): void {
  try { getWebApp()?.ready?.(); } catch {}
}

export function tmeExpand(): void {
  try { getWebApp()?.expand?.(); } catch {}
}

export function tmeRequestFullscreen(): void {
  try {
    const webApp = getWebApp();
    if (!isMobilePlatform(webApp?.platform)) return;
    webApp?.requestFullscreen?.();
  } catch {}
}

export function tmeDisableVerticalSwipes(): void {
  try { getWebApp()?.disableVerticalSwipes?.(); } catch {}
}

export function tmeSetHeaderColor(color: string): void {
  if (!color) return;
  try { getWebApp()?.setHeaderColor?.(color); } catch {}
}

export function tmeSetBackgroundColor(color: string): void {
  if (!color) return;
  try { getWebApp()?.setBackgroundColor?.(color); } catch {}
}

export function tmeHapticImpact(style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft' = 'light'): void {
  try { getWebApp()?.HapticFeedback?.impactOccurred?.(style); } catch {}
}

export function tmeForceDarkTheme(): void {
  try {
    document.documentElement.dataset.theme = 'dark';
    document.body.dataset.theme = 'dark';
    document.documentElement.style.setProperty('--tg-theme-bg-color', '#0f141a');
    document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', '#151b22');
    document.documentElement.style.setProperty('--tg-theme-text-color', '#e6edf3');
    document.documentElement.style.setProperty('--tg-theme-hint-color', '#8b98a5');
    document.documentElement.style.setProperty('--tg-theme-link-color', '#6bb6ff');
    document.documentElement.style.setProperty('--tg-theme-button-color', '#408ce6');
    document.documentElement.style.setProperty('--tg-theme-button-text-color', '#0b0f14');
    document.documentElement.style.backgroundColor = '#0f141a';
    document.body.style.backgroundColor = '#0f141a';
  } catch {}
}

export function tmeEnterFullscreen(): void {
  tmeReady();
  tmeExpand();
  tmeRequestFullscreen();
  tmeDisableVerticalSwipes();
  tmeSetHeaderColor('#151b22');
  tmeSetBackgroundColor('#0f141a');
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

export function openTelegramLink(url: string): void {
  if (!url) return;
  const webApp = getWebApp();
  try {
    webApp?.openTelegramLink?.(url);
    return;
  } catch {}
  try {
    webApp?.openLink?.(url);
    return;
  } catch {}
  try {
    window.open(url, '_blank', 'noopener,noreferrer');
  } catch {}
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

const LOCALE_MAP: Record<string, Locale> = { en: 'en', eng: 'en', ru: 'ru', uk: 'uk', ua: 'uk' };
const LANG_STORAGE_KEY = 'app:lang';

function normalizeLocale(raw?: string | null): Locale | null {
  if (!raw) return null;
  const normalized = raw.toLowerCase();
  if (normalized in LOCALE_MAP) return LOCALE_MAP[normalized];
  const [base] = normalized.split('-');
  return LOCALE_MAP[base] ?? null;
}

export function readLocale(fallback: Locale = 'en'): Locale {
  try {
    const stored = window.sessionStorage.getItem(LANG_STORAGE_KEY);
    const storedLocale = normalizeLocale(stored);
    if (storedLocale) return storedLocale;
  } catch {
  }

  const docLocale = normalizeLocale(document.documentElement.lang);
  if (docLocale) return docLocale;

  const raw = getWebApp()?.initDataUnsafe?.user?.language_code;
  return normalizeLocale(raw) ?? fallback;
}

export function readPreferredLocale(paramLang?: string, fallback: Locale = 'en'): Locale {
  try {
    const stored = window.sessionStorage.getItem(LANG_STORAGE_KEY);
    const storedLocale = normalizeLocale(stored);
    if (storedLocale) return storedLocale;
  } catch {
  }

  const paramLocale = normalizeLocale(paramLang);
  if (paramLocale) return paramLocale;

  return readLocale(fallback);
}
