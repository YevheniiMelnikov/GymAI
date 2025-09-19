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

let expandedDays = new Set<string>();
let rendered: RenderedProgram | null = null;
let currentAbort: AbortController | null = null;

function getCurrentLocale(): Locale {
  const lang = document.documentElement.lang as Locale | string;
  if (lang === 'ru' || lang === 'uk' || lang === 'en') {
    return lang;
  }
  return 'en';
}

function ensureHistoryHandlers(): void {
  if (historyButton && !historyButton.dataset.bound) {
    historyButton.dataset.bound = 'true';
    historyButton.addEventListener('click', () => {
      goToHistory();
    });
  }
  if (content && !content.dataset.bound) {
    content.dataset.bound = 'true';
    content.addEventListener('click', (event) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const toggle = target.closest<HTMLButtonElement>('.day-toggle');
      if (!toggle || toggle.disabled) {
        return;
      }
      const dayId = toggle.dataset.dayId;
      if (!dayId || !rendered) {
        return;
      }
      const day = rendered.days.get(dayId);
      if (!day) {
        return;
      }
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      setDayExpanded(dayId, !expanded);
    });
  }
}

function setDayExpanded(dayId: string, expand: boolean): void {
  if (!rendered) {
    return;
  }
  const entry = rendered.days.get(dayId);
  if (!entry) {
    return;
  }
  entry.button.setAttribute('aria-expanded', String(expand));
  entry.button.classList.toggle('day-toggle--expanded', expand);
  entry.panel.hidden = !expand;
  entry.panel.setAttribute('aria-hidden', String(!expand));
  if (expand) {
    expandedDays.add(dayId);
    entry.button.scrollIntoView({ block: 'nearest' });
  } else {
    expandedDays.delete(dayId);
  }
}

function clearContent(): void {
  if (!content) return;
  content.innerHTML = '';
}

function renderSkeleton(count = 4): void {
  if (!content) return;
  content.setAttribute('aria-busy', 'true');
  clearContent();
  for (let i = 0; i < count; i += 1) {
    const placeholder = document.createElement('div');
    placeholder.className = 'skeleton-card';
    content.appendChild(placeholder);
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

function resolveProgramTitle(program: Program): string {
  const named = (program as { title?: string | null }).title;
  if (named && named.trim()) {
    return named.trim();
  }
  return t('program.title');
}

function updateMeta(program: Program, locale: Locale): void {
  const formattedDate = program.created_at ? fmtDate(program.created_at, locale) : null;
  if (titleEl) {
    titleEl.textContent = resolveProgramTitle(program);
  }
  if (dateBlock) {
    if (formattedDate) {
      dateBlock.textContent = t('program.created', { date: formattedDate });
      dateBlock.removeAttribute('hidden');
    } else {
      dateBlock.textContent = '';
      dateBlock.setAttribute('hidden', 'true');
    }
  }
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = false;
  }
}

type LegacyMeta = {
  readonly createdAt?: string | null;
  readonly locale: Locale;
  readonly title?: string | null;
};

function updateLegacyMeta(meta: LegacyMeta): void {
  if (titleEl) {
    titleEl.textContent = meta.title?.trim() || t('program.title');
  }
  if (dateBlock) {
    if (meta.createdAt) {
      const formattedDate = fmtDate(meta.createdAt, meta.locale);
      dateBlock.textContent = t('program.created', { date: formattedDate });
      dateBlock.removeAttribute('hidden');
    } else {
      dateBlock.textContent = '';
      dateBlock.setAttribute('hidden', 'true');
    }
  }
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = false;
  }
}

function renderLegacyContent(text: string, locale: Locale): void {
  if (!content) return;
  clearContent();
  content.setAttribute('aria-busy', 'false');
  rendered = renderLegacyProgram(text, locale, expandedDays);
  content.appendChild(rendered.fragment);
  rendered.days.forEach((day, dayId) => {
    const expanded = expandedDays.has(dayId);
    day.button.setAttribute('aria-expanded', String(expanded));
    day.button.classList.toggle('day-toggle--expanded', expanded);
    day.panel.hidden = !expanded;
    day.panel.setAttribute('aria-hidden', String(!expanded));
  });
}

function resetMeta(): void {
  if (titleEl) {
    titleEl.textContent = t('program.title');
  }
  if (dateBlock) {
    dateBlock.textContent = '';
    dateBlock.setAttribute('hidden', 'true');
  }
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = true;
  }
}

function renderProgramContent(program: Program): void {
  if (!content) return;
  clearContent();
  rendered = renderProgramDays(program, program.locale, expandedDays);
  content.setAttribute('aria-busy', 'false');
  content.appendChild(rendered.fragment);
  rendered.days.forEach((day, dayId) => {
    const expanded = expandedDays.has(dayId);
    day.button.setAttribute('aria-expanded', String(expanded));
    day.button.classList.toggle('day-toggle--expanded', expanded);
    day.panel.hidden = !expanded;
    day.panel.setAttribute('aria-hidden', String(!expanded));
  });
}

function ensureInitData(): boolean {
  if (initData) return true;
  void applyLang('eng');
  if (content) {
    content.textContent = t('open_from_telegram');
  }
  return false;
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
  if (!content || !ensureInitData()) return;

  ensureHistoryHandlers();
  resetMeta();
  renderSkeleton();

  if (currentAbort) {
    currentAbort.abort();
  }
  const controller = new AbortController();
  currentAbort = controller;

  try {
    const loaded = await loadProgram(route, controller.signal);
    if (loaded.kind === 'structured') {
      expandedDays = new Set<string>();
      updateMeta(loaded.program, loaded.locale);
      renderProgramContent(loaded.program);
    } else {
      expandedDays = new Set<string>();
      updateLegacyMeta({
        locale: loaded.locale,
        createdAt: loaded.createdAt ?? null
      });
      renderLegacyContent(loaded.programText, loaded.locale);
    }
  } catch (error) {
    if ((error as { name?: string } | null)?.name === 'AbortError') {
      return;
    }
    resetMeta();
    const message = error instanceof HttpError ? error.message : statusToMessage(500);
    showError(message, () => {
      void renderProgramView(route);
    });
  } finally {
    if (currentAbort === controller) {
      currentAbort = null;
    }
  }
}
