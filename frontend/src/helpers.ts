import type { ActualExercise, ActualSet, ExerciseProgress, TrainingDay, WorkoutSession } from './types';

export interface DraftSet {
  number: number;
  reps: string;
  duration_seconds: string;
  weight_kg: string;
  rpe: string;
  completed: boolean;
}

export interface DraftExercise {
  position: number;
  skipped: boolean;
  sets: DraftSet[];
}

const text = (value: number | null) => value === null ? '' : String(value);

export function toDraft(exercises: ActualExercise[]): DraftExercise[] {
  return exercises.map(exercise => ({
    ...exercise,
    sets: exercise.sets.map(set => ({
      ...set,
      reps: text(set.reps),
      duration_seconds: text(set.duration_seconds),
      weight_kg: text(set.weight_kg),
      rpe: text(set.rpe),
    })),
  }));
}

function numberInput(value: string, label: string, max: number, integer: boolean, zero = false) {
  if (!value.trim()) return null;
  // Commas from decimal mobile keyboards are accepted, but partial/invalid input is never erased.
  const normalized = value.trim().replace(',', '.');
  if (!/^\d+(?:\.\d+)?$/.test(normalized)) throw new Error(`${label}: introduce un número válido.`);
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed < (zero ? 0 : 1) || parsed > max ||
      (integer && !Number.isInteger(parsed))) {
    throw new Error(`${label}: valor fuera de rango${integer ? ' (debe ser entero)' : ''}.`);
  }
  return parsed;
}

export function serializeDraft(draft: DraftExercise[]): ActualExercise[] {
  return draft.map(exercise => ({
    position: exercise.position,
    skipped: exercise.skipped,
    sets: exercise.sets.map(set => {
      const prefix = `Ejercicio ${exercise.position + 1}, serie ${set.number}`;
      const actual: ActualSet = {
        number: set.number,
        reps: numberInput(set.reps, `${prefix}, repeticiones`, 10000, true),
        duration_seconds: numberInput(set.duration_seconds, `${prefix}, segundos`, 86400, true),
        weight_kg: numberInput(set.weight_kg, `${prefix}, peso`, 2000, false, true),
        rpe: numberInput(set.rpe, `${prefix}, RPE`, 10, false),
        completed: set.completed,
      };
      if (actual.completed && actual.reps === null && actual.duration_seconds === null) {
        throw new Error(`${prefix}: indica repeticiones o duración antes de marcarla hecha.`);
      }
      return actual;
    }),
  }));
}

export function validateCompletion(exercises: ActualExercise[], prescription: TrainingDay): void {
  for (let position = 0; position < prescription.exercises.length; position++) {
    const exercise = exercises.find(item => item.position === position);
    if (!exercise) throw new Error('Faltan ejercicios en la sesión. Recarga antes de continuar.');
    if (exercise.skipped) continue;
    const prescribed = prescription.exercises[position];
    for (let number = 1; number <= prescribed.sets; number++) {
      const set = exercise.sets.find(item => item.number === number);
      if (!set?.completed || (set.reps === null && set.duration_seconds === null)) {
        throw new Error(`Completa las ${prescribed.sets} series de ${prescribed.name} o marca el ejercicio como omitido.`);
      }
    }
  }
}

export function isDirty(session: WorkoutSession | null, draft: DraftExercise[]): boolean {
  return !!session && JSON.stringify(toDraft(session.exercises)) !== JSON.stringify(draft);
}

export function remainingSeconds(deadline: number | null, now: number): number {
  return deadline === null ? 0 : Math.max(0, Math.ceil((deadline - now) / 1000));
}

export function formatDuration(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('es', {
    day: 'numeric', month: 'short', year: 'numeric',
  }).format(date);
}

// Repetitions/sets are shown only within the same exercise. Weight never ranks different exercises.
export function progressRows(exercise: ExerciseProgress): ExerciseProgress['history'] {
  return [...exercise.history].sort((a, b) =>
    a.date.localeCompare(b.date) || a.session_id - b.session_id);
}

export function repetitionBars(exercise: ExerciseProgress) {
  const rows = progressRows(exercise);
  const max = Math.max(1, ...rows.map(row => row.total_reps ?? 0));
  return rows.map(row => ({
    ...row,
    percent: row.total_reps === null ? null : Math.max(0, row.total_reps) / max * 100,
  }));
}
