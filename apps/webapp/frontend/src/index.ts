import { applyLang, t } from './i18n/i18n';
import { getRoute, ProgramRoute } from './router';

declare const Telegram: any;

const tg = Telegram?.WebApp;
const initData: string = tg?.initData || '';

async function route(): Promise<void> {
  const info = getRoute();
  if (info.name === 'history') {
    const { renderHistory } = await import('./views/history');
    await renderHistory();
    return;
  }
  const { renderProgramView } = await import('./views/program_view');
  await renderProgramView(info as ProgramRoute);
}

void (async () => {
  const initialLang = (
    Telegram?.WebApp?.initDataUnsafe?.user?.language_code ?? 'en'
  ).replace('ua', 'uk');
  await applyLang(initialLang);
  try {
    (Telegram?.WebApp)?.ready?.();
  } catch {}
  if (!initData) {
    const content = document.getElementById('content');
    if (content) content.textContent = t('open_from_telegram');
    return;
  }
  await route();
})();
