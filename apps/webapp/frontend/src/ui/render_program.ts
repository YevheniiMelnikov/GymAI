import {
  getReplaceExerciseStatus,
  getReplaceSubscriptionExerciseStatus,
  getExerciseTechnique,
  HttpError,
  PaymentRequiredError,
  replaceExercise,
  replaceSubscriptionExercise,
  ReplaceExerciseStatus,
  saveExerciseSets,
  saveSubscriptionExerciseSets
} from '../api/http';
import { Day, Exercise, ExerciseTechniqueResp, Locale, Program, Week } from '../api/types';
import { t } from '../i18n/i18n';
import { readInitData, readLocale } from '../telegram';

export type RenderedProgram = {
  readonly fragment: DocumentFragment;
};

const techniqueCache = new Map<string, ExerciseTechniqueResp>();
const pendingTechnique = new Map<string, Promise<ExerciseTechniqueResp>>();

function techniqueCacheKey(gifKey: string, locale: Locale): string {
  return `${gifKey}:${locale}`;
}

function preloadTechniqueData(program: Program): void {
  const keys: string[] = [];
  const seen = new Set<string>();
  const locale = readLocale();
  const weeks = ensureWeeks(program);
  weeks.forEach((week) => {
    week.days.forEach((day) => {
      if (day.type !== 'workout') return;
      day.exercises.forEach((exercise) => {
        const gifKey = exercise.gif_key ? String(exercise.gif_key) : '';
        if (!gifKey) return;
        const cacheKey = techniqueCacheKey(gifKey, locale);
        if (seen.has(cacheKey) || techniqueCache.has(cacheKey)) return;
        seen.add(cacheKey);
        keys.push(gifKey);
      });
    });
  });

  if (keys.length === 0) return;

  const preload = () => {
    keys.forEach((gifKey) => {
      const cacheKey = techniqueCacheKey(gifKey, locale);
      if (techniqueCache.has(cacheKey)) return;
      if (!pendingTechnique.has(cacheKey)) {
        const promise = getExerciseTechnique(gifKey, locale)
          .then((data) => {
            techniqueCache.set(cacheKey, data);
            return data;
          })
          .finally(() => {
            pendingTechnique.delete(cacheKey);
          });
        pendingTechnique.set(cacheKey, promise);
      }
    });
  };

  const idleCallback = (
    globalThis as unknown as Window & {
      requestIdleCallback?: (callback: IdleRequestCallback, options?: IdleRequestOptions) => number;
    }
  ).requestIdleCallback;
  if (idleCallback) {
    idleCallback(() => preload(), { timeout: 1500 });
  } else {
    globalThis.setTimeout(preload, 300);
  }
}

function preloadTechniqueGifs(program: Program): void {
  const urls: string[] = [];
  const seen = new Set<string>();
  const weeks = ensureWeeks(program);
  weeks.forEach((week) => {
    week.days.forEach((day) => {
      if (day.type !== 'workout') return;
      day.exercises.forEach((exercise) => {
        const url = exercise.gif_url || (exercise.gif_key ? `/api/gif/${encodeURIComponent(exercise.gif_key)}` : null);
        if (!url || seen.has(url)) return;
        seen.add(url);
        urls.push(url);
      });
    });
  });

  if (urls.length === 0) return;

  const preload = () => {
    urls.forEach((url) => {
      const img = new Image();
      img.decoding = 'async';
      img.loading = 'eager';
      img.src = url;
    });
  };

  const idleCallback = (
    globalThis as unknown as Window & {
      requestIdleCallback?: (callback: IdleRequestCallback, options?: IdleRequestOptions) => number;
    }
  ).requestIdleCallback;
  if (idleCallback) {
    idleCallback(() => preload(), { timeout: 1500 });
  } else {
    globalThis.setTimeout(preload, 300);
  }
}

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

type DisplaySet = {
  readonly reps: number;
  readonly weight: number;
  readonly weightUnit: string | null;
};

type IndexedExercise = {
  readonly exercise: Exercise;
  readonly index: number;
};

type SupersetGroup = {
  readonly kind: 'superset';
  readonly id: number;
  readonly exercises: IndexedExercise[];
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

function formatNumber(value: number): string {
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2).replace(/\.?0+$/, '');
}

function buildDisplaySets(exercise: Exercise): DisplaySet[] {
  if (exercise.sets_detail && exercise.sets_detail.length > 0) {
    return exercise.sets_detail.map((detail) => ({
      reps: Math.max(1, Math.floor(parseNumeric(detail.reps, 1))),
      weight: Math.max(0, parseNumeric(detail.weight, 0)),
      weightUnit: detail.weight_unit ?? null
    }));
  }

  const setsCount = Math.max(1, Math.floor(parseNumeric(exercise.sets, 1)));
  const reps = parseReps(exercise.reps, 1);
  const weight = Math.max(0, parseNumeric(exercise.weight?.value ?? null, 0));
  const weightUnit = exercise.weight?.unit ?? null;
  return Array.from({ length: setsCount }, () => ({
    reps,
    weight,
    weightUnit
  }));
}

function isAuxExercise(exercise: Exercise): boolean {
  const kind = (exercise.kind ?? '').trim().toLowerCase();
  return kind === 'warmup' || kind === 'cardio';
}

