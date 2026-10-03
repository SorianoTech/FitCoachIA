export interface Exercise {
  exercise_id: string;
  name: string;
  sets: number;
  reps: string;
  rest_seconds: number;
  rpe: number | null;
  notes: string | null;
}

export interface TrainingDay {
  day: number;
  focus: string;
  exercises: Exercise[];
  estimated_minutes: number;
}

export interface TrainingWeek {
  week: number;
  intensity: string;
  days: TrainingDay[];
}

export interface Bootstrap {
  plan_id: number;
  version: number;
  plan: {
    goal: string;
    days_per_week: number;
    environment: string;
    weeks: TrainingWeek[];
    excluded_by_injury: string[];
    progression_notes: string;
  };
  cycle: {
    id: number;
    started_at: string;
    expected_end_at: string;
    completed_at: string | null;
  } | null;
  current_week: number | null;
  calendar_status: string;
}

export interface ActualSet {
  number: number;
  reps: number | null;
  duration_seconds: number | null;
  weight_kg: number | null;
  rpe: number | null;
  completed: boolean;
}

export interface ActualExercise {
  position: number;
  skipped: boolean;
  sets: ActualSet[];
}

export interface WorkoutSession {
  id: number;
  plan_id: number;
  mesocycle_id: number | null;
  week: number;
  day: number;
  revision: number;
  status: 'in_progress' | 'completed';
  started_at: string;
  completed_at: string | null;
  prescription: TrainingDay;
  exercises: ActualExercise[];
}

export interface ExerciseProgress {
  exercise_id: string;
  name: string;
  history: {
    date: string;
    session_id: number;
    total_reps: number | null;
    total_duration_seconds: number | null;
    total_sets: number;
    max_weight_kg: number | null;
    average_rpe: number | null;
  }[];
}

export interface Progress {
  completed_sessions: number;
  history_limit: number;
  history_truncated: boolean;
  exercises: ExerciseProgress[];
}

export interface BotAction {
  message: string;
  bot_url: string;
}

export interface TelegramWebApp {
  initData: string;
  ready(): void;
  expand(): void;
  enableClosingConfirmation(): void;
  disableClosingConfirmation(): void;
  openTelegramLink(url: string): void;
  onEvent(event: string, callback: () => void): void;
  offEvent(event: string, callback: () => void): void;
  BackButton: {
    show(): void;
    hide(): void;
    onClick(callback: () => void): void;
    offClick(callback: () => void): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}
