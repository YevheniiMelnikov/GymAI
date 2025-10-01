import { mountProgramView } from './program_view';

export type ProgramViewContext = Parameters<typeof mountProgramView>[0];
export type ProgramCleanup = Awaited<ReturnType<typeof mountProgramView>>;

export async function renderProgram(
  ctx: ProgramViewContext,
  source: 'direct' | 'subscription'
): Promise<ProgramCleanup> {
  return mountProgramView(ctx, source);
}
