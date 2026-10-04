import { describe, expect, it } from 'vitest';
import {
  formatDate, formatDuration, isDirty, progressRows, remainingSeconds, repetitionBars,
  serializeDraft, toDraft, validateCompletion,
} from './helpers';
import type { ActualExercise, ExerciseProgress, TrainingDay, WorkoutSession } from './types';

const actual: ActualExercise[] = [{
  position: 0,
  skipped: false,
  sets: [{ number: 1, reps: 8, duration_seconds: null, weight_kg: 0, rpe: null, completed: true }],
}];
const prescription: TrainingDay = {
  day: 1, focus: 'Fuerza', estimated_minutes: 30,
  exercises: [{
    exercise_id: 'squat', name: 'Sentadilla', sets: 1, reps: '8–10',
    rest_seconds: 90, rpe: null, notes: null,
  }],
};
const session: WorkoutSession = {
  id: 1, plan_id: 3, mesocycle_id: null, week: 1, day: 1, revision: 2,
  status: 'in_progress', started_at: '2026-10-01', completed_at: null,
  prescription, exercises: actual,
};

describe('workout snapshots', () => {
  it('round trips nullable values, zero load and completed status without losing data', () => {
    expect(serializeDraft(toDraft(actual))).toEqual(actual);
    expect(isDirty(session, toDraft(actual))).toBe(false);
    expect(isDirty(null, [])).toBe(false);
  });

  it('keeps all exercises and sets, including skipped exercise data, in full snapshots', () => {
    const data = [...actual, { ...actual[0], position: 1, skipped: true }];
    expect(serializeDraft(toDraft(data))).toEqual(data);
  });

  it('accepts mobile decimal commas and detects edits', () => {
    const draft = toDraft(actual);
    draft[0].sets[0].weight_kg = '12,5';
    draft[0].sets[0].rpe = '7.5';
    expect(isDirty(session, draft)).toBe(true);
    expect(serializeDraft(draft)[0].sets[0]).toMatchObject({ weight_kg: 12.5, rpe: 7.5 });
  });

  it('allows incomplete sets to save a partial snapshot', () => {
    const draft = toDraft(actual);
    draft[0].sets[0].completed = false;
    draft[0].sets[0].reps = '';
    expect(serializeDraft(draft)[0].sets[0].reps).toBeNull();
  });

  it('requires repetitions or duration on completed sets', () => {
    const draft = toDraft(actual);
    draft[0].sets[0].reps = '';
    expect(() => serializeDraft(draft)).toThrow('repeticiones o duración');
    draft[0].sets[0].duration_seconds = '45';
    expect(serializeDraft(draft)[0].sets[0].duration_seconds).toBe(45);
  });

  it.each(['1e2', '-', 'abc', 'Infinity', '-1', '0', '2.5'])('rejects invalid repetition input %s without mutating the draft', value => {
    const draft = toDraft(actual);
    draft[0].sets[0].reps = value;
    expect(() => serializeDraft(draft)).toThrow();
    expect(draft[0].sets[0].reps).toBe(value);
  });

  it('rejects invalid effort and load values', () => {
    const draft = toDraft(actual);
    draft[0].sets[0].rpe = '11';
    expect(() => serializeDraft(draft)).toThrow('RPE');
    draft[0].sets[0].rpe = '';
    draft[0].sets[0].weight_kg = '-1';
    expect(() => serializeDraft(draft)).toThrow('peso');
  });

  it('requires every prescribed set to finalize, or an explicitly skipped exercise', () => {
    expect(() => validateCompletion(actual, prescription)).not.toThrow();
    const twoSets = { ...prescription, exercises: [{ ...prescription.exercises[0], sets: 2 }] };
    expect(() => validateCompletion(actual, twoSets)).toThrow('Completa las 2');
    expect(() => validateCompletion([], prescription)).toThrow('Faltan ejercicios');
    expect(() => validateCompletion([{ position: 0, skipped: true, sets: [] }], twoSets)).not.toThrow();
    const incomplete = [{ ...actual[0], sets: [{ ...actual[0].sets[0], completed: false }] }];
    expect(() => validateCompletion(incomplete, prescription)).toThrow('Completa');
  });
});

describe('deadline rest timer', () => {
  it('uses elapsed wall clock time rather than interval ticks after webview sleep', () => {
    const deadline = 1000 + 90_000;
    expect(remainingSeconds(deadline, 1000)).toBe(90);
    expect(remainingSeconds(deadline, 31_250)).toBe(60);
    expect(remainingSeconds(deadline, 121_000)).toBe(0);
  });

  it('rounds up and never displays a negative value after expiration or cancellation', () => {
    expect(remainingSeconds(1000, 999)).toBe(1);
    expect(remainingSeconds(1000, 1000)).toBe(0);
    expect(remainingSeconds(null, 1000)).toBe(0);
    expect(formatDuration(90)).toBe('1:30');
    expect(formatDuration(0)).toBe('0:00');
  });

  it('supports pause/resume by rebuilding a deadline from the remaining time', () => {
    const paused = remainingSeconds(100_000, 50_000);
    const resumedAt = 500_000;
    const resumedDeadline = resumedAt + paused * 1000;
    expect(remainingSeconds(resumedDeadline, resumedAt)).toBe(50);
    expect(remainingSeconds(resumedDeadline, resumedAt + 10_000)).toBe(40);
  });
});

describe('deterministic progress', () => {
  const exercise: ExerciseProgress = {
    exercise_id: 'squat', name: 'Sentadilla', history: [
      { date: '2026-10-03', session_id: 2, total_reps: 20, total_duration_seconds: null, total_sets: 2, max_weight_kg: 10, average_rpe: 8 },
      { date: '2026-10-01', session_id: 1, total_reps: 10, total_duration_seconds: null, total_sets: 1, max_weight_kg: null, average_rpe: null },
    ],
  };

  it('sorts histories without mutation and preserves nullable bodyweight measurements', () => {
    expect(progressRows(exercise).map(row => row.session_id)).toEqual([1, 2]);
    expect(exercise.history[0].session_id).toBe(2);
    expect(progressRows(exercise)[0].max_weight_kg).toBeNull();
  });

  it('scales repetitions only within the exercise and handles empty/zero histories', () => {
    expect(repetitionBars(exercise).map(row => row.percent)).toEqual([50, 100]);
    expect(repetitionBars({ ...exercise, history: [] })).toEqual([]);
    const zero = { ...exercise, history: [{ ...exercise.history[0], total_reps: 0 }] };
    expect(repetitionBars(zero)[0].percent).toBe(0);
  });

  it('handles absent or invalid dates explicitly', () => {
    expect(formatDate(null)).toBe('—');
    expect(formatDate('not-a-date')).toBe('—');
  });

  it('preserves duration-only progress without treating missing repetitions as zero', () => {
    const timed = {
      ...exercise,
      history: [{ ...exercise.history[0], total_reps: null, total_duration_seconds: 90 }],
    };
    expect(progressRows(timed)[0].total_duration_seconds).toBe(90);
    expect(repetitionBars(timed)[0].percent).toBeNull();
    expect(repetitionBars(timed)[0].total_reps).toBeNull();
  });
});
