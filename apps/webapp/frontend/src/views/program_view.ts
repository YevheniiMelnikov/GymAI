import { getProgram, HttpError, LoadedProgram, statusToMessage } from '../api/http';
import { Locale, Program, ProgramOrigin } from '../api/types';
import { applyLang, t } from '../i18n/i18n';
import { RenderedProgram, fmtDate, renderLegacyProgram, renderWeekList } from '../ui/render_program';
import { ProgramRoute, goToHistory } from '../router';

type ExpandedState = Record<string, string[]>;

const content = document.getElementById('content') as HTMLElement | null;
const dateChip = document.getElementById('program-date') as HTMLSpanElement | null;
const originChip = document.getElementById('program-origin') as HTMLSpanElement | null;
const historyButton = document.getElementById('history-button') as HTMLButtonElement | null;
const titleEl = document.getElementById('page-title') as HTMLElement | null;

const tg = (window as any).Telegram?.WebApp;
const initData: string = tg?.initData || '';

let currentProgramId: string | null = null;
let expandedDays = new Set<string>();
let rendered: RenderedProgram | null = null;
let currentAbort: AbortController | null = null;

type MetaOptions = {
  readonly locale: Locale;
  readonly createdAt?: string | null;
  readonly origin?: ProgramOrigin | null;
};

function storageKey(programId: string): string {
  return `program:${programId}:expanded`;
}

function readSessionExpanded(programId: string): Set<string> | null {
  try {
    const stored = sessionStorage.getItem(storageKey(programId));
    if (!stored) return null;
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return new Set();
    const ids = parsed.filter((value) => typeof value === 'string');
    return new Set(ids);
  } catch {
    return null;
  }
}

function writeSessionExpanded(programId: string, value: Set<string>): void {
  try {
    sessionStorage.setItem(storageKey(programId), JSON.stringify(Array.from(value)));
  } catch {
    /* ignore storage errors */
  }
}

function getCurrentLocale(): Locale {
  const lang = document.documentElement.lang as Locale | string;
  if (lang === 'ru' || lang === 'uk' || lang === 'en') {
    return lang;
  }
  return 'en';
}

function readExpanded(programId: string): Set<string> {
  const session = readSessionExpanded(programId);
  if (session) return session;
  const state = (history.state as { expanded?: ExpandedState } | null)?.expanded;
  if (!state) return new Set();
  const stored = state[programId];
  if (!stored) return new Set();
  return new Set(stored);
}

function persistExpanded(programId: string, value: Set<string>): void {
  writeSessionExpanded(programId, value);
  const state = history.state as { expanded?: ExpandedState } | null;
  const expanded: ExpandedState = { ...(state?.expanded ?? {}), [programId]: Array.from(value) };
  history.replaceState({ ...(state ?? {}), expanded, lastProgramId: programId }, document.title);
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

      const notesToggle = target.closest<HTMLButtonElement>('.exercise-item__toggle');
      if (notesToggle) {
        const exerciseId = notesToggle.dataset.exerciseId;
        if (!exerciseId) return;
        const notes = content.querySelector<HTMLDivElement>(`#notes-${exerciseId}`);
        if (!notes) return;
        const open = notesToggle.getAttribute('aria-expanded') === 'true';
        notesToggle.setAttribute('aria-expanded', String(!open));
        notes.hidden = open;
        return;
      }

      const dayCard = target.closest<HTMLButtonElement>('.day-card');
      if (!dayCard || dayCard.disabled) return;
      const dayId = dayCard.dataset.dayId;
      if (!dayId || !rendered) return;
      const panel = rendered.dayPanels.get(dayId);
      if (!panel) return;
      const expanded = dayCard.getAttribute('aria-expanded') === 'true';
      toggleDay(dayCard, panel, !expanded);
    });
  }
}

function toggleDay(button: HTMLButtonElement, panel: HTMLDivElement, expand: boolean): void {
  const dayId = button.dataset.dayId;
  if (!dayId || !currentProgramId) return;
  button.setAttribute('aria-expanded', String(expand));
  button.classList.toggle('day-card--expanded', expand);
  panel.setAttribute('aria-hidden', String(!expand));
  if (expand) {
    panel.classList.add('exercise-list--expanded');
    panel.style.maxHeight = `${panel.scrollHeight}px`;
    button.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    expandedDays.add(dayId);
  } else {
    panel.classList.remove('exercise-list--expanded');
    panel.style.maxHeight = `${panel.scrollHeight}px`;
    requestAnimationFrame(() => {
      panel.style.maxHeight = '0px';
    });
    expandedDays.delete(dayId);
  }
  persistExpanded(currentProgramId, expandedDays);
}

