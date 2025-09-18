export type ProgramRoute = {
  readonly name: 'program';
  readonly programId?: string;
  readonly source?: 'subscription';
};

export type HistoryRoute = {
  readonly name: 'history';
};

export type Route = ProgramRoute | HistoryRoute;

function normalizePath(pathname: string): string[] {
  return pathname
    .replace(/\/+$/, '')
    .split('/')
    .filter(Boolean);
}

export function getRoute(): Route {
  const segments = normalizePath(window.location.pathname);
  if (segments[0] === 'history') {
    return { name: 'history' };
  }
  if (segments[0] === 'program') {
    return { name: 'program', programId: segments[1] };
  }

  const params = new URLSearchParams(window.location.search);
  const page = params.get('page');
  if (page === 'history') {
    return { name: 'history' };
  }
  const programId = params.get('program_id') ?? undefined;
  const source = params.get('type') === 'subscription' ? 'subscription' : undefined;
  return { name: 'program', programId, source };
}

export function goToHistory(): void {
  window.location.assign('history');
}

export function goToProgram(programId?: string): void {
  if (programId) {
    window.location.assign(`./program/${programId}`);
  } else {
    window.location.assign('./');
  }
}
