import { applyLang, t } from './i18n/i18n';
import { initRouter, onRouteChange, Route, goToHistory } from './router';
import { mountProgramView } from './views/program_view';
import { renderHistoryView } from './views/history';

type CleanupFn = () => void;

function ensureHistoryButton(): HTMLButtonElement | null {
  const controls = document.getElementById('controls') as HTMLDivElement | null;
  if (!controls) return null;

  controls.innerHTML = '';
  const footer = document.createElement('div');
  footer.className = 'history-footer';

  const button = document.createElement('button');
  button.type = 'button';
  button.id = 'history-button';
  button.className = 'primary-button';
  button.disabled = true;
  footer.appendChild(button);

  controls.appendChild(footer);
  return button;
}

function resolveSourceFromLocation(): 'direct' | 'subscription' {
  try {
    const u = new URL(window.location.href);
    const src = (u.searchParams.get('source') || '').toLowerCase();
    return src === 'subscription' ? 'subscription' : 'direct';
  } catch {
    return 'direct';
  }
}

function isHistoryRoute(): boolean {
  try {
    const u = new URL(window.location.href);
    if (u.hash.toLowerCase().includes('history')) return true;
    if (u.pathname.endsWith('/history')) return true;
    if ((u.searchParams.get('page') || '').toLowerCase() === 'history') return true;
  } catch {}
  return false;
}

async function handleRoute(
  _route: Route,
  ctx: {
    root: HTMLElement;
    content: HTMLElement;
    dateEl: HTMLElement;
    historyButton: HTMLButtonElement | null;
  },
  cleanup: { current?: CleanupFn }
): Promise<void> {
  if (cleanup.current) {
    try { cleanup.current(); } catch {}
  }
  cleanup.current = undefined;

  if (isHistoryRoute()) {
    if (ctx.historyButton) {
      ctx.historyButton.textContent = t('back');
      ctx.historyButton.disabled = false;
      ctx.historyButton.onclick = () => goToHistory();
    }
    await renderHistoryView();
    return;
  }

  if (ctx.historyButton) {
    ctx.historyButton.textContent = t('program.view_history');
    ctx.historyButton.disabled = false;
    ctx.historyButton.onclick = () => goToHistory();
  }

  const source = resolveSourceFromLocation();
  const dispose = await mountProgramView(
    {
      root: ctx.root,
      content: ctx.content,
      dateEl: ctx.dateEl,
      button: ctx.historyButton,
    },
    source
  );
  cleanup.current = dispose;
}

async function bootstrap(): Promise<void> {
  const root = document.getElementById('app') as HTMLElement | null;
  const content = document.getElementById('content') as HTMLElement | null;
  const dateEl = document.getElementById('program-date') as HTMLElement | null;
  if (!root || !content || !dateEl) return;

  try { await applyLang(); } catch {}

  const historyButton = ensureHistoryButton();
  const cleanup: { current?: CleanupFn } = {};

  onRouteChange((route) => {
    void handleRoute(route, { root, content, dateEl, historyButton }, cleanup);
  });

  initRouter();
}

bootstrap();