function groupExercises(exercises: Exercise[]): Array<IndexedExercise | SupersetGroup> {
  const groups = new Map<number, IndexedExercise[]>();
  exercises.forEach((exercise, index) => {
    const supersetId = exercise.superset_id;
    if (typeof supersetId !== 'number') {
      return;
    }
    if (!groups.has(supersetId)) {
      groups.set(supersetId, []);
    }
    groups.get(supersetId)?.push({ exercise, index });
  });

  const seen = new Set<number>();
  const items: Array<IndexedExercise | SupersetGroup> = [];
  exercises.forEach((exercise, index) => {
    const supersetId = exercise.superset_id;
    if (typeof supersetId !== 'number') {
      items.push({ exercise, index });
      return;
    }
    if (seen.has(supersetId)) {
      return;
    }
    seen.add(supersetId);
    const group = groups.get(supersetId) ?? [];
    if (group.length < 2) {
      items.push({ exercise, index });
      return;
    }
    const orderedGroup = [...group].sort((left, right) => {
      const leftOrder = typeof left.exercise.superset_order === 'number' ? left.exercise.superset_order : null;
      const rightOrder = typeof right.exercise.superset_order === 'number' ? right.exercise.superset_order : null;
      if (leftOrder !== null && rightOrder !== null) {
        return leftOrder - rightOrder;
      }
      if (leftOrder !== null) return -1;
      if (rightOrder !== null) return 1;
      return left.index - right.index;
    });
    items.push({ kind: 'superset', id: supersetId, exercises: orderedGroup });
  });

  return items;
}

const CLOSE_ICON = `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
  <path d="M4 4L12 12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
  <path d="M12 4L4 12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
</svg>`;
const EXERCISE_EDIT_EVENT = 'exercise-edit-dialog';
export const EXERCISE_EDIT_SAVED_EVENT = 'exercise-edit-saved';
export const EXERCISE_TECHNIQUE_EVENT = 'exercise-technique-dialog';

type ProgramSource = 'direct' | 'subscription';
type ProgramContext = {
  programId: string | null;
  source: ProgramSource | null;
};

let programContext: ProgramContext = { programId: null, source: null };

export function setProgramContext(programId: string | null, source: ProgramSource | null): void {
  programContext = { programId, source };
}

type ExerciseEditDialogOptions = {
  allowReplace?: boolean;
  onSave?: (exercise: Exercise, sets: Array<{ reps: number; weight: number }>) => void | Promise<void>;
};

export function openExerciseEditDialog(exercise: Exercise, options?: ExerciseEditDialogOptions): void {
  getExerciseEditDialog().open(exercise, null, options);
}

type ExerciseDialogController = {
  open: (gifUrl?: string | null, exerciseName?: string, gifKey?: string | null) => void;
  close: () => void;
};

type ReplaceExerciseContext = {
  exercise: Exercise;
  details: HTMLDetailsElement;
};

type ReplaceExerciseDialogController = {
  open: (context: ReplaceExerciseContext) => void;
  close: () => void;
};

type EditableSet = {
  id: string;
  reps: number;
  weight: number;
};

type ExerciseEditDialogController = {
  open: (exercise: Exercise, details: HTMLDetailsElement | null, options?: ExerciseEditDialogOptions) => void;
  close: () => void;
};

const REPLACE_DIALOG_ID = 'exercise-replace-dialog';
const REPLACE_POLL_INTERVAL_MS = 1500;
const REPLACE_POLL_MAX_ATTEMPTS = 80;
let exerciseDialog: ReplaceExerciseDialogController | null = null;
const TECHNIQUE_DIALOG_ID = 'exercise-technique-dialog';
let exerciseTechniqueDialog: ExerciseDialogController | null = null;
const EDIT_DIALOG_ID = 'exercise-edit-dialog';
let exerciseEditDialog: ExerciseEditDialogController | null = null;
let editSetCounter = 0;
const isReducedMotionPreferred = (() => {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
})();

