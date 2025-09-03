export type Route = { route: 'history' } | { route: 'program'; id?: string; type?: 'subscription' };

export function getRoute(): Route {
  const params = new URLSearchParams(window.location.search);
  const page = params.get('page');
  if (page === 'history') return { route: 'history' };
  const id = params.get('program_id') || undefined;
  const type = params.get('type') === 'subscription' ? 'subscription' : undefined;
  return { route: 'program', id, type };
}
