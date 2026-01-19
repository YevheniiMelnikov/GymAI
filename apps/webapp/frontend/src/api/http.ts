import { readLocale } from '../telegram';
import {
  Locale,
  DietPlanDetailResp,
  DietPlanListResp,
  DietPlanOptionsResp,
  PaymentInitResp,
  PaymentPayloadResp,
  Program,
  ProgramResp,
  ProgramStructuredResponse,
  ProfileResp,
  ProfileUpdatePayload,
  SupportContactResp,
  SubscriptionResp,
  SubscriptionStatusResp,
  ExerciseTechniqueResp,
  WorkoutPlanKind,
  WorkoutPlanOptionsResp
} from './types';

const KNOWN_LOCALES: readonly Locale[] = ['en', 'ru', 'uk'];
const LOCALE_ALIASES: Record<string, Locale> = { ua: 'uk' };

function normalizeLocale(raw: string | null | undefined, fallback: Locale): Locale {
  if (!raw) return fallback;
  const lower = raw.toLowerCase();
  if (lower in LOCALE_ALIASES) {
    return LOCALE_ALIASES[lower];
  }
  if ((KNOWN_LOCALES as readonly string[]).includes(lower)) {
    return lower as Locale;
  }
  return fallback;
}

export class HttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function statusToMessage(status: number): string {
  switch (status) {
    case 400:
      return 'bad_request';
    case 401:
    case 403:
      return 'unauthorized';
    case 404:
      return 'not_found';
    case 500:
      return 'server_error';
    default:
      return 'unexpected_error';
  }
}

export type LoadedProgram =
  | { kind: 'structured'; program: Program; locale: Locale }
  | { kind: 'legacy'; programText: string; locale: Locale; createdAt?: string | null };

export type PaymentData = {
  data: string;
  signature: string;
  checkoutUrl: string;
  amount: string;
  currency: string;
  paymentType: string;
  locale: Locale;
};

export type PaymentInitData = PaymentData & { orderId: string };
export type DietPlanListData = { diets: Array<{ id: number; created_at: number }>; locale: Locale };
export type DietPlanDetailData = {
  id: number;
  createdAt: string | null;
  plan: DietPlanDetailResp['plan'] | null;
  locale: Locale;
};

export async function getJSON<T>(url: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
  return (await resp.json()) as T;
}

export async function getExerciseTechnique(
  gifKey: string,
  locale?: Locale,
  signal?: AbortSignal
): Promise<ExerciseTechniqueResp> {
  const resolvedLocale = locale ?? readLocale();
  const url = new URL(`api/technique/${encodeURIComponent(gifKey)}/`, window.location.href);
  url.searchParams.set('lang', resolvedLocale);
  return await getJSON<ExerciseTechniqueResp>(url.toString(), { signal });
}

type GetProgramOpts = {
  initData: string;
  source: 'direct' | 'subscription';
  signal?: AbortSignal;
};

function isStructuredProgram(data: ProgramResp): data is ProgramStructuredResponse {
  return typeof data === 'object' && data !== null && 'days' in data;
}