function attachPanelTransitions(): void {
  if (!rendered) return;
  rendered.dayPanels.forEach((panel) => {
    if (!panel.dataset.transitionBound) {
      panel.dataset.transitionBound = 'true';
      panel.addEventListener('transitionend', (event) => {
        if (event.propertyName !== 'max-height') return;
        if (panel.classList.contains('exercise-list--expanded')) {
          panel.style.maxHeight = 'none';
        } else {
          panel.style.maxHeight = '0px';
        }
      });
    }
  });
}

function clearContent(): void {
  if (!content) return;
  content.innerHTML = '';
}

function renderSkeleton(count = 6): void {
  if (!content) return;
  content.setAttribute('aria-busy', 'true');
  clearContent();
  const section = document.createElement('section');
  section.className = 'week';
  for (let i = 0; i < count; i += 1) {
    const card = document.createElement('div');
    card.className = 'day-card day-card--skeleton';
    const bar = document.createElement('div');
    bar.className = 'day-card__title skeleton-bar';
    card.appendChild(bar);
    const sub = document.createElement('div');
    sub.className = 'day-card__subtitle skeleton-bar';
    card.appendChild(sub);
    section.appendChild(card);
  }
  content.appendChild(section);
}

function showError(message: string, retry: () => void): void {
  if (!content) return;
  clearContent();
  content.removeAttribute('aria-busy');
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
  updateMetaFrom({
    locale,
    createdAt: program.created_at,
    origin: program.origin ?? null
  });
}

function updateMetaFrom(meta: MetaOptions): void {
  if (titleEl) titleEl.textContent = t('program.title');
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = false;
  }
  const formattedDate = meta.createdAt ? fmtDate(meta.createdAt, meta.locale) : null;
  if (dateChip) {
    if (formattedDate) {
      dateChip.textContent = t('program.created', { date: formattedDate });
      dateChip.removeAttribute('hidden');
    } else {
      dateChip.textContent = '';
      dateChip.setAttribute('hidden', 'true');
    }
  }
  if (originChip) {
    const origin = meta.origin;
    if (origin) {
      originChip.textContent = t(origin === 'ai' ? 'program.origin.ai' : 'program.origin.coach');
      originChip.classList.toggle('ai-label', origin === 'ai');
      originChip.removeAttribute('hidden');
    } else {
      originChip.textContent = '';
      originChip.setAttribute('hidden', 'true');
      originChip.classList.remove('ai-label');
    }
  }
}

function renderLegacyContent(text: string, locale: Locale): void {
  if (!content) return;
  clearContent();
  content.removeAttribute('aria-busy');
  rendered = renderLegacyProgram(text, locale, expandedDays);
  content.appendChild(rendered.fragment);
  rendered.dayPanels.forEach((panel, dayId) => {
    if (expandedDays.has(dayId)) {
      panel.classList.add('exercise-list--expanded');
      panel.style.maxHeight = 'none';
      panel.setAttribute('aria-hidden', 'false');
    } else {
      panel.classList.remove('exercise-list--expanded');
      panel.style.maxHeight = '0px';
      panel.setAttribute('aria-hidden', 'true');
    }
  });
  attachPanelTransitions();
}

function resetMeta(): void {
  if (dateChip) {
    dateChip.textContent = '';
    dateChip.setAttribute('hidden', 'true');
  }
  if (originChip) {
    originChip.textContent = '';
    originChip.setAttribute('hidden', 'true');
    originChip.classList.remove('ai-label');
  }
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = true;
  }
}

function renderProgramContent(program: Program): void {
  if (!content) return;
  clearContent();
  rendered = renderWeekList(program, program.locale, expandedDays);
  content.removeAttribute('aria-busy');
  content.appendChild(rendered.fragment);
  rendered.dayPanels.forEach((panel, dayId) => {
    if (expandedDays.has(dayId)) {
      panel.classList.add('exercise-list--expanded');
      panel.style.maxHeight = 'none';
      panel.setAttribute('aria-hidden', 'false');
    } else {
      panel.classList.remove('exercise-list--expanded');
      panel.style.maxHeight = '0px';
      panel.setAttribute('aria-hidden', 'true');
    }
  });
  attachPanelTransitions();
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
      currentProgramId = loaded.program.id;
      expandedDays = readExpanded(loaded.program.id);
      persistExpanded(loaded.program.id, expandedDays);
      updateMeta(loaded.program, loaded.locale);
      renderProgramContent(loaded.program);
    } else {
      const legacyId = loaded.programId ?? 'legacy';
      currentProgramId = legacyId;
      expandedDays = readExpanded(legacyId);
      persistExpanded(legacyId, expandedDays);
      updateMetaFrom({
        locale: loaded.locale,
        createdAt: loaded.createdAt ?? null,
        origin: loaded.origin ?? null
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
