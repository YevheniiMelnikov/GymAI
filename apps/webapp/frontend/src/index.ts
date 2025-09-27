import { applyLang, t } from './i18n/i18n';
import { initRouter, onRouteChange, Route, goToHistory, goToProgram } from './router';
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

async function handleRoute(
  route: Route,
  ctx: {
    root: HTMLElement;
    content: HTMLElement;
    dateEl: HTMLElement;
    historyButton: HTMLButtonElement | null;
    titleEl: HTMLElement | null;
  },
  cleanup: { current?: CleanupFn }
): Promise<void> {
  const { historyButton, titleEl } = ctx;
  if (cleanup.current) {
    try { cleanup.current(); } catch {}
  }
  cleanup.current = undefined;

  if (route.kind === 'history') {
    const source = resolveSourceFromLocation();
    if (historyButton) {
      historyButton.disabled = true;
    }
    await renderHistoryView(titleEl ?? undefined);
    if (historyButton) {
      historyButton.textContent = t('back');
      historyButton.disabled = false;
      historyButton.onclick = () => goToProgram(source);
    }
    return;
  }

  if (historyButton) {
    historyButton.disabled = true;
  }

  const dispose = await mountProgramView(
    {
      root: ctx.root,
      content: ctx.content,
      dateEl: ctx.dateEl,
      button: historyButton,
      titleEl,
    },
    route.source
  );
  cleanup.current = dispose;

  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = false;
    historyButton.onclick = () => goToHistory();
  }
}

async function bootstrap(): Promise<void> {
  const root = document.getElementById('app') as HTMLElement | null;
  const content = document.getElementById('content') as HTMLElement | null;
  const dateEl = document.getElementById('program-date') as HTMLElement | null;
  const titleEl = document.getElementById('page-title') as HTMLElement | null;
  if (!root || !content || !dateEl) return;

  try { await applyLang(); } catch {}

  const historyButton = ensureHistoryButton();
  const cleanup: { current?: CleanupFn } = {};

  onRouteChange((route) => {
    void handleRoute(route, { root, content, dateEl, historyButton, titleEl }, cleanup);
  });

  initRouter();
}

bootstrap();
