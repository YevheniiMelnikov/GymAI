import { Day, Exercise, Locale, Program, Week } from '../api/types';
import { t } from '../i18n/i18n';

export type RenderedProgram = {
  readonly fragment: DocumentFragment;
};

export function fmtDate(value: string | number, locale: string): string {
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  }).format(date);
}

function ensureWeeks(program: Program): Week[] {
  if (program.weeks && program.weeks.length > 0) return program.weeks;
  return [{ index: 1, days: program.days }];
}

type LegacyExerciseParts = {
  readonly name: string;
  readonly details: string | null;
};

function parseLegacyExerciseLine(line: string): LegacyExerciseParts {
  const trimmed = line.trim();
  const withoutMarker = trimmed.replace(/^(?:\d+[.)]\s+|\d+\s*[–—-]\s+|[-–—•*+]\s+)/, '');
  const base = withoutMarker.length > 0 ? withoutMarker : trimmed;

  const presentation = extractExercisePresentation(base);
  if (presentation.extraDetails.length > 0) {
    return { name: presentation.title, details: presentation.extraDetails.join(', ') };
  }

  const separators: Array<{ readonly pattern: RegExp; readonly offset: number }> = [
    { pattern: /:/, offset: 1 },
    { pattern: /\s[–—-]\s/, offset: 3 }
  ];

  for (const { pattern, offset } of separators) {
    const match = base.match(pattern);
    if (!match || match.index === undefined) continue;
    const splitIndex = match.index;
    const name = base.slice(0, splitIndex).trim();
    const details = base.slice(splitIndex + offset).trim();
    if (name.length > 0 && details.length > 0) {
      return { name, details };
    }
  }

  return { name: presentation.title, details: null };
}

type ExercisePresentation = {
  readonly title: string;
  readonly extraDetails: readonly string[];
};

const LEADING_NUMBER_PATTERN = /^\s*\d+(?:\.\d+)*\s*[).:\-–—]?\s*/;
const NOISE_TOKEN_PATTERN = /\bset\s+\d+\b/i;
const NOISE_TOKEN_GLOBAL_PATTERN = /\bset\s+\d+\b/gi;

function stripNoiseTokens(value: string): string {
  return value.replace(NOISE_TOKEN_GLOBAL_PATTERN, ' ').replace(/\s{2,}/g, ' ').trim();
}

function isNoiseToken(value: string): boolean {
  const normalized = value.trim();
  if (normalized.length === 0) {
    return true;
  }

  if (!NOISE_TOKEN_PATTERN.test(normalized)) {
    return false;
  }

  const cleaned = normalized.replace(/\bset\s+\d+\b/gi, '').trim();
  return cleaned.length === 0;
}

function extractExercisePresentation(name: string): ExercisePresentation {
  const raw = stripNoiseTokens(name.trim());
  if (raw.length === 0) {
    return { title: '', extraDetails: [] };
  }

  const normalized = raw
    .replace(/\s[–—-]\s/g, ' | ')
    .replace(/\s*[:：]\s*/g, ' | ')
    .replace(/[|¦│]/g, '|');

  const segments = normalized
    .split('|')
    .map((segment) => stripNoiseTokens(segment))
    .filter((segment) => segment.length > 0);

  const primary = segments.shift() ?? raw;
  const cleanedTitle = primary.replace(LEADING_NUMBER_PATTERN, '').trim();
  const title = cleanedTitle.length > 0 ? cleanedTitle : primary;

  const extraDetails = segments.filter((segment) => !isNoiseToken(segment));
  const uniqueDetails = Array.from(new Set(extraDetails));
  return { title, extraDetails: uniqueDetails };
}

function sanitizeNote(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = stripNoiseTokens(value);
  if (trimmed.length === 0) return null;
  if (isNoiseToken(trimmed)) return null;
  return trimmed;
}

const REFRESH_ICON = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
  <path d="M4.2 5.8a4 4 0 0 1 6.6-1.6L12 5.4V2.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M11.8 10.2a4 4 0 0 1-6.6 1.6L4 10.6v2.9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

type ExerciseDialogController = {
  open: () => void;
  close: () => void;
};

const REPLACE_DIALOG_ID = 'exercise-replace-dialog';
let exerciseDialog: ExerciseDialogController | null = null;

function getExerciseDialog(): ExerciseDialogController {
  if (exerciseDialog) return exerciseDialog;

  const root = document.createElement('div');
  root.id = REPLACE_DIALOG_ID;
  root.className = 'exercise-dialog';
  root.setAttribute('aria-hidden', 'true');

  const panel = document.createElement('div');
  panel.className = 'exercise-dialog__panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-labelledby', `${REPLACE_DIALOG_ID}-title`);
  panel.tabIndex = -1;

  const title = document.createElement('h3');
  title.id = `${REPLACE_DIALOG_ID}-title`;
  title.className = 'exercise-dialog__title';

  const body = document.createElement('p');
  body.className = 'exercise-dialog__body';

  const actions = document.createElement('div');
  actions.className = 'exercise-dialog__actions';

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'button-ghost';

  const confirmBtn = document.createElement('button');
  confirmBtn.type = 'button';
  confirmBtn.className = 'primary-button';

  actions.append(cancelBtn, confirmBtn);
  panel.append(title, body, actions);
  root.appendChild(panel);
  document.body.appendChild(root);

  const close = () => {
    root.dataset.state = 'closed';
    root.setAttribute('aria-hidden', 'true');
    document.removeEventListener('keydown', handleKeydown);
  };

  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  };

  const open = () => {
    title.textContent = t('program.exercise.replace_dialog.title');
    body.textContent = t('program.exercise.replace_dialog.body');
    confirmBtn.textContent = t('program.exercise.replace_dialog.confirm');
    cancelBtn.textContent = t('program.exercise.replace_dialog.cancel');
    root.dataset.state = 'open';
    root.setAttribute('aria-hidden', 'false');
    document.addEventListener('keydown', handleKeydown);
    window.requestAnimationFrame(() => {
      panel.focus();
    });
  };

  const onBackdropClick = (event: MouseEvent) => {
    if (event.target === root) {
      event.preventDefault();
      close();
    }
  };

  cancelBtn.addEventListener('click', (event) => {
    event.preventDefault();
    close();
  });
  confirmBtn.addEventListener('click', (event) => {
    event.preventDefault();
    close();
  });
  root.addEventListener('click', onBackdropClick);

  exerciseDialog = { open, close };
  return exerciseDialog;
}

