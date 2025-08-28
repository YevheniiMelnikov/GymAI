import { applyLang, t } from './i18n/i18n';
import { getRoute } from './router';

declare const Telegram: any;

const tg = Telegram?.WebApp;
const initData: string = tg?.initData || '';

async function route(): Promise<void> {
  const { route, id, type } = getRoute();
  if (route === 'history') {
    const { renderHistory } = await import('./views/history.js');
    await renderHistory();
    return;
  }
  const { renderProgramView } = await import('./views/program_view.js');
  await renderProgramView(id, type);
}

void (async () => {
  await applyLang('eng');
  if (!initData) {
    const content = document.getElementById('content');
    if (content) content.textContent = t('open_from_telegram');
    return;
  }
  await route();
})();