export async function getProgram(
  programId: string,
  opts: GetProgramOpts
): Promise<LoadedProgram>;
export async function getProgram(
  programId: string,
  locale: Locale,
  opts: GetProgramOpts
): Promise<LoadedProgram>;
export async function getProgram(
  programId: string,
  a: Locale | GetProgramOpts,
  b?: GetProgramOpts
): Promise<LoadedProgram> {
  let locale: Locale = 'en';
  let opts: GetProgramOpts;

  if (typeof a === 'string') {
    locale = a;
    opts = b as GetProgramOpts;
  } else {
    try {
      const tg = (window as any).Telegram?.WebApp;
      const lc = tg?.initDataUnsafe?.user?.language_code;
      if (lc && (['en', 'ru', 'uk'] as Locale[]).includes(lc)) {
        locale = lc as Locale;
      }
    } catch {
    }
    opts = a;
  }

  const params = new URLSearchParams({ locale, source: opts.source });
  if (programId) {
    params.set('program_id', programId);
  }
  const url = new URL('api/program/', window.location.href);
  params.forEach((value, key) => {
    url.searchParams.set(key, value);
  });
  const headers: Record<string, string> = {};
  if (opts.initData) headers['X-Telegram-InitData'] = opts.initData;

  const data = await getJSON<ProgramResp>(url.toString(), { headers, signal: opts.signal });

  const fromResponse = (data as { language?: string | null }).language;
  const resolvedLocale = normalizeLocale(fromResponse ?? (data as { locale?: string }).locale, locale);

  if (isStructuredProgram(data)) {
    const programLocale = normalizeLocale(data.locale, resolvedLocale);
    return {
      kind: 'structured',
      program: {
        ...data,
        locale: programLocale,
        created_at: data.created_at ?? null,
        weeks: data.weeks ?? [],
        days: data.days ?? []
      },
      locale: programLocale
    };
  }

  const createdAtRaw = data.created_at;
  let createdAt: string | null = null;
  if (typeof createdAtRaw === 'number') {
    createdAt = new Date(createdAtRaw * 1000).toISOString();
  } else if (typeof createdAtRaw === 'string') {
    createdAt = createdAtRaw;
  }

  return { kind: 'legacy', programText: data.program, locale: resolvedLocale, createdAt };
}

export async function getSubscription(
  initData: string,
  subscriptionId?: string,
  signal?: AbortSignal
): Promise<SubscriptionResp> {
  const locale = readLocale();
  const url = new URL('api/subscription/', window.location.href);
  if (subscriptionId) {
    url.searchParams.set('subscription_id', subscriptionId);
  }
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;

  const raw = await getJSON<SubscriptionResp>(url.toString(), { headers, signal });
  const resolvedLocale = normalizeLocale(raw.language, locale);
  return {
    ...raw,
    language: resolvedLocale,
  };
}

export async function getSubscriptionStatus(
  initData: string,
  signal?: AbortSignal
): Promise<SubscriptionStatusResp> {
  const url = new URL('api/subscription/status/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  return await getJSON<SubscriptionStatusResp>(url.toString(), { headers, signal });
}

export async function getPaymentData(
  orderId: string,
  initData: string,
  signal?: AbortSignal
): Promise<PaymentData> {
  const locale = readLocale();
  const url = new URL('api/payment/', window.location.href);
  url.searchParams.set('order_id', orderId);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;

  const raw = await getJSON<PaymentPayloadResp>(url.toString(), { headers, signal });
  const resolvedLocale = normalizeLocale(raw.language, locale);
  return {
    data: raw.data,
    signature: raw.signature,
    checkoutUrl: raw.checkout_url,
    amount: raw.amount,
    currency: raw.currency ?? 'UAH',
    paymentType: raw.payment_type ?? '',
    locale: resolvedLocale,
  };
}

export async function initPayment(
  packageId: string,
  initData: string,
  signal?: AbortSignal
): Promise<PaymentInitData> {
  const locale = readLocale();
  const url = new URL('api/payment/init/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;

  const raw = await getJSON<PaymentInitResp>(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify({ package_id: packageId }),
    signal,
  });
  const resolvedLocale = normalizeLocale(raw.language, locale);
  return {
    orderId: raw.order_id,
    data: raw.data,
    signature: raw.signature,
    checkoutUrl: raw.checkout_url,
    amount: raw.amount,
    currency: raw.currency ?? 'UAH',
    paymentType: raw.payment_type ?? '',
    locale: resolvedLocale,
  };
}

export type WorkoutAction = 'create_program' | 'create_subscription';

export async function triggerWorkoutAction(action: WorkoutAction, initData: string): Promise<void> {
  const url = new URL('api/workouts/action/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;

  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify({ action })
  });
  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
  try {
    await resp.json();
  } catch {
  }
}

export type WorkoutPlanCreatePayload = {
  plan_type: WorkoutPlanKind;
  split_number: number;
  period?: '1m' | '6m' | '12m';
  wishes?: string;
};