function createExerciseActions(details: HTMLDetailsElement): HTMLDivElement {
  const actions = document.createElement('div');
  actions.className = 'program-exercise-actions';

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'exercise-refresh-btn';
  button.setAttribute('aria-label', t('program.exercise.replace'));
  button.title = t('program.exercise.replace');
  button.innerHTML = REFRESH_ICON;

  const dialog = getExerciseDialog();
  button.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!details.open) {
      details.open = true;
    }
    dialog.open();
  });

  actions.appendChild(button);
  return actions;
}

function createExerciseItem(ex: Exercise, index: number): HTMLLIElement {
  const li = document.createElement('li');
  li.className = 'program-exercise';

  const details = document.createElement('details');
  details.className = 'program-exercise-details';

  const summary = document.createElement('summary');
  summary.className = 'program-exercise-summary';
  const presentation = extractExercisePresentation(ex.name);
  const title = presentation.title.length > 0 ? presentation.title : ex.name;

  const indexLabel = document.createElement('span');
  indexLabel.className = 'program-exercise-index';
  indexLabel.textContent = String(index + 1);

  const titleLabel = document.createElement('span');
  titleLabel.className = 'program-exercise-title';
  titleLabel.textContent = title;

  summary.appendChild(indexLabel);
  summary.appendChild(titleLabel);
  details.appendChild(summary);

  const metaParts: string[] = [...presentation.extraDetails];
  if (ex.sets !== null && ex.sets !== undefined && ex.sets !== '') {
    metaParts.push(`Sets: ${String(ex.sets)}`);
  }
  if (ex.reps !== null && ex.reps !== undefined && ex.reps !== '') {
    metaParts.push(`Reps: ${String(ex.reps)}`);
  }
  if (ex.weight) metaParts.push(`Weight: ${ex.weight.value} ${ex.weight.unit}`);
  if (ex.equipment) metaParts.push(`Equipment: ${ex.equipment}`);

  const content = document.createElement('div');
  content.className = 'program-exercise-content';

  const note = sanitizeNote(ex.notes);

  const meaningfulMeta = metaParts.filter((part) => !isNoiseToken(part));

  if (meaningfulMeta.length > 0) {
    const meta = document.createElement('div');
    meta.className = 'program-exercise-meta';
    meta.textContent = meaningfulMeta.join(', ');
    content.appendChild(meta);
  }

  if (note) {
    const notes = document.createElement('p');
    notes.className = 'program-exercise-notes';
    notes.textContent = note;
    content.appendChild(notes);
  }

  if (content.childElementCount === 0) {
    content.classList.add('program-exercise-content--minimal');
  }

  content.appendChild(createExerciseActions(details));
  details.appendChild(content);
  li.appendChild(details);
  return li;
}

function renderDay(day: Day): HTMLElement {
  const details = document.createElement('details');
  details.className = 'program-day';

  const summary = document.createElement('summary');
  summary.className = 'program-day-summary';

  if (day.type === 'rest') {
    summary.textContent = t('program.day.rest');
    details.classList.add('program-day-rest');
  } else {
    summary.textContent = t('program.day', { n: day.index });
  }

  details.appendChild(summary);

  if (day.type === 'workout' && day.exercises) {
    const list = document.createElement('ul');
    list.className = 'program-day-list';
    day.exercises.forEach((ex, idx) => {
      list.appendChild(createExerciseItem(ex, idx));
    });
    details.appendChild(list);
  }

  return details;
}

export function renderProgramDays(program: Program): RenderedProgram {
  const fragment = document.createDocumentFragment();
  const weeks = ensureWeeks(program);
  weeks.forEach((week) => {
    const wrap = document.createElement('section');
    wrap.className = 'week';
    week.days.forEach((day) => {
      wrap.appendChild(renderDay(day));
    });

    fragment.appendChild(wrap);
  });
  return { fragment };
}

export function renderLegacyProgram(text: string, _locale: Locale): RenderedProgram {
  const fragment = document.createDocumentFragment();
  const parts = text.split(/\n\s*\n/).filter((p) => p.trim().length > 0);

  parts.forEach((block, idx) => {
    const lines = block.split(/\n/).map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) return;

    const exercises = lines.slice(1).map((line, i) => {
      const parsed = parseLegacyExerciseLine(line);
      return {
        id: `ex-${idx + 1}-${i + 1}`,
        name: parsed.name,
        sets: null,
        reps: null,
        weight: null,
        equipment: null,
        notes: parsed.details
      } satisfies Exercise;
    });

    const fakeDay = {
      id: `legacy-${idx + 1}`,
      index: idx + 1,
      type: 'workout' as const,
      title: lines[0],
      exercises
    } satisfies Day;
    fragment.appendChild(renderDay(fakeDay));
  });

  return { fragment };
}
