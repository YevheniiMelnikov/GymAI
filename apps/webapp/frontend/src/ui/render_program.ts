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

  if (content.childElementCount > 0) {
    details.appendChild(content);
    li.appendChild(details);
    return li;
  }

  details.classList.add('program-exercise-details-static');
  summary.classList.add('program-exercise-summary-static');
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
    const customTitle = day.title?.trim();
    if (customTitle && customTitle.length > 0) {
      summary.textContent = customTitle;
    } else {
      const fallback = t('program.day', { n: day.index, title: '' }).replace(/([\s—–-])+$/, '');
      summary.textContent = fallback;
    }
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

    const h2 = document.createElement('h2');
    h2.textContent = t('program.week', { n: week.index });
    wrap.appendChild(h2);

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