function attachDetailsAnimation(details: HTMLDetailsElement, content: HTMLElement): void {
  if (isReducedMotionPreferred) {
    return;
  }
  const summary = details.querySelector('summary');
  if (!summary) {
    return;
  }
  let isAnimating = false;
  let animationTimer: number | null = null;
  let nestedResizeTimer: number | null = null;

  const cleanup = () => {
    content.style.height = '';
    content.style.overflow = '';
    content.style.transition = '';
    isAnimating = false;
    if (animationTimer !== null) {
      window.clearTimeout(animationTimer);
      animationTimer = null;
    }
    if (nestedResizeTimer !== null) {
      window.clearTimeout(nestedResizeTimer);
      nestedResizeTimer = null;
    }
  };

  const animateOpen = () => {
    if (isAnimating) {
      return;
    }
    isAnimating = true;
    details.open = true;
    content.style.height = '0px';
    content.style.overflow = 'hidden';
    content.style.transition = 'height 0.45s ease';
    const targetHeight = content.scrollHeight;
    requestAnimationFrame(() => {
      content.style.height = `${targetHeight}px`;
    });
    const finish = () => {
      content.removeEventListener('transitionend', finish);
      cleanup();
    };
    content.addEventListener('transitionend', finish);
    animationTimer = window.setTimeout(finish, 520);
  };

  const animateClose = () => {
    if (isAnimating) {
      return;
    }
    isAnimating = true;
    if (details.classList.contains('program-day')) {
      const nested = details.querySelectorAll<HTMLDetailsElement>('details.program-exercise-details[open]');
      nested.forEach((item) => {
        item.open = false;
        const nestedContent = item.querySelector<HTMLElement>('.program-exercise-content');
        if (nestedContent) {
          nestedContent.style.height = '';
          nestedContent.style.overflow = '';
          nestedContent.style.transition = '';
        }
      });
    }
    const startHeight = content.scrollHeight;
    content.style.height = `${startHeight}px`;
    content.style.overflow = 'hidden';
    content.style.transition = 'height 0.4s ease';
    requestAnimationFrame(() => {
      content.style.height = '0px';
    });
    const finish = () => {
      content.removeEventListener('transitionend', finish);
      details.open = false;
      cleanup();
    };
    content.addEventListener('transitionend', finish);
    animationTimer = window.setTimeout(finish, 460);
  };

  if (details.classList.contains('program-day')) {
    content.addEventListener('toggle', (event) => {
      const target = event.target as HTMLElement | null;
      if (!target || !target.classList.contains('program-exercise-details')) {
        return;
      }
      if (!details.open) {
        return;
      }
      if (content.style.height) {
        content.style.height = `${content.scrollHeight}px`;
        content.style.overflow = 'hidden';
        if (nestedResizeTimer !== null) {
          window.clearTimeout(nestedResizeTimer);
        }
        nestedResizeTimer = window.setTimeout(() => {
          content.style.height = '';
          content.style.overflow = '';
          content.style.transition = '';
        }, 320);
      }
    });
  }

  summary.addEventListener('click', (event) => {
    if (details.classList.contains('program-day-rest')) {
      return;
    }
    event.preventDefault();
    if (details.open) {
      animateClose();
    } else {
      animateOpen();
    }
  });
}

function getExerciseDialog(): ReplaceExerciseDialogController {
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

  const body = document.createElement('div');
  body.className = 'exercise-dialog__body';

  const message = document.createElement('p');
  message.className = 'exercise-dialog__message';

  const media = document.createElement('img');
  media.className = 'exercise-dialog__media';
  media.loading = 'lazy';
  media.hidden = true;

  const actions = document.createElement('div');
  actions.className = 'exercise-dialog__actions';

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'button-ghost';

  const confirmBtn = document.createElement('button');
  confirmBtn.type = 'button';
  confirmBtn.className = 'primary-button';

  actions.append(cancelBtn, confirmBtn);
  body.append(message, media);
  panel.append(title, body, actions);
  root.appendChild(panel);
  document.body.appendChild(root);

  let replaceContext: ReplaceExerciseContext | null = null;
  let isLoading = false;

  const setLoading = (loading: boolean) => {
    isLoading = loading;
    confirmBtn.disabled = loading;
    cancelBtn.disabled = loading;
    confirmBtn.innerHTML = '';
    confirmBtn.textContent = t('program.exercise.replace_dialog.confirm');
  };

  const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

  type ReplaceStatusLoader = (taskId: string, initData: string) => Promise<ReplaceExerciseStatus>;

  const waitForReplace = async (taskId: string, statusLoader: ReplaceStatusLoader) => {
    const initData = readInitData();
    for (let attempt = 0; attempt < REPLACE_POLL_MAX_ATTEMPTS; attempt += 1) {
      const status = await statusLoader(taskId, initData);
      if (status.status === 'success') {
        return;
      }
      if (status.status === 'error') {
        throw new Error(status.error || 'replace_failed');
      }
      await sleep(REPLACE_POLL_INTERVAL_MS);
    }
    throw new Error('replace_timeout');
  };

  const close = () => {
    root.dataset.state = 'closed';
    root.setAttribute('aria-hidden', 'true');
    document.removeEventListener('keydown', handleKeydown);
    window.dispatchEvent(new CustomEvent(EXERCISE_TECHNIQUE_EVENT, { detail: { open: false } }));
  };

  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  };

  const open = (context: ReplaceExerciseContext) => {
    replaceContext = context;
    title.textContent = t('program.exercise.replace_dialog.title');
    body.textContent = t('program.exercise.replace_dialog.body');
    confirmBtn.textContent = t('program.exercise.replace_dialog.confirm');
    cancelBtn.textContent = t('program.exercise.replace_dialog.cancel');
    setLoading(false);
    root.dataset.state = 'open';
    root.setAttribute('aria-hidden', 'false');
    document.addEventListener('keydown', handleKeydown);
    window.dispatchEvent(new CustomEvent(EXERCISE_TECHNIQUE_EVENT, { detail: { open: true } }));
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
    void (async () => {
      const ctx = replaceContext;
      if (!ctx || isLoading) return;
      if (!programContext.programId) {
        window.alert(t('program.action_error'));
        close();
        return;
      }
      try {
        (window as any).Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('medium');
      } catch {
      }

      const initData = readInitData();
      const isSubscription = programContext.source === 'subscription';
      const replaceAction = isSubscription ? replaceSubscriptionExercise : replaceExercise;
      const statusLoader = isSubscription ? getReplaceSubscriptionExerciseStatus : getReplaceExerciseStatus;

      const runReplace = async (useCredits: boolean) => {
        setLoading(true);
        const editDialog = getExerciseEditDialog();
        editDialog.close();
        ctx.details.open = false;
        ctx.details.classList.add('program-exercise-details--loading');
        close();
        const taskId = await replaceAction(programContext.programId!, ctx.exercise.id, initData, useCredits);
        await waitForReplace(taskId, statusLoader);
        ctx.details.classList.remove('program-exercise-details--loading');
        window.dispatchEvent(new CustomEvent(EXERCISE_EDIT_SAVED_EVENT));
        close();
      };

      try {
        await runReplace(false);
      } catch (err) {
        replaceContext?.details.classList.remove('program-exercise-details--loading');
        if (err instanceof PaymentRequiredError) {
          if (!err.canAfford) {
            window.alert(t('not_enough_credits'));
            setLoading(false);
            return;
          }
          const confirmed = window.confirm(
            t('program.exercise.replace_paid.body', { price: err.price, balance: err.balance })
          );
          if (!confirmed) {
            setLoading(false);
            return;
          }
          try {
            await runReplace(true);
          } catch (paidErr) {
            const messageKey =
              paidErr instanceof HttpError && paidErr.message === 'not_enough_credits' ? 'not_enough_credits' : 'program.action_error';
            window.alert(t(messageKey as any));
            setLoading(false);
          }
          return;
        }
        const message =
          err instanceof HttpError && (err.status === 429 || err.message === 'limit_reached')
            ? t('program.exercise.replace_limit')
            : t('program.action_error');
        window.alert(message);
        setLoading(false);
      }
    })();
  });
  root.addEventListener('click', onBackdropClick);

  exerciseDialog = { open, close };
  return exerciseDialog;
}

