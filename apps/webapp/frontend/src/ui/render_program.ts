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

function createExerciseItem(ex: Exercise, index: number): HTMLLIElement {
  const li = document.createElement('li');
  li.className = 'program-exercise';

  const details = document.createElement('details');
  details.className = 'program-exercise-details';

  const summary = document.createElement('summary');
  summary.className = 'program-exercise-summary';
  summary.textContent = `${index + 1}. ${ex.name}`;
  details.appendChild(summary);

  const metaParts: string[] = [];
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

  if (metaParts.length > 0) {
    const meta = document.createElement('div');
    meta.className = 'program-exercise-meta';
    meta.textContent = metaParts.join(' | ');
    content.appendChild(meta);
  }

  if (ex.notes) {
    const notes = document.createElement('p');
    notes.className = 'program-exercise-notes';
    notes.textContent = ex.notes;
    content.appendChild(notes);
  }

  if (content.childElementCount > 0) {
    details.appendChild(content);
  }

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

    const fakeDay = {
      id: `legacy-${idx + 1}`,
      index: idx + 1,
      type: 'workout' as const,
      title: lines[0],
      exercises: lines.slice(1).map((line, i) => ({
        id: `ex-${idx + 1}-${i + 1}`,
        name: line,
        sets: null,
        reps: null,
        weight: null,
        equipment: null,
        notes: null
      }))
    } satisfies Day;
    fragment.appendChild(renderDay(fakeDay));
  });

  return { fragment };
}
