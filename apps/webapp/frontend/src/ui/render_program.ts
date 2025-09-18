import { Day, Exercise, Program, Week } from '../api/types';
import { TemplateParams, t } from '../i18n/i18n';

const dateFormatterCache = new Map<string, Intl.DateTimeFormat>();
const numberFormatterCache = new Map<string, Intl.NumberFormat>();

export type RenderedProgram = {
  readonly fragment: DocumentFragment;
  readonly dayPanels: Map<string, HTMLDivElement>;
};

function getDateFormatter(locale: string): Intl.DateTimeFormat {
  let formatter = dateFormatterCache.get(locale);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    });
    dateFormatterCache.set(locale, formatter);
  }
  return formatter;
}

function getNumberFormatter(locale: string): Intl.NumberFormat {
  let formatter = numberFormatterCache.get(locale);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 2, useGrouping: false });
    numberFormatterCache.set(locale, formatter);
  }
  return formatter;
}

export function fmtDate(value: string, locale: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return getDateFormatter(locale).format(new Date(timestamp));
}

export function fmtWeight(value: number, unit: string, locale: string): string {
  const formatted = getNumberFormatter(locale).format(value);
  const normalized = unit.toLowerCase();
  const unitKey = normalized === 'kg' || normalized === 'lb' ? `program.ex.unit.${normalized}` : null;
  const localizedUnit = unitKey ? t(unitKey as 'program.ex.unit.kg' | 'program.ex.unit.lb') : unit;
  return t('program.ex.weight', { w: formatted, unit: localizedUnit });
}

export function fmtSetsReps(sets: number, reps: string): string {
  const params: TemplateParams = { sets, reps };
  return t('program.ex.sets_reps', params);
}

function ensureWeeks(program: Program): Week[] {
  if (Array.isArray(program.weeks) && program.weeks.length > 0) {
    return program.weeks;
  }
  const days = Array.isArray(program.days) ? program.days : [];
  return [
    {
      index: 1,
      days
    }
  ];
}

function buildChevron(): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.classList.add('day-card__chevron');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('fill', 'currentColor');
  path.setAttribute('d', 'M9.29 6.71a1 1 0 0 0 0 1.41L13.17 12l-3.88 3.88a1 1 0 1 0 1.41 1.41l4.59-4.59a1 1 0 0 0 0-1.41L10.7 6.7a1 1 0 0 0-1.41.01z');
  svg.appendChild(path);
  return svg;
}

function buildNotesToggle(exerciseId: string): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'exercise-item__toggle';
  btn.setAttribute('aria-expanded', 'false');
  btn.dataset.exerciseId = exerciseId;
  const label = document.createElement('span');
  label.className = 'sr-only';
  label.textContent = t('program.ex.more');
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  icon.setAttribute('aria-hidden', 'true');
  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  circle.setAttribute('fill', 'currentColor');
  circle.setAttribute('d', 'M12 2a10 10 0 1 0 10 10A10.011 10.011 0 0 0 12 2zm0 15a1.25 1.25 0 1 1 1.25-1.25A1.252 1.252 0 0 1 12 17zm1-4.75h-2V7h2z');
  icon.appendChild(circle);
  btn.appendChild(label);
  btn.appendChild(icon);
  return btn;
}

function isBodyweightEquipment(equipment: string | null | undefined): boolean {
  if (!equipment) return true;
  return /body\s*weight|вага\s*тіла|own\s*weight/i.test(equipment);
}

export function renderExerciseList(
  exercises: Exercise[] | null | undefined,
  locale: string,
  isExpanded: boolean,
  dayId: string
): HTMLDivElement {
  const list = document.createElement('div');
  list.className = 'exercise-list';
  list.dataset.dayPanel = dayId;
  list.setAttribute('role', 'region');
  list.setAttribute('aria-hidden', String(!isExpanded));
  if (isExpanded) {
    list.classList.add('exercise-list--expanded');
  }
  const fragment = document.createDocumentFragment();
  (exercises ?? []).forEach((exercise, index) => {
    const row = document.createElement('div');
    row.className = 'exercise-item';
    row.dataset.exerciseId = exercise.id;

    const order = document.createElement('span');
    order.className = 'exercise-item__index';
    order.textContent = String(index + 1);
    row.appendChild(order);

    const body = document.createElement('div');
    body.className = 'exercise-item__body';
    const name = document.createElement('div');
    name.className = 'exercise-item__name';
    name.textContent = exercise.name;
    body.appendChild(name);

    const metaPieces: string[] = [];
    if (typeof exercise.sets === 'number' && exercise.reps) {
      metaPieces.push(fmtSetsReps(exercise.sets, exercise.reps));
    } else if (exercise.reps) {
      metaPieces.push(exercise.reps);
    }
    if (exercise.weight) {
      metaPieces.push(fmtWeight(exercise.weight.value, exercise.weight.unit, locale));
    } else if (isBodyweightEquipment(exercise.equipment)) {
      metaPieces.push(t('program.ex.bodyweight'));
    }
    if (exercise.equipment) {
      metaPieces.push(exercise.equipment);
    }

    if (metaPieces.length > 0) {
      const meta = document.createElement('div');
      meta.className = 'exercise-item__meta';
      meta.textContent = metaPieces.join(' | ');
      body.appendChild(meta);
    }
    row.appendChild(body);

    if (exercise.notes) {
      const toggle = buildNotesToggle(exercise.id);
      toggle.setAttribute('aria-controls', `notes-${exercise.id}`);
      row.appendChild(toggle);

      const notes = document.createElement('div');
      notes.id = `notes-${exercise.id}`;
      notes.className = 'exercise-notes';
      notes.textContent = exercise.notes;
      notes.hidden = true;
      fragment.appendChild(row);
      fragment.appendChild(notes);
    } else {
      fragment.appendChild(row);
    }
  });
  list.appendChild(fragment);
  return list;
}