function getExerciseTechniqueDialog(): ExerciseDialogController {
  if (exerciseTechniqueDialog) return exerciseTechniqueDialog;

  const root = document.createElement('div');
  root.id = TECHNIQUE_DIALOG_ID;
  root.className = 'exercise-dialog exercise-technique-dialog';
  root.setAttribute('aria-hidden', 'true');

  const panel = document.createElement('div');
  panel.className = 'exercise-dialog__panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-labelledby', `${TECHNIQUE_DIALOG_ID}-title`);
  panel.tabIndex = -1;

  const title = document.createElement('h3');
  title.id = `${TECHNIQUE_DIALOG_ID}-title`;
  title.className = 'exercise-dialog__title';

  const body = document.createElement('div');
  body.className = 'exercise-dialog__body';

  const message = document.createElement('p');
  message.className = 'exercise-dialog__message';

  const media = document.createElement('img');
  media.className = 'exercise-dialog__media';
  media.loading = 'lazy';
  media.hidden = true;

  const techniqueList = document.createElement('ol');
  techniqueList.className = 'exercise-dialog__technique';
  techniqueList.hidden = true;

  const actions = document.createElement('div');
  actions.className = 'exercise-dialog__actions';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'primary-button exercise-dialog__close';

  actions.append(closeBtn);
  body.append(message, media, techniqueList);
  panel.append(title, body, actions);
  root.appendChild(panel);
  document.body.appendChild(root);

  let techniqueAbort: AbortController | null = null;
  let activeTechniqueKey: string | null = null;
  let activeLocale: Locale | null = null;

  const close = () => {
    techniqueAbort?.abort();
    techniqueAbort = null;
    activeTechniqueKey = null;
    activeLocale = null;
    root.dataset.state = 'closed';
    root.setAttribute('aria-hidden', 'true');
    document.removeEventListener('keydown', handleKeydown);
    window.dispatchEvent(new CustomEvent(EXERCISE_TECHNIQUE_EVENT, { detail: { open: false } }));
  };

  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  };

  const open = (gifUrl?: string | null, exerciseName?: string, gifKey?: string | null) => {
    const hasGif = Boolean(gifUrl);
    title.textContent = hasGif ? '' : t('program.exercise.technique.title');
    title.hidden = hasGif;
    message.textContent = t('program.exercise.technique.body');
    closeBtn.textContent = t('program.exercise.technique.close');
    techniqueList.innerHTML = '';
    techniqueList.hidden = true;
    techniqueAbort?.abort();
    techniqueAbort = null;
    activeTechniqueKey = gifKey ? String(gifKey) : null;
    activeLocale = readLocale();
    if (gifUrl) {
      media.src = gifUrl;
      media.alt = exerciseName || t('program.exercise.technique.title');
      media.hidden = false;
      message.hidden = true;
    } else {
      media.removeAttribute('src');
      media.hidden = true;
      message.hidden = false;
      title.hidden = false;
    }
    root.dataset.state = 'open';
    root.setAttribute('aria-hidden', 'false');
    document.addEventListener('keydown', handleKeydown);
    window.dispatchEvent(new CustomEvent(EXERCISE_TECHNIQUE_EVENT, { detail: { open: true } }));
    window.requestAnimationFrame(() => {
      panel.focus();
    });

    if (!gifUrl || !activeTechniqueKey || !activeLocale) {
      return;
    }

    const cacheKey = techniqueCacheKey(activeTechniqueKey, activeLocale);
    const cached = techniqueCache.get(cacheKey);
    if (cached) {
      if (cached.canonical_name) {
        media.alt = cached.canonical_name;
      }
      if (Array.isArray(cached.technique_description) && cached.technique_description.length > 0) {
        const items = cached.technique_description
          .map((step) => String(step || '').trim())
          .filter((step) => step.length > 0);
        if (items.length > 0) {
          items.forEach((step) => {
            const li = document.createElement('li');
            li.textContent = step;
            techniqueList.appendChild(li);
          });
          techniqueList.hidden = false;
        }
      }
      return;
    }

    const abort = new AbortController();
    techniqueAbort = abort;
    const pending = pendingTechnique.get(cacheKey);
    const request = pending ?? getExerciseTechnique(activeTechniqueKey, activeLocale, abort.signal);
    if (!pending) {
      pendingTechnique.set(
        cacheKey,
        Promise.resolve(request)
          .then((data) => {
            techniqueCache.set(cacheKey, data);
            return data;
          })
          .finally(() => {
            pendingTechnique.delete(cacheKey);
          })
      );
    }
    Promise.resolve(request)
      .then((data) => {
        if (abort.signal.aborted) return;
        if (root.dataset.state !== 'open') return;
        if (activeTechniqueKey !== data.gif_key || activeLocale === null) return;
        if (data.canonical_name) {
          media.alt = data.canonical_name;
        }
        if (Array.isArray(data.technique_description) && data.technique_description.length > 0) {
          const items = data.technique_description
            .map((step) => String(step || '').trim())
            .filter((step) => step.length > 0);
          if (items.length > 0) {
            items.forEach((step) => {
              const li = document.createElement('li');
              li.textContent = step;
              techniqueList.appendChild(li);
            });
            techniqueList.hidden = false;
          }
        }
      })
      .catch(() => {
      });
  };

  const onBackdropClick = (event: MouseEvent) => {
    if (event.target === root) {
      event.preventDefault();
      close();
    }
  };

  closeBtn.addEventListener('click', (event) => {
    event.preventDefault();
    close();
  });
  media.addEventListener('error', () => {
    media.removeAttribute('src');
    media.hidden = true;
    message.hidden = false;
    techniqueList.innerHTML = '';
    techniqueList.hidden = true;
  });
  root.addEventListener('click', onBackdropClick);

  exerciseTechniqueDialog = { open, close };
  return exerciseTechniqueDialog;
}

