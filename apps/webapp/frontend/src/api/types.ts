export type Locale = 'en' | 'ru' | 'uk';

export type Weight = {
  value: number | string;
  unit: string;
};

export type ExerciseSetDetail = {
  reps: number;
  weight: number;
  weight_unit?: string | null;
};

export type Exercise = {
  id: string;
  set_id?: number | null;
  name: string;
  sets: number | string | null;
  reps: number | string | null;
  weight: Weight | null;
  sets_detail?: ExerciseSetDetail[] | null;
  equipment: string | null;
  notes: string | null;
  drop_set?: boolean;
  superset_id?: number | null;
  superset_order?: number | null;
  gif_key?: string | null;
  gif_url?: string | null;
};

export type ExerciseTechniqueResp = {
  gif_key: string;
  canonical_name: string;
  technique_description: string[];
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
  language?: string;
};

export type ProgramStructuredResponse = Program;

export type ProgramResp = ProgramLegacyResponse | ProgramStructuredResponse;

export type HistoryItem = {
  id: number;
  created_at: number;
};

export type HistoryResp = {
    programs?: HistoryItem[];
    subscriptions?: HistoryItem[];
    error?: string;
    language?: string;
};

export type SubscriptionResp = {
  program?: string;
  days?: Day[];
  id?: string;
  error?: string;
  language?: string;
  created_at?: number | string | null;
};

export type DietPlanItem = {
  name: string;
  grams: number;
  calories: number;
  protein_g: number;
  fat_g: number;
  carbs_g: number;
};

export type DietMeal = {
  name: string;
  items: DietPlanItem[];
  totals: {
    calories: number;
    protein_g: number;
    fat_g: number;
    carbs_g: number;
  };
};

export type DietPlan = {
  meals: DietMeal[];
  totals: {
    calories: number;
    protein_g: number;
    fat_g: number;
    carbs_g: number;
  };
  notes?: string[];
  schema_version?: string | null;
};

export type DietPlanSummary = {
  id: number;
  created_at: number;
};

export type DietPlanListResp = {
  diets?: DietPlanSummary[];
  language?: string;
  error?: string;
};

export type DietPlanDetailResp = {
  id?: number;
  created_at?: number;
  plan?: DietPlan;
  language?: string;
  error?: string;
};

export type DietPlanOptionsResp = {
  price: number;
};

export type SubscriptionStatusResp = {
  active: boolean;
  id?: string;
  error?: string;
};

export type PaymentPayloadResp = {
  data: string;
  signature: string;
  checkout_url: string;
  amount: string;
  currency?: string;
  payment_type?: string;
  language?: string | null;
};

export type PaymentInitResp = {
  order_id: string;
  data: string;
  signature: string;
  checkout_url: string;
  amount: string;
  currency?: string;
  payment_type?: string;
  language?: string | null;
};

export type DietProduct = 'plant_food' | 'meat' | 'fish_seafood' | 'eggs' | 'dairy';
export type WorkoutExperience = 'beginner' | 'amateur' | 'advanced' | 'pro';
export type WorkoutLocation = 'gym' | 'home';
export type Gender = 'male' | 'female';

export type ProfileResp = {
  id: number;
  tg_id: number | null;
  language: string;
  status: string;
  gender: Gender | null;
  born_in: number | null;
  weight: number | null;
  height: number | null;
  health_notes: string | null;
  workout_experience: WorkoutExperience | null;
  workout_goals: string | null;
  diet_allergies: string | null;
  diet_products: DietProduct[] | null;
  workout_location: WorkoutLocation | null;
  credits: number | null;
};

export type WorkoutPlanKind = 'program' | 'subscription';

export type SubscriptionPlanOption = {
  period: '1m' | '6m' | '12m';
  months: number;
  price: number;
};

export type WorkoutPlanOptionsResp = {
  program_price: number;
  subscriptions: SubscriptionPlanOption[];
};

export type ProfileUpdatePayload = {
  gender?: Gender | null;
  born_in?: number | null;
  weight?: number | null;
  height?: number | null;
  health_notes?: string | null;
  workout_experience?: WorkoutExperience | null;
  workout_goals?: string | null;
  diet_allergies?: string | null;
  diet_products?: DietProduct[] | null;
  workout_location?: WorkoutLocation | null;
  language?: string | null;
};

export type SupportContactResp = {
  url: string;
};