export type WorkoutPlanCreateResp = {
  status: string;
  subscription_id?: number | null;
  task_id?: string;
};

export async function getWorkoutPlanOptions(
  initData: string,
  signal?: AbortSignal
): Promise<WorkoutPlanOptionsResp> {
  const url = new URL('api/workouts/options/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  return await getJSON<WorkoutPlanOptionsResp>(url.toString(), { headers, signal });
}

export async function createWorkoutPlan(
  payload: WorkoutPlanCreatePayload,
  initData: string
): Promise<WorkoutPlanCreateResp> {
  const url = new URL('api/workouts/create/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;
  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify(payload)
  });
  if (!resp.ok) {
    let errorKey = statusToMessage(resp.status);
    try {
      const data = (await resp.json()) as { error?: string | null };
      if (data && typeof data.error === 'string') {
        errorKey = data.error;
      }
    } catch {
    }
    throw new HttpError(resp.status, errorKey);
  }
  return (await resp.json()) as WorkoutPlanCreateResp;
}

export type ExerciseSetPayload = {
  reps: number;
  weight: number;
};

export type WeeklySurveyExercisePayload = {
  id: string;
  name: string;
  difficulty: number;
  comment?: string | null;
  sets_detail?: Array<ExerciseSetPayload & { weight_unit?: string | null }>;
};

export type WeeklySurveyDayPayload = {
  id: string;
  title?: string | null;
  skipped: boolean;
  exercises: WeeklySurveyExercisePayload[];
};

export type WeeklySurveyPayload = {
  subscription_id: number;
  days: WeeklySurveyDayPayload[];
};

export async function submitWeeklySurvey(payload: WeeklySurveyPayload, initData: string): Promise<void> {
  const url = new URL('api/weekly-survey/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;

  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify(payload)
  });

  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
}

export async function getProfile(initData: string, signal?: AbortSignal): Promise<ProfileResp> {
  const url = new URL('api/profile/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  return await getJSON<ProfileResp>(url.toString(), { headers, signal });
}

export async function getDietPlans(
  initData: string,
  signal?: AbortSignal
): Promise<DietPlanListData> {
  const locale = readLocale();
  const url = new URL('api/diets/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;

  const raw = await getJSON<DietPlanListResp>(url.toString(), { headers, signal });
  const resolvedLocale = normalizeLocale(raw.language, locale);
  return {
    diets: raw.diets ?? [],
    locale: resolvedLocale,
  };
}

export async function getDietPlan(
  initData: string,
  dietId?: string,
  signal?: AbortSignal
): Promise<DietPlanDetailData> {
  const locale = readLocale();
  const url = new URL('api/diet/', window.location.href);
  if (dietId) {
    url.searchParams.set('diet_id', dietId);
  }
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;

  const raw = await getJSON<DietPlanDetailResp>(url.toString(), { headers, signal });
  const resolvedLocale = normalizeLocale(raw.language, locale);
  let createdAt: string | null = null;
  if (typeof raw.created_at === 'number') {
    createdAt = new Date(raw.created_at * 1000).toISOString();
  }
  return {
    id: raw.id ?? 0,
    createdAt,
    plan: raw.plan ?? null,
    locale: resolvedLocale,
  };
}

export async function getDietPlanOptions(
  initData: string,
  signal?: AbortSignal
): Promise<DietPlanOptionsResp> {
  const url = new URL('api/diets/options/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  return await getJSON<DietPlanOptionsResp>(url.toString(), { headers, signal });
}

export async function createDietPlan(initData: string): Promise<{ status: string; task_id?: string }> {
  const url = new URL('api/diets/create/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  const resp = await fetch(url.toString(), { method: 'POST', headers });
  if (!resp.ok) {
    let errorKey: string | null = null;
    try {
      const data = (await resp.json()) as { error?: string | null };
      if (data && typeof data.error === 'string') {
        errorKey = data.error;
      }
    } catch {
    }
    throw new HttpError(resp.status, errorKey ?? statusToMessage(resp.status));
  }
  return (await resp.json()) as { status: string; task_id?: string };
}

export async function updateProfile(payload: ProfileUpdatePayload, initData: string): Promise<ProfileResp> {
  const url = new URL('api/profile/update/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;
  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    let errorKey: string | null = null;
    try {
      const data = (await resp.json()) as { error?: string | null };
      if (data && typeof data.error === 'string') {
        errorKey = data.error;
      }
    } catch {
    }
    throw new HttpError(resp.status, errorKey ?? statusToMessage(resp.status));
  }
  return (await resp.json()) as ProfileResp;
}

export async function deleteProfile(initData: string): Promise<void> {
  const url = new URL('api/profile/delete/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  const resp = await fetch(url.toString(), { method: 'POST', headers });
  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
}

export async function triggerBalanceAction(initData: string): Promise<void> {
  const url = new URL('api/profile/balance/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  const resp = await fetch(url.toString(), { method: 'POST', headers });
  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
}

export async function getSupportContact(initData: string, signal?: AbortSignal): Promise<SupportContactResp> {
  const url = new URL('api/support/', window.location.href);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;
  return await getJSON<SupportContactResp>(url.toString(), { headers, signal });
}

export async function saveExerciseSets(
  programId: string,
  exerciseId: string,
  weightUnit: string | null,
  sets: ExerciseSetPayload[],
  initData: string
): Promise<void> {
  const url = new URL('api/program/exercise/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;

  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      program_id: programId,
      exercise_id: exerciseId,
      weight_unit: weightUnit,
      sets
    })
  });

  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
}

export async function saveSubscriptionExerciseSets(
  subscriptionId: string,
  exerciseId: string,
  weightUnit: string | null,
  sets: ExerciseSetPayload[],
  initData: string
): Promise<void> {
  const url = new URL('api/subscription/exercise/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;

  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      subscription_id: subscriptionId,
      exercise_id: exerciseId,
      weight_unit: weightUnit,
      sets
    })
  });

  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
}