function parseNumeric(value: number | string | null | undefined, fallback: number): number {
  if (value === null || value === undefined || value === '') return fallback;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? fallback : parsed;
}

function parseReps(value: number | string | null | undefined, fallback: number): number {
  if (typeof value === 'number') {
    return Math.max(1, Math.floor(value));
  }
  if (typeof value === 'string') {
    const matches = value.match(/\d+(?:[.,]\d+)?/g);
    if (matches && matches.length > 0) {
      const nums = matches
        .map((item) => Number(item.replace(',', '.')))
        .filter((item) => !Number.isNaN(item));
      if (nums.length > 0) {
        return Math.max(1, Math.floor(Math.max(...nums)));
      }
    }
  }
  return Math.max(1, Math.floor(fallback));
}

function buildInitialSets(exercise: Exercise): EditableSet[] {
  if (exercise.sets_detail && exercise.sets_detail.length > 0) {
    return exercise.sets_detail.map((detail) => ({
      id: `set-${editSetCounter++}`,
      reps: Math.max(1, Math.floor(parseNumeric(detail.reps, 1))),
      weight: Math.max(0, parseNumeric(detail.weight, 0))
    }));
  }

  const setsCount = Math.max(1, Math.floor(parseNumeric(exercise.sets, 1)));
  const reps = parseReps(exercise.reps, 1);
  const weight = Math.max(0, parseNumeric(exercise.weight?.value ?? null, 0));
  return Array.from({ length: setsCount }, () => ({
    id: `set-${editSetCounter++}`,
    reps,
    weight
  }));
}


