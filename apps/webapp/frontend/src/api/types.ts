export type Locale = 'uk' | 'ru' | 'en';

export type ProgramOrigin = 'ai' | 'coach';

export interface Weight {
  readonly value: number;
  readonly unit: 'kg' | 'lb';
}

export interface Exercise {
  readonly id: string;
  readonly name: string;
  readonly sets?: number | null;
  readonly reps?: string | null;
  readonly weight?: Weight | null;
  readonly equipment?: string | null;
  readonly notes?: string | null;
}

export interface Day {
  readonly id: string;
  readonly index: number;
  readonly type: 'workout' | 'rest';
  readonly title: string;
  readonly exercises?: Exercise[] | null;
}

export interface Week {
  readonly index: number;
  readonly days: Day[];
}

export interface Program {
  readonly id: string;
  readonly created_at: string;
  readonly origin?: ProgramOrigin;
  readonly locale: Locale;
  readonly weeks?: Week[];
  readonly days?: Day[];
}

export type ProgramPayload = Program | string;

export interface ProgramResponse {
  readonly program: ProgramPayload;
  readonly created_at?: number | string | null;
  readonly coach_type?: 'ai_coach' | 'human' | null;
  readonly language?: string | null;
  readonly program_id?: string | number | null;
}

export interface HistoryItem {
  readonly id: number;
  readonly created_at: number;
  readonly coach_type: 'human' | 'ai_coach';
}

export interface HistoryResp {
  readonly programs?: HistoryItem[];
  readonly error?: string;
  readonly language?: string;
}