export async function replaceExercise(
  programId: string,
  exerciseId: string,
  initData: string
): Promise<string> {
  const url = new URL('api/program/exercise/replace/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;

  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      program_id: programId,
      exercise_id: exerciseId
    })
  });

  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
  const data = (await resp.json()) as { task_id?: string | null };
  if (!data.task_id) {
    throw new Error('missing_task_id');
  }
  return data.task_id;
}

export async function replaceSubscriptionExercise(
  subscriptionId: string,
  exerciseId: string,
  initData: string
): Promise<string> {
  const url = new URL('api/subscription/exercise/replace/', window.location.href);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) headers['X-Telegram-InitData'] = initData;

  const resp = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      subscription_id: subscriptionId,
      exercise_id: exerciseId
    })
  });

  if (!resp.ok) {
    throw new HttpError(resp.status, statusToMessage(resp.status));
  }
  const data = (await resp.json()) as { task_id?: string | null };
  if (!data.task_id) {
    throw new Error('missing_task_id');
  }
  return data.task_id;
}

export type ReplaceExerciseStatus = {
  status: 'queued' | 'processing' | 'success' | 'error';
  error?: string | null;
};

export async function getReplaceExerciseStatus(
  taskId: string,
  initData: string
): Promise<ReplaceExerciseStatus> {
  const url = new URL('api/program/exercise/replace/status/', window.location.href);
  url.searchParams.set('task_id', taskId);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;

  return getJSON<ReplaceExerciseStatus>(url.toString(), { headers });
}

export async function getReplaceSubscriptionExerciseStatus(
  taskId: string,
  initData: string
): Promise<ReplaceExerciseStatus> {
  const url = new URL('api/subscription/exercise/replace/status/', window.location.href);
  url.searchParams.set('task_id', taskId);
  const headers: Record<string, string> = {};
  if (initData) headers['X-Telegram-InitData'] = initData;

  return getJSON<ReplaceExerciseStatus>(url.toString(), { headers });
}
