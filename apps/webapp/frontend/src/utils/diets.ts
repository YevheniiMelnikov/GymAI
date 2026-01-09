import { getDietPlans } from '../api/http';

export const fetchLatestDietId = async (initData: string): Promise<number | null> => {
    const data = await getDietPlans(initData);
    const diets = data.diets ?? [];
    if (diets.length === 0) {
        return null;
    }
    const latest = diets.reduce((acc, item) => (item.created_at > acc.created_at ? item : acc));
    return Number.isFinite(latest.id) ? latest.id : null;
};

type LatestDietOptions = {
    attempts?: number;
    delayMs?: number;
};

const sleep = (delayMs: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, delayMs));

export const waitForLatestDietId = async (
    initData: string,
    options: LatestDietOptions = {}
): Promise<number | null> => {
    const attempts = options.attempts ?? 6;
    const delayMs = options.delayMs ?? 1200;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
        try {
            const latestId = await fetchLatestDietId(initData);
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
