export type CoachType = 'human' | 'ai_coach';

export type ProgramResp = {
  program?: string;
  created_at?: number | string;
  coach_type?: CoachType;
  error?: string;
  language?: string;
};

export type HistoryItem = {
  id: number;
  created_at: number;
  coach_type: CoachType;
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
