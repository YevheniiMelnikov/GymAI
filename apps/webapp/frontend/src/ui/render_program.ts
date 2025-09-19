import { Day, Exercise, Locale, Program, Week } from '../api/types';
import { t } from '../i18n/i18n';

export type RenderedProgram = {
  readonly fragment: DocumentFragment;
};

export function fmtDate(value: string, locale: string): string {
  const date = new Date(value);
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

function createExerciseItem(ex: Exercise, index: number, locale: string): HTMLLIElement {
  const li = document.createElement('li');
  li.textContent = `${index + 1}. ${ex.name}`;
  const meta: string[] = [];
  if (ex.sets && ex.reps) meta.push(`${ex.sets}×${ex.reps}`);
  else if (ex.reps) meta.push(ex.reps);
  if (ex.weight) meta.push(`${ex.weight.value} ${ex.weight.unit}`);
  if (ex.equipment) meta.push(ex.equipment);
  if (ex.notes) meta.push(ex.notes);
  if (meta.length > 0) {
    const small = document.createElement('div');
    small.style.color = 'var(--muted)';
    small.style.fontSize = '13px';
    small.textContent = meta.join(' | ');
    li.appendChild(document.createElement('br'));
    li.appendChild(small);
  }
  return li;
}

function renderDay(day: Day, locale: string): HTMLElement {
  const section = document.createElement('article');
  section.className = 'program-day';

  const h3 = document.createElement('h3');
  if (day.type === 'rest') {
    h3.textContent = t('program.day.rest');
  } else {
    h3.textContent = t('program.day', { n: day.index, title: day.title });
  }
  section.appendChild(h3);

  if (day.type === 'workout' && day.exercises) {
    const ul = document.createElement('ul');
    day.exercises.forEach((ex, idx) => {
      ul.appendChild(createExerciseItem(ex, idx, locale));
    });
    section.appendChild(ul);
  }
  return section;
}

export function renderProgramDays(program: Program, locale: string): RenderedProgram {
  const fragment = document.createDocumentFragment();
  const weeks = ensureWeeks(program);
  weeks.forEach((week) => {
    const wrap = document.createElement('section');
    wrap.className = 'week';

    const h2 = document.createElement('h2');
    h2.textContent = t('program.week', { n: week.index });
    wrap.appendChild(h2);

    week.days.forEach((day) => {
      wrap.appendChild(renderDay(day, locale));
    });

    fragment.appendChild(wrap);
  });
  return { fragment };
}

export function renderLegacyProgram(text: string, locale: Locale): RenderedProgram {
  const fragment = document.createDocumentFragment();
  const parts = text.split(/\n\s*\n/).filter((p) => p.trim().length > 0);

  parts.forEach((block, idx) => {
    const lines = block.split(/\n/).map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) return;

    const fakeDay: Day = {
      id: `legacy-${idx + 1}`,
      index: idx + 1,
      type: 'workout',
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
    };
    fragment.appendChild(renderDay(fakeDay, locale));
  });

  return { fragment };
}