function getExerciseEditDialog(): ExerciseEditDialogController {
  if (exerciseEditDialog) return exerciseEditDialog;

  const root = document.createElement('div');
  root.id = EDIT_DIALOG_ID;
  root.className = 'exercise-dialog exercise-edit-dialog';
  root.setAttribute('aria-hidden', 'true');

  const panel = document.createElement('div');
  panel.className = 'exercise-dialog__panel exercise-edit-dialog__panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.tabIndex = -1;

  const header = document.createElement('div');
  header.className = 'exercise-edit-dialog__header';

  const title = document.createElement('h3');
  title.className = 'exercise-edit-dialog__title';

  const body = document.createElement('div');
  body.className = 'exercise-edit-dialog__body';

  const listHeader = document.createElement('div');
  listHeader.className = 'exercise-edit-dialog__list-header';
  const listHeaderLabel = document.createElement('div');
  listHeaderLabel.className = 'exercise-edit-dialog__list-header-label';
  const listHeaderFields = document.createElement('div');
  listHeaderFields.className = 'exercise-edit-dialog__fields exercise-edit-dialog__fields-header';
  const listHeaderReps = document.createElement('div');
  listHeaderReps.className = 'exercise-edit-dialog__field-label';
  const listHeaderWeight = document.createElement('div');
  listHeaderWeight.className = 'exercise-edit-dialog__field-label';
  const listHeaderSpacer = document.createElement('div');
  listHeaderSpacer.className = 'exercise-edit-dialog__list-header-spacer';

  listHeaderFields.append(listHeaderReps, listHeaderWeight);
  listHeader.append(listHeaderLabel, listHeaderFields, listHeaderSpacer);

  const list = document.createElement('div');
  list.className = 'exercise-edit-dialog__list';

  const replaceButton = document.createElement('button');
  replaceButton.type = 'button';
  replaceButton.className = 'exercise-edit-dialog__replace';

  const addButton = document.createElement('button');
  addButton.type = 'button';
  addButton.className = 'button-ghost exercise-edit-dialog__add';
  addButton.textContent = t('program.exercise.edit_dialog.add_set');

  const footer = document.createElement('div');
  footer.className = 'exercise-edit-dialog__footer';

  const cancelButton = document.createElement('button');
  cancelButton.type = 'button';
  cancelButton.className = 'button-ghost';
  cancelButton.textContent = t('program.exercise.edit_dialog.cancel');

  const saveButton = document.createElement('button');
  saveButton.type = 'button';
  saveButton.className = 'primary-button';
  saveButton.textContent = t('program.exercise.edit_dialog.save');

  footer.append(cancelButton, saveButton);

  header.append(title);
  body.append(listHeader, list, addButton);
  panel.append(header, body, footer, replaceButton);
  root.appendChild(panel);
  document.body.appendChild(root);

  let currentExercise: Exercise | null = null;
  let currentDetails: HTMLDetailsElement | null = null;
  let currentOptions: ExerciseEditDialogOptions | null = null;
  let initialSets: EditableSet[] = [];
  let sets: EditableSet[] = [];
  let isSaving = false;

  const renderSets = (scrollToLast = false) => {
    list.innerHTML = '';
    sets.forEach((set, index) => {
      const row = document.createElement('div');
      row.className = 'exercise-edit-dialog__set';

      const label = document.createElement('div');
      label.className = 'exercise-edit-dialog__set-label';
      label.textContent = String(index + 1);

      const fields = document.createElement('div');
      fields.className = 'exercise-edit-dialog__fields';

      const repsField = document.createElement('label');
      repsField.className = 'exercise-edit-dialog__field';
      const repsInput = document.createElement('input');
      repsInput.type = 'number';
      repsInput.inputMode = 'numeric';
      repsInput.min = '1';
      repsInput.step = '1';
      repsInput.value = String(set.reps);
      repsInput.className = 'exercise-edit-dialog__input';
      repsInput.setAttribute('aria-label', t('program.exercise.edit_dialog.reps'));
      repsField.append(repsInput);

      const weightField = document.createElement('label');
      weightField.className = 'exercise-edit-dialog__field';
      const weightInput = document.createElement('input');
      weightInput.type = 'number';
      weightInput.inputMode = 'decimal';
      weightInput.min = '0';
      weightInput.step = '0.5';
      weightInput.value = String(set.weight);
      weightInput.className = 'exercise-edit-dialog__input';
      weightInput.setAttribute('aria-label', t('program.exercise.edit_dialog.weight'));
      weightField.append(weightInput);

      const deleteButton = document.createElement('button');
      deleteButton.type = 'button';
      deleteButton.className = 'exercise-edit-dialog__delete';
      deleteButton.innerHTML = CLOSE_ICON;
      deleteButton.setAttribute('aria-label', t('program.exercise.edit_dialog.delete_set'));
      if (sets.length === 1) {
        deleteButton.disabled = true;
      }

      repsInput.addEventListener('input', () => {
        const value = Math.floor(parseNumeric(repsInput.value, set.reps));
        set.reps = Math.max(1, value);
      });
      repsInput.addEventListener('blur', () => {
        repsInput.value = String(set.reps);
      });

      weightInput.addEventListener('input', () => {
        const value = parseNumeric(weightInput.value, set.weight);
        set.weight = Math.max(0, value);
      });
      weightInput.addEventListener('blur', () => {
        weightInput.value = String(set.weight);
      });

      deleteButton.addEventListener('click', (event) => {
        event.preventDefault();
        if (sets.length === 1) return;
        sets = sets.filter((item) => item.id !== set.id);
        renderSets();
      });

      fields.append(repsField, weightField);
      row.append(label, fields, deleteButton);
      list.appendChild(row);
    });

    if (scrollToLast) {
      const last = list.lastElementChild;
      if (last) {
        last.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  };

  const syncButtons = () => {
    cancelButton.textContent = t('program.exercise.edit_dialog.cancel');
    saveButton.textContent = isSaving
      ? t('program.exercise.edit_dialog.saving')
      : t('program.exercise.edit_dialog.save');
    cancelButton.disabled = isSaving;
    saveButton.disabled = isSaving;
    addButton.disabled = isSaving;
  };

  const close = () => {
    root.dataset.state = 'closed';
    root.setAttribute('aria-hidden', 'true');
    document.removeEventListener('keydown', handleKeydown);
    window.dispatchEvent(new CustomEvent(EXERCISE_EDIT_EVENT, { detail: { open: false } }));
  };

  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  };

  const open = () => {
    if (!currentExercise) return;
    title.textContent = currentExercise.name;
    panel.setAttribute('aria-label', t('program.exercise.edit'));
    root.dataset.state = 'open';
    root.setAttribute('aria-hidden', 'false');
    document.addEventListener('keydown', handleKeydown);
    window.dispatchEvent(new CustomEvent(EXERCISE_EDIT_EVENT, { detail: { open: true } }));
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

  root.addEventListener('click', onBackdropClick);

  addButton.addEventListener('click', (event) => {
    event.preventDefault();
    const last = sets[sets.length - 1];
    const clone = {
      id: `set-${editSetCounter++}`,
      reps: last ? last.reps : 1,
      weight: last ? last.weight : 0
    };
    sets = [...sets, clone];
    renderSets(true);
  });

  cancelButton.addEventListener('click', (event) => {
    event.preventDefault();
    sets = initialSets.map((set) => ({ ...set }));
    close();
  });

  replaceButton.addEventListener('click', (event) => {
    event.preventDefault();
    if (!currentExercise || !currentDetails) return;
    getExerciseDialog().open({ exercise: currentExercise, details: currentDetails });
  });

  saveButton.addEventListener('click', async (event) => {
    event.preventDefault();
    if (!currentExercise || isSaving) return;
    if (currentOptions?.onSave) {
      isSaving = true;
      syncButtons();
      try {
        await currentOptions.onSave(currentExercise, sets.map((set) => ({ reps: set.reps, weight: set.weight })));
        close();
      } finally {
        isSaving = false;
        syncButtons();
      }
      return;
    }
    if (!programContext.programId) {
      window.alert(t('program.action_error'));
      return;
    }
    try {
      (window as any).Telegram?.WebApp?.HapticFeedback?.impactOccurred?.('medium');
    } catch {
    }
    isSaving = true;
    syncButtons();
    try {
      const initData = readInitData();
      const weightUnit =
        currentExercise.weight?.unit ?? currentExercise.sets_detail?.[0]?.weight_unit ?? null;
      const payload = sets.map((set) => ({ reps: set.reps, weight: set.weight }));
      if (programContext.source === 'direct') {
        await saveExerciseSets(programContext.programId, currentExercise.id, weightUnit, payload, initData);
      } else if (programContext.source === 'subscription') {
        await saveSubscriptionExerciseSets(programContext.programId, currentExercise.id, weightUnit, payload, initData);
      } else {
        window.alert(t('program.action_error'));
        return;
      }
      window.dispatchEvent(new CustomEvent(EXERCISE_EDIT_SAVED_EVENT));
      close();
    } finally {
      isSaving = false;
      syncButtons();
    }
  });

  exerciseEditDialog = {
    open: (exercise: Exercise, details: HTMLDetailsElement | null, options?: ExerciseEditDialogOptions) => {
      const allowReplace = options?.allowReplace !== false;
      currentExercise = exercise;
      currentDetails = details;
      currentOptions = options ?? null;
      initialSets = buildInitialSets(exercise);
      sets = initialSets.map((set) => ({ ...set }));
      addButton.textContent = t('program.exercise.edit_dialog.add_set');
      title.textContent = exercise.name;
      listHeaderLabel.textContent = t('program.exercise.edit_dialog.set');
      listHeaderReps.textContent = t('program.exercise.edit_dialog.reps');
      listHeaderWeight.textContent = t('program.exercise.edit_dialog.weight');
      replaceButton.textContent = t('program.exercise.replace');
      replaceButton.style.display = allowReplace ? '' : 'none';
      replaceButton.disabled = !allowReplace;
      replaceButton.tabIndex = allowReplace ? 0 : -1;
      renderSets();
      syncButtons();
      open();
    },
    close
  };
  return exerciseEditDialog;
}

function createExerciseActions(details: HTMLDetailsElement, exercise: Exercise, exerciseTitle: string): HTMLDivElement {
  const actions = document.createElement('div');
  actions.className = 'program-exercise-actions';

  const techniqueButton = document.createElement('button');
  techniqueButton.type = 'button';
  techniqueButton.className = 'program-exercise-technique-btn';
  techniqueButton.textContent = t('program.exercise.technique.button');

  const techniqueDialog = getExerciseTechniqueDialog();
  const openTechniqueDialog = () => {
    const resolvedGifUrl =
      exercise.gif_url ||
      (exercise.gif_key ? `/api/gif/${encodeURIComponent(exercise.gif_key)}` : null);
    if (!details.open) {
      details.open = true;
    }
    techniqueDialog.open(resolvedGifUrl, exerciseTitle, exercise.gif_key ?? null);
  };
  techniqueButton.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    openTechniqueDialog();
  });

  const editButton = document.createElement('button');
  editButton.type = 'button';
  editButton.className = 'program-exercise-edit-btn';
  editButton.textContent = t('program.exercise.edit');

  const editDialog = getExerciseEditDialog();
  editButton.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!details.open) {
      details.open = true;
    }
    editDialog.open(exercise, details);
  });

  actions.append(techniqueButton, editButton);
  return actions;
}

