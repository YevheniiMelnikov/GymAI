import type { HistoryItem, Locale } from '../api/types';

type WorkoutKind = 'program' | 'subscription';

type HistoryResponse = {
    programs?: HistoryItem[];
    subscriptions?: HistoryItem[];
};

const sleep = (delayMs: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, delayMs));

const getLatestId = (items: HistoryItem[]): number | null => {
    if (items.length === 0) {
        return null;
    }
    const latest = items.reduce((acc, item) => (item.created_at > acc.created_at ? item : acc));
    return Number.isFinite(latest.id) ? latest.id : null;
};

const fetchLatestWorkoutId = async (
    initData: string,
    kind: WorkoutKind,
    locale: Locale
): Promise<number | null> => {
    const url = new URL('/api/programs/', window.location.origin);
    url.searchParams.set('locale', locale);
    const headers: Record<string, string> = {};
    if (initData) {
        headers['X-Telegram-InitData'] = initData;
    }
    const resp = await fetch(url.toString(), { headers });
    if (!resp.ok) {
        return null;
    }
    const data = (await resp.json()) as HistoryResponse;
    const items = kind === 'subscription' ? data.subscriptions : data.programs;
    return getLatestId(Array.isArray(items) ? items : []);
};

export const waitForLatestWorkoutId = async (
    initData: string,
    kind: WorkoutKind,
    locale: Locale,
    options: { attempts?: number; delayMs?: number } = {}
): Promise<number | null> => {
    const attempts = options.attempts ?? 6;
    const delayMs = options.delayMs ?? 1200;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
        try {
            const latestId = await fetchLatestWorkoutId(initData, kind, locale);
            if (latestId) {
                return latestId;
            }
        } catch {
        }
        if (attempt < attempts - 1) {
            await sleep(delayMs);
        }
    }
    return null;
};
