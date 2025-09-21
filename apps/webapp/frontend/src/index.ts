import { applyLang, t } from './i18n/i18n';
import { initRouter, onRouteChange, Route, goToHistory } from './router';
import { mountProgramView } from './views/program_view';
import { renderHistoryView } from './views/history';
import { whenTelegramReady } from './telegram';
import { renderFatal } from './ui/fatal';

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

async function handleRoute(route: Route, ctx: {
  root: HTMLElement;
  content: HTMLElement;
  dateEl: HTMLElement;
  historyButton: HTMLButtonElement | null;
}, cleanup: { current?: CleanupFn }): Promise<void> {
  if (cleanup.current) {
    cleanup.current();
    cleanup.current = undefined;
  }

  if (route.kind === 'history') {
    if (ctx.historyButton) {
      ctx.historyButton.disabled = true;
    }
    await renderHistoryView();
    return;
  }

  if (ctx.historyButton) {
    ctx.historyButton.textContent = t('program.view_history');
    ctx.historyButton.disabled = false;
    ctx.historyButton.onclick = () => goToHistory();
  }

  const dispose = await mountProgramView(
    {
      root: ctx.root,
      content: ctx.content,
      dateEl: ctx.dateEl,
      button: ctx.historyButton,
    },
    route.source
  );
  cleanup.current = dispose;
}

async function bootstrap(): Promise<void> {
  const root = document.getElementById('app') as HTMLElement | null;
  const content = document.getElementById('content') as HTMLElement | null;
  const dateEl = document.getElementById('program-date') as HTMLElement | null;
  if (!root || !content || !dateEl) return;

  const fatal = (reason: unknown, message?: string): void => {
    console.error('Fatal webapp error', reason);
    renderFatal(root, message ?? 'Unable to start the application. Please try again later.', reason);
  };

  window.addEventListener('unhandledrejection', (event) => {
    fatal(event.reason);
  });
  window.addEventListener('error', (event) => {
    fatal(event.error ?? event.message);
  });

  const telegramReady = await whenTelegramReady();
  if (!telegramReady) {
    fatal('telegram_unavailable', 'Telegram WebApp is not available. Close and reopen the Mini App.');
    return;
  }

  try {
    await applyLang();
  } catch {
  }

  const historyButton = ensureHistoryButton();
  const cleanup: { current?: CleanupFn } = {};

  onRouteChange((route) => {
    void handleRoute(
      route,
      { root, content, dateEl, historyButton },
      cleanup
    );
  });

  initRouter();
}

bootstrap();
