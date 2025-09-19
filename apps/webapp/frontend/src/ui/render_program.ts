import { Day, Exercise, Locale, Program, Week } from '../api/types';
import { TemplateParams, t } from '../i18n/i18n';

const dateFormatterCache = new Map<string, Intl.DateTimeFormat>();
const numberFormatterCache = new Map<string, Intl.NumberFormat>();

export type RenderedProgram = {
  readonly fragment: DocumentFragment;
  readonly days: Map<string, { button: HTMLButtonElement; panel: HTMLDivElement }>;
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

const LEGACY_DAY_HEADERS = [
  /^\s*День\s*(\d+)\s*(?:—|–|:|-)?\s*(.+)?$/i,
  /^\s*Day\s*(\d+)\s*(?:—|–|:|-)?\s*(.+)?$/i
];

const REST_TOKENS = [/rest/i, /відпочинок/i, /отдых/i];

type LegacyParsedDay = {
  readonly index: number;
  readonly title: string;
  readonly lines: readonly string[];
  readonly type: 'workout' | 'rest';
};

function matchLegacyDayHeader(header: string): { index: number; title: string } | null {
  for (const pattern of LEGACY_DAY_HEADERS) {
    const match = header.match(pattern);
    if (!match) continue;
    const parsedIndex = Number.parseInt(match[1] ?? '', 10);
    if (!Number.isFinite(parsedIndex)) continue;
    const rawTitle = (match[2] ?? '').trim();
    return {
      index: parsedIndex,
      title: rawTitle || header.replace(pattern, '').trim() || header
    };
  }
  return null;
}

function detectRestDay(title: string, lines: readonly string[]): boolean {
  if (lines.length > 0) return false;
  return REST_TOKENS.some((pattern) => pattern.test(title));
}

function parseLegacyDays(text: string): LegacyParsedDay[] {
  const trimmed = text.trim();
  if (!trimmed) {
    return [];
  }
  const rawBlocks = trimmed
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);

  const parsed: LegacyParsedDay[] = [];

  rawBlocks.forEach((block, blockIndex) => {
    const lines = block.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length === 0) {
      return;
    }
    const header = lines[0];
    const matched = matchLegacyDayHeader(header);
    const displayIndex = matched?.index ?? blockIndex + 1;
    const title = matched?.title ?? header;
    const rest = lines.slice(1);
    const hasExercises = rest.length > 0;
    const isRest = detectRestDay(title, rest) || !hasExercises;
    parsed.push({
      index: displayIndex,
      title,
      lines: isRest ? [] : rest,
      type: isRest ? 'rest' : 'workout'
    });
  });

  if (parsed.length === 0) {
    const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length === 0) {
      return [];
    }
    const [firstLine, ...rest] = lines;
    const exercises = rest;
    const hasExercises = exercises.length > 0;
    const isRest = detectRestDay(firstLine, exercises) || !hasExercises;
    parsed.push({
      index: 1,
      title: isRest ? t('program.day.rest') : firstLine,
      lines: isRest ? [] : exercises,
      type: isRest ? 'rest' : 'workout'
    });
  }

  return parsed;
}

function createLegacyDays(data: readonly LegacyParsedDay[]): Day[] {
  return data.map((day, order) => {
    const displayIndex = Number.isFinite(day.index) && day.index > 0 ? day.index : order + 1;
    const dayId = `legacy-${String(displayIndex).padStart(2, '0')}-${order + 1}`;
    const exercises: Exercise[] =
      day.type === 'workout'
        ? day.lines.map((line, exerciseIndex) => ({
            id: `${dayId}-ex-${exerciseIndex + 1}`,
            name: line,
            sets: null,
            reps: null,
            weight: null,
            equipment: null,
            notes: null
          }))
        : [];
    return {
      id: dayId,
      index: displayIndex,
      type: day.type,
      title: day.title,
      exercises
    };
  });
}

function isBodyweightEquipment(equipment: string | null | undefined): boolean {
  if (!equipment) {
    return true;
  }
  return /body\s*weight|вага\s*тіла|own\s*weight/i.test(equipment);
}

function collectExerciseMeta(exercise: Exercise, locale: string): string[] {
  const metaPieces: string[] = [];
  if (typeof exercise.sets === 'number' && exercise.reps) {
    metaPieces.push(fmtSetsReps(exercise.sets, exercise.reps));
  } else if (exercise.reps) {
    metaPieces.push(exercise.reps);
  }
  if (exercise.weight) {
    metaPieces.push(fmtWeight(exercise.weight.value, exercise.weight.unit, locale));
  }
  const equipment = exercise.equipment?.trim();
  if (!exercise.weight && isBodyweightEquipment(equipment ?? null)) {
    metaPieces.push(t('program.ex.bodyweight'));
  }
  if (equipment) {
    metaPieces.push(equipment);
  }
  return metaPieces;
}

