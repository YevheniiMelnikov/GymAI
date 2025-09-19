import { getProgram, HttpError, LoadedProgram, statusToMessage } from '../api/http';
import { Locale, Program } from '../api/types';
import { applyLang, t } from '../i18n/i18n';
import { RenderedProgram, fmtDate, renderLegacyProgram, renderProgramDays } from '../ui/render_program';
import { ProgramRoute, goToHistory } from '../router';

const content = document.getElementById('content') as HTMLElement | null;
const dateBlock = document.getElementById('program-date') as HTMLElement | null;
const historyButton = document.getElementById('history-button') as HTMLButtonElement | null;
const titleEl = document.getElementById('page-title') as HTMLElement | null;

const tg = (window as any).Telegram?.WebApp;
const initData: string = tg?.initData || '';

let rendered: RenderedProgram | null = null;

function getCurrentLocale(): Locale {
  const lang = document.documentElement.lang as Locale | string;
  if (lang === 'ru' || lang === 'uk' || lang === 'en') {
    return lang;
  }
  return 'en';
}

function ensureHandlers(): void {
  if (historyButton && !historyButton.dataset.bound) {
    historyButton.dataset.bound = 'true';
    historyButton.addEventListener('click', goToHistory);
  }
}

function clearContent(): void {
  if (content) content.innerHTML = '';
}

function renderSkeleton(count = 3): void {
  if (!content) return;
  content.setAttribute('aria-busy', 'true');
  clearContent();
  for (let i = 0; i < count; i++) {
    const ph = document.createElement('div');
    ph.className = 'skeleton-card';
    content.appendChild(ph);
  }
}

function showError(message: string, retry: () => void): void {
  if (!content) return;
  clearContent();
  content.setAttribute('aria-busy', 'false');
  const block = document.createElement('div');
  block.className = 'error-block';
  const text = document.createElement('p');
  text.textContent = message;
  block.appendChild(text);
  const retryBtn = document.createElement('button');
  retryBtn.type = 'button';
  retryBtn.textContent = t('retry');
  retryBtn.addEventListener('click', retry);
  block.appendChild(retryBtn);
  content.appendChild(block);
}

function updateMeta(program: Program, locale: Locale): void {
  if (titleEl) {
    const named = (program as { title?: string | null }).title;
    titleEl.textContent = named?.trim() || t('program.title');
  }
  if (dateBlock) {
    if (program.created_at) {
      const formatted = fmtDate(program.created_at, locale);
      dateBlock.textContent = t('program.created', { date: formatted });
      dateBlock.hidden = false;
    } else {
      dateBlock.textContent = '';
      dateBlock.hidden = true;
    }
  }
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = false;
  }
}

function resetMeta(): void {
  if (titleEl) titleEl.textContent = t('program.title');
  if (dateBlock) {
    dateBlock.textContent = '';
    dateBlock.hidden = true;
  }
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = true;
  }
}

function renderProgramContent(program: Program): void {
  if (!content) return;
  clearContent();
  rendered = renderProgramDays(program, program.locale);
  content.setAttribute('aria-busy', 'false');
  content.appendChild(rendered.fragment);
}

function renderLegacyContent(text: string, locale: Locale): void {
  if (!content) return;
  clearContent();
  rendered = renderLegacyProgram(text, locale);
  content.setAttribute('aria-busy', 'false');
  content.appendChild(rendered.fragment);
}

async function loadProgram(route: ProgramRoute, signal: AbortSignal): Promise<LoadedProgram> {
  const locale = getCurrentLocale();
  const loaded = await getProgram(route.programId ?? '', locale, {
    initData,
    source: route.source,
    signal
  });
  await applyLang(loaded.locale);
  document.title = t('program.title');
  return loaded;
}

export async function renderProgramView(route: ProgramRoute): Promise<void> {
  if (!content) return;
  ensureHandlers();
  resetMeta();
  renderSkeleton();

  const controller = new AbortController();

  try {
    const loaded = await loadProgram(route, controller.signal);
    if (loaded.kind === 'structured') {
      updateMeta(loaded.program, loaded.locale);
      renderProgramContent(loaded.program);
    } else {
      updateMeta(
        { id: 'legacy', created_at: loaded.createdAt ?? null, locale: loaded.locale, weeks: [], days: [] },
        loaded.locale
      );
      renderLegacyContent(loaded.programText, loaded.locale);
    }
  } catch (error) {
    if ((error as { name?: string } | null)?.name === 'AbortError') return;
    resetMeta();
    const message = error instanceof HttpError ? error.message : statusToMessage(500);
    showError(message, () => {
      void renderProgramView(route);
    });
  }
}
