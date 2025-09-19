export type ProgramRoute = {
  programId?: string;
  source: 'direct' | 'subscription';
};

export function goToHistory(): void {
  window.location.assign('?page=history');
}

export function goToProgram(programId: string, source: 'direct' | 'subscription' = 'direct'): void {
  const url = `?program_id=${encodeURIComponent(programId)}&type=${source}`;
  window.location.assign(url);
}