export function renderDayCard(day: Day, isExpanded: boolean): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'day-card';
  btn.dataset.dayId = day.id;
  btn.id = `day-${day.id}`;
  btn.setAttribute('aria-expanded', String(isExpanded));
  if (isExpanded) {
    btn.classList.add('day-card--expanded');
  }
  if (day.type === 'rest') {
    btn.classList.add('day-card--rest');
    btn.disabled = true;
  }

  const title = document.createElement('div');
  title.className = 'day-card__title';
  if (day.type === 'rest') {
    title.textContent = t('program.day.rest');
  } else {
    title.textContent = t('program.day', { n: day.index, title: day.title });
  }
  const textWrap = document.createElement('div');
  textWrap.className = 'day-card__text';
  textWrap.appendChild(title);

  const subtitleValue = (day as { subtitle?: string | null }).subtitle;
  if (day.type === 'workout' && subtitleValue && subtitleValue.trim() && subtitleValue.trim() !== day.title.trim()) {
    const subtitle = document.createElement('div');
    subtitle.className = 'day-card__subtitle';
    subtitle.textContent = subtitleValue;
    textWrap.appendChild(subtitle);
  }

  btn.appendChild(textWrap);

  if (day.type === 'workout') {
    btn.appendChild(buildChevron());
  }

  return btn;
}

export function renderWeekList(
  program: Program,
  locale: string,
  expandedDays: Set<string>
): RenderedProgram {
  const fragment = document.createDocumentFragment();
  const dayPanels = new Map<string, HTMLDivElement>();
  const weeks = ensureWeeks(program);
  for (const week of weeks) {
    const section = document.createElement('section');
    section.className = 'week';

    const heading = document.createElement('h2');
    heading.textContent = t('program.week', { n: week.index });
    section.appendChild(heading);

    for (const day of week.days) {
      const isExpanded = expandedDays.has(day.id);
      const card = renderDayCard(day, isExpanded);
      section.appendChild(card);

      if (day.type === 'workout') {
        const list = renderExerciseList(day.exercises ?? [], locale, isExpanded, day.id);
        list.id = `panel-${day.id}`;
        list.setAttribute('aria-labelledby', card.id);
        card.setAttribute('aria-controls', list.id);
        if (isExpanded) {
          list.style.maxHeight = `${Math.max(list.scrollHeight, 1)}px`;
        }
        section.appendChild(list);
        dayPanels.set(day.id, list);
      }
    }
    fragment.appendChild(section);
  }
  return { fragment, dayPanels };
}

export function renderLegacyProgram(text: string): HTMLElement {
  const section = document.createElement('section');
  section.className = 'legacy-program';
  const blocks = text.trim().split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  if (blocks.length === 0) {
    const paragraph = document.createElement('p');
    paragraph.textContent = text;
    section.appendChild(paragraph);
    return section;
  }
  blocks.forEach((block, index) => {
    const lines = block.split('\n').map((line) => line.trim()).filter(Boolean);
    if (lines.length === 0) return;
    const day = document.createElement('article');
    day.className = 'legacy-program__day';
    const heading = document.createElement(index === 0 ? 'h2' : 'h3');
    heading.className = 'legacy-program__day-title';
    heading.textContent = lines[0];
    day.appendChild(heading);
    if (lines.length > 1) {
      const list = document.createElement('ul');
      list.className = 'legacy-program__list';
      for (let i = 1; i < lines.length; i += 1) {
        const item = document.createElement('li');
        item.className = 'legacy-program__item';
        item.textContent = lines[i];
        list.appendChild(item);
      }
      day.appendChild(list);
    }
    section.appendChild(day);
  });
  return section;
}