function createExerciseItem(exercise: Exercise, index: number, locale: string): HTMLLIElement {
  const item = document.createElement('li');
  item.className = 'exercise-item';

  const order = document.createElement('span');
  order.className = 'exercise-index';
  order.textContent = `${index + 1}.`;
  item.appendChild(order);

  const body = document.createElement('div');
  body.className = 'exercise-body';

  const name = document.createElement('div');
  name.className = 'exercise-name';
  name.textContent = exercise.name;
  body.appendChild(name);

  const metaPieces = collectExerciseMeta(exercise, locale);
  if (metaPieces.length > 0) {
    const meta = document.createElement('div');
    meta.className = 'exercise-meta';
    meta.textContent = metaPieces.join(' | ');
    body.appendChild(meta);
  }

  if (exercise.notes) {
    const notes = document.createElement('div');
    notes.className = 'exercise-notes';
    notes.textContent = exercise.notes;
    body.appendChild(notes);
  }

  item.appendChild(body);
  return item;
}

function renderWorkoutDay(
  day: Day,
  locale: string
): { container: HTMLElement; entry: { button: HTMLButtonElement; panel: HTMLDivElement } } {
  const container = document.createElement('article');
  container.className = 'program-day';

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'day-toggle';
  button.dataset.dayId = day.id;
  button.id = `day-${day.id}`;
  button.setAttribute('aria-expanded', 'false');
  button.textContent = t('program.day', { n: day.index, title: day.title });
  container.appendChild(button);

  const panel = document.createElement('div');
  panel.className = 'day-panel';
  panel.id = `panel-${day.id}`;
  panel.setAttribute('aria-labelledby', button.id);
  panel.setAttribute('aria-hidden', 'true');
  panel.hidden = true;

  const list = document.createElement('ul');
  list.className = 'exercise-list';
  (day.exercises ?? []).forEach((exercise, index) => {
    list.appendChild(createExerciseItem(exercise, index, locale));
  });
  panel.appendChild(list);
  container.appendChild(panel);

  button.setAttribute('aria-controls', panel.id);

  return { container, entry: { button, panel } };
}

function renderRestDay(day: Day): HTMLElement {
  const container = document.createElement('article');
  container.className = 'program-day program-day--rest';

  const label = document.createElement('div');
  label.className = 'day-rest';
  label.textContent = t('program.day', { n: day.index, title: t('program.day.rest') });
  container.appendChild(label);

  return container;
}

export function renderProgramDays(
  program: Program,
  locale: string,
  expandedDays: Set<string>
): RenderedProgram {
  const fragment = document.createDocumentFragment();
  const days = new Map<string, { button: HTMLButtonElement; panel: HTMLDivElement }>();
  const weeks = ensureWeeks(program);

  weeks.forEach((week) => {
    const section = document.createElement('section');
    section.className = 'week';

    const heading = document.createElement('h2');
    heading.className = 'week-title';
    heading.textContent = t('program.week', { n: week.index });
    section.appendChild(heading);

    week.days.forEach((day) => {
      if (day.type === 'workout') {
        const renderedDay = renderWorkoutDay(day, locale);
        const isExpanded = expandedDays.has(day.id);
        renderedDay.entry.button.setAttribute('aria-expanded', String(isExpanded));
        renderedDay.entry.button.classList.toggle('day-toggle--expanded', isExpanded);
        renderedDay.entry.panel.hidden = !isExpanded;
        renderedDay.entry.panel.setAttribute('aria-hidden', String(!isExpanded));
        section.appendChild(renderedDay.container);
        days.set(day.id, renderedDay.entry);
      } else {
        section.appendChild(renderRestDay(day));
      }
    });

    fragment.appendChild(section);
  });

  return { fragment, days };
}

export function renderLegacyProgram(
  text: string,
  locale: Locale,
  expandedDays: Set<string>
): RenderedProgram {
  const parsed = parseLegacyDays(text);
  if (parsed.length === 0) {
    const fragment = document.createDocumentFragment();
    if (text.trim()) {
      const paragraph = document.createElement('p');
      paragraph.textContent = text.trim();
      fragment.appendChild(paragraph);
    }
    return { fragment, days: new Map() };
  }
  const legacyDays = createLegacyDays(parsed);
  const program: Program = {
    id: 'legacy',
    created_at: new Date().toISOString(),
    locale,
    weeks: [
      {
        index: 1,
        days: legacyDays
      }
    ],
    days: legacyDays
  };
  return renderProgramDays(program, locale, expandedDays);
}
