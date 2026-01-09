export const loadFavoriteIds = (key: string): Set<number> => {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return new Set();
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return new Set();
    }
    return new Set(parsed.map((value) => Number(value)).filter(Number.isFinite));
  } catch {
    return new Set();
  }
};

export const toggleFavoriteId = (key: string, ids: Set<number>, id: number): Set<number> => {
  if (!Number.isFinite(id)) {
    return new Set(ids);
  }
  const next = new Set(ids);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  try {
    window.localStorage.setItem(key, JSON.stringify([...next]));
  } catch {
  }
  return next;
};
