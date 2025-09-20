export type ProgramRoute = { kind: 'program'; source: 'direct' | 'subscription' };
export type HistoryRoute = { kind: 'history' };
export type Route = ProgramRoute | HistoryRoute;

type NavCb = (r: Route) => void;
let listeners: NavCb[] = [];

export function parseRoute(loc: Location): Route {
  const url = new URL(loc.href);
  const type = (url.searchParams.get('type') || 'program').toLowerCase();
  if (type === 'history') return { kind: 'history' };
  const source = (url.searchParams.get('source') || 'direct') as 'direct' | 'subscription';
  return { kind: 'program', source };
}

export function goToHistory(): void {
  const url = new URL(location.href);
  url.searchParams.set('type', 'history');
  history.pushState({}, '', url.toString());
  emit();
}

export function goToProgram(source: 'direct' | 'subscription' = 'direct'): void {
  const url = new URL(location.href);
  url.searchParams.set('type', 'program');
  url.searchParams.set('source', source);
  history.pushState({}, '', url.toString());
  emit();
}

function emit() {
  const r = parseRoute(location);
  listeners.forEach((cb) => cb(r));
}

export function initRouter(): void {
  emit();
}

export function onRouteChange(cb: NavCb): void {
  listeners.push(cb);
}

window.addEventListener('popstate', () => emit());
