export type Locale = 'en' | 'ru' | 'uk';

export type Weight = {
  value: number | string;
  unit: string;
};

export type Exercise = {
  id: string;
  name: string;
  sets: number | string | null;
  reps: number | string | null;
  weight: Weight | null;
  equipment: string | null;
  notes: string | null;
};

export type WorkoutDay = {
  id: string;
  index: number;
  type: 'workout';
  title: string | null;
  exercises: Exercise[];
};

export type RestDay = {
  id: string;
  index: number;
  type: 'rest';
  title: string | null;
};

export type Day = WorkoutDay | RestDay;

export type Week = {
  id?: string;
  index: number;
  days: Day[];
};

export type Program = {
  id: string;
  locale: Locale;
  created_at: string | number | null;
  weeks?: Week[];
  days: Day[];
};

export type ProgramLegacyResponse = {
  program: string;
  created_at?: number | string | null;
  coach_type?: string;
  language?: string;
};

export type ProgramStructuredResponse = Program;

export type ProgramResp = ProgramLegacyResponse | ProgramStructuredResponse;

export type HistoryItem = {
  id: number;
  created_at: number;
  coach_type: string;
};

export type HistoryResp = {
  programs?: HistoryItem[];
  error?: string;
  language?: string;
};

export type SubscriptionResp = {
  program?: string;
  error?: string;
  language?: string;
};
