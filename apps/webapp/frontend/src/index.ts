import { applyLang, t } from './i18n/i18n';
import { initRouter, onRouteChange, goToHistory, goToProgram } from './router';
import type { ProgramRoute } from './router';
import { renderProgram } from './views/program';
import { renderHistoryView } from './views/history';
import { renderSubscriptions } from './views/subscriptions';
import { renderSegmented } from './components/Segmented';
import { tmeExpand, tmeMatchBackground } from './telegram';

type CleanupFn = () => void;
type Segment = 'program' | 'subscriptions';

const SEGMENT_HASH: Record<Segment, string> = { program: '#/program', subscriptions: '#/subscriptions' };

function parseSegment(hash: string): Segment | null {
  const normalized = hash.toLowerCase();
  if (normalized === SEGMENT_HASH.program) return 'program';
  if (normalized === SEGMENT_HASH.subscriptions) return 'subscriptions';
  return null;
}

function parseSegmentParam(param: string | null): Segment | null {
  if (!param) return null;
  const normalized = param.toLowerCase();
  if (normalized === 'program') return 'program';
  if (normalized === 'subscriptions') return 'subscriptions';
  return null;
}

function segmentFromQuery(): Segment | null {
  try {
    const url = new URL(window.location.href);
    return parseSegmentParam(url.searchParams.get('segment'));
  } catch {
    return null;
  }
}

function langFromQuery(): string | null {
  try {
    const url = new URL(window.location.href);
    const raw = url.searchParams.get('lang');
    return raw && raw.trim() ? raw : null;
  } catch {
    return null;
  }
}

function ensureSegmentHash(): Segment {
  const parsed = parseSegment(location.hash);
  if (parsed) {
    return parsed;
  }
  const querySegment = segmentFromQuery();
  if (querySegment) {
    const target = SEGMENT_HASH[querySegment];
    if (location.hash !== target) {
      location.hash = target;
    }
    return querySegment;
  }
  location.hash = SEGMENT_HASH.program;
  return 'program';
}

function syncRouteForSegment(route: ProgramRoute, segment: Segment): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set('segment', segment);
    if (segment === 'program') {
      url.searchParams.set('source', 'direct');
    } else if (route.source === 'subscription') {
      url.searchParams.set('source', 'subscription');
    } else {
      url.searchParams.delete('source');
    }
    history.replaceState({}, '', url.toString());
  } catch {
  }
}

function updateHashForSegment(segment: Segment): void {
  const target = SEGMENT_HASH[segment];
  if (location.hash !== target) {
    location.hash = target;
  }
}

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
    const url = new URL(window.location.href);
    const source = (url.searchParams.get('source') || '').toLowerCase();
    return source === 'subscription' ? 'subscription' : 'direct';
  } catch {
    return 'direct';
  }
}

async function bootstrap(): Promise<void> {
  const root = document.getElementById('app') as HTMLElement | null;
  const content = document.getElementById('content') as HTMLElement | null;
  const dateEl = document.getElementById('program-date') as HTMLElement | null;
  const titleEl = document.getElementById('page-title') as HTMLElement | null;
  const segmented = document.getElementById('segmented') as HTMLElement | null;
  if (!root || !content || !dateEl) return;

  const queryLang = langFromQuery();

  try {
    await applyLang(queryLang ?? undefined);
  } catch {
  }

  tmeExpand();
  tmeMatchBackground();

  const historyButton = ensureHistoryButton();
  const cleanup: { current?: CleanupFn } = {};
  let segmentedCleanup: (() => void) | undefined;
  const segmentState: { current: Segment; renderToken: number; lastRoute: ProgramRoute | null } = {
    current: ensureSegmentHash(),
    renderToken: 0,
    lastRoute: null,
  };

  function clearCleanup(): void {
    if (cleanup.current) {
      try {
        cleanup.current();
      } catch {
      }
      cleanup.current = undefined;
    }
  }

  const renderSegment = async (route: ProgramRoute, segment: Segment): Promise<void> => {
    segmentState.current = segment;
    segmentState.renderToken += 1;
    const token = segmentState.renderToken;

    syncRouteForSegment(route, segment);

    if (segmented) {
      segmentedCleanup?.();
      segmentedCleanup = renderSegmented(segmented, segment, (next) => {
        if (next !== segmentState.current) {
          updateHashForSegment(next);
        }
      });
      segmented.removeAttribute('aria-hidden');
    }

    clearCleanup();

    if (historyButton) {
      historyButton.disabled = true;
    }

    if (segment === 'program') {
      const dispose = await renderProgram(
        { root, content, dateEl, button: historyButton, titleEl },
        'direct'
      );
      if (segmentState.renderToken === token) {
        cleanup.current = dispose;
        if (historyButton) {
          historyButton.textContent = t('program.view_history');
          historyButton.disabled = false;
          historyButton.onclick = () => goToHistory();
        }
      } else {
        try {
          dispose();
        } catch {
        }
      }
      return;
    }

    if (titleEl) {
      titleEl.textContent = t('program.title');
    }
    dateEl.hidden = true;
    dateEl.textContent = '';
    content.innerHTML = '';
    content.removeAttribute('aria-busy');
    await renderSubscriptions(content);
    if (historyButton) {
      historyButton.textContent = t('program.view_history');
      historyButton.disabled = false;
      historyButton.onclick = () => goToHistory();
    }
  };

  const handleProgramRoute = async (route: ProgramRoute): Promise<void> => {
    segmentState.lastRoute = route;
    const segment = ensureSegmentHash();
    await renderSegment(route, segment);
  };

  const handleHistoryRoute = async (): Promise<void> => {
    segmentState.lastRoute = null;
    segmentState.renderToken += 1;
    if (segmented) {
      segmentedCleanup?.();
      segmentedCleanup = undefined;
      segmented.setAttribute('aria-hidden', 'true');
      segmented.innerHTML = '';
    }
    clearCleanup();

    if (historyButton) {
      historyButton.disabled = true;
    }

    await renderHistoryView(titleEl ?? undefined);

    if (historyButton) {
      historyButton.textContent = t('back');
      historyButton.disabled = false;
      historyButton.onclick = () => goToProgram(resolveSourceFromLocation());
    }
  };

  onRouteChange((route) => {
    if (route.kind === 'history') {
      void handleHistoryRoute();
      return;
    }
    void handleProgramRoute(route);
  });

  window.addEventListener('hashchange', () => {
    const next = ensureSegmentHash();
    if (next === segmentState.current) {
      return;
    }
    segmentState.current = next;
    if (segmentState.lastRoute) {
      void renderSegment(segmentState.lastRoute, next);
    }
  });

  initRouter();
}

bootstrap();