function createExerciseItem(ex: Exercise, index: number): HTMLLIElement {
  const li = document.createElement('li');
  li.className = 'program-exercise';

  const details = document.createElement('details');
  details.className = 'program-exercise-details';
  const hasSuperset = typeof ex.superset_id === 'number';
  const auxExercise = isAuxExercise(ex);

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
  if (hasSuperset) {
    const supersetTag = document.createElement('span');
    supersetTag.className = 'program-exercise-tag program-exercise-tag--superset';
    supersetTag.textContent = t('program.exercise.superset_label');
    summary.appendChild(supersetTag);
  }
  details.appendChild(summary);

  const content = document.createElement('div');
  content.className = 'program-exercise-content';

  const note = sanitizeNote(ex.notes);
  const detailParts: string[] = [...presentation.extraDetails];
  if (ex.equipment) detailParts.push(`Equipment: ${ex.equipment}`);
  const meaningfulDetails = detailParts.filter((part) => !isNoiseToken(part));
  if (meaningfulDetails.length > 0) {
    const meta = document.createElement('div');
    meta.className = 'program-exercise-meta';
    meta.textContent = meaningfulDetails.join(', ');
    content.appendChild(meta);
  }

  if (ex.drop_set) {
    const flags = document.createElement('div');
    flags.className = 'program-exercise-flags';
    const dropTag = document.createElement('span');
    dropTag.className = 'program-exercise-tag program-exercise-tag--drop';
    dropTag.textContent = t('program.exercise.drop_set_label');
    flags.appendChild(dropTag);
    content.appendChild(flags);
  }

  let setsTable: HTMLDivElement | null = null;
  if (!auxExercise) {
    const sets = buildDisplaySets(ex);
    if (sets.length > 0) {
      const table = document.createElement('div');
      table.className = 'exercise-sets-table';

      const header = document.createElement('div');
      header.className = 'exercise-sets-table__row exercise-sets-table__row--header';

      const setHeader = document.createElement('div');
      setHeader.className = 'exercise-sets-table__cell';
      setHeader.textContent = t('program.exercise.edit_dialog.set');

      const repsHeader = document.createElement('div');
      repsHeader.className = 'exercise-sets-table__cell';
      repsHeader.textContent = t('program.exercise.edit_dialog.reps');

      const weightHeader = document.createElement('div');
      weightHeader.className = 'exercise-sets-table__cell';
      weightHeader.textContent = t('program.exercise.edit_dialog.weight');

      header.append(setHeader, repsHeader, weightHeader);
      table.appendChild(header);

      sets.forEach((set, setIndex) => {
        const row = document.createElement('div');
        row.className = 'exercise-sets-table__row';

        const setCell = document.createElement('div');
        setCell.className = 'exercise-sets-table__cell';
        setCell.textContent = String(setIndex + 1);

        const repsCell = document.createElement('div');
        repsCell.className = 'exercise-sets-table__cell';
        repsCell.textContent = formatNumber(set.reps);

        const weightCell = document.createElement('div');
        weightCell.className = 'exercise-sets-table__cell';
        const weightValue = formatNumber(set.weight);
        weightCell.textContent =
          set.weight <= 0 ? '—' : set.weightUnit ? `${weightValue} ${set.weightUnit}` : weightValue;

        row.append(setCell, repsCell, weightCell);
        table.appendChild(row);
      });

      setsTable = table;
    }
  }

  if (note) {
    const notes = document.createElement('p');
    notes.className = 'program-exercise-notes';
    notes.textContent = note;
    if (auxExercise) {
      notes.style.whiteSpace = 'pre-line';
    }
    content.appendChild(notes);
  }

  if (content.childElementCount === 0) {
    content.classList.add('program-exercise-content--minimal');
  }

  if (!auxExercise) {
    const actions = createExerciseActions(details, ex, title);
    content.appendChild(actions);
    if (setsTable) {
      content.appendChild(setsTable);
      const editButton = actions.querySelector<HTMLButtonElement>('.program-exercise-edit-btn');
      if (editButton) {
        content.appendChild(editButton);
      }
    }
  } else if (setsTable) {
    content.appendChild(setsTable);
  }
  details.appendChild(content);
  attachDetailsAnimation(details, content);
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
    const grouped = groupExercises(day.exercises);
    grouped.forEach((item) => {
      if ('kind' in item) {
        const groupItem = document.createElement('li');
        groupItem.className = 'program-exercise-group';
        const groupList = document.createElement('ul');
        groupList.className = 'program-exercise-group__list';
        item.exercises.forEach((entry) => {
          groupList.appendChild(createExerciseItem(entry.exercise, entry.index));
        });
        groupItem.appendChild(groupList);
        list.appendChild(groupItem);
        return;
      }
      list.appendChild(createExerciseItem(item.exercise, item.index));
    });
    details.appendChild(list);
    attachDetailsAnimation(details, list);
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
  preloadTechniqueGifs(program);
  preloadTechniqueData(program);
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
