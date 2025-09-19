import { applyLang } from './i18n/i18n';
import { renderProgramView } from './views/program_view';
import { renderHistoryView } from './views/history';
import { ProgramRoute } from './router';

// Telegram init data
const tg = (window as any).Telegram?.WebApp;
const initData: string = tg?.initData || '';

function ensureInitData(): boolean {
  if (initData) return true;
  void applyLang('en');
  const content = document.getElementById('content');
  if (content) {
    content.textContent = 'Open this page from Telegram';
  }
  return false;
}

async function main(): Promise<void> {
  if (!ensureInitData()) return;

  // определяем маршрут
  const params = new URLSearchParams(window.location.search);
  const page = params.get('page');

  if (page === 'history') {
    await renderHistoryView();
  } else {
    const route: ProgramRoute = {
      programId: params.get('program_id') ?? undefined,
      source: params.get('type') === 'subscription' ? 'subscription' : 'direct',
    };
    await renderProgramView(route);
  }
}

void main();
