import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { toDraft } from './helpers';
import { PlanView } from './PlanView';
import { ProgressView } from './ProgressView';
import { SessionView } from './SessionView';
import type { Bootstrap, WorkoutSession } from './types';

const day = {
  day: 1, focus: 'Fuerza', estimated_minutes: 30,
  exercises: [{
    exercise_id: 'squat', name: 'Sentadilla', sets: 1, reps: '8–10', rest_seconds: 90,
    rpe: 7, notes: 'Mantén el control.',
  }],
};
const bootstrap: Bootstrap = {
  plan_id: 1, version: 2, current_week: null, cycle: null, calendar_status: 'unknown',
  plan: {
    goal: 'Ganar fuerza', days_per_week: 3, environment: 'Gimnasio',
    weeks: [{ week: 1, intensity: 'Moderada', days: [day] }],
    excluded_by_injury: ['Saltos'], progression_notes: 'Progresa gradualmente.',
  },
};
const noop = () => {};
const session: WorkoutSession = {
  id: 1, plan_id: 1, mesocycle_id: 1, week: 1, day: 1, revision: 2,
  status: 'completed', started_at: '2026-10-01', completed_at: '2026-10-01',
  prescription: day,
  exercises: [{
    position: 0, skipped: false,
    sets: [{ number: 1, reps: 8, duration_seconds: null, weight_kg: null, rpe: 7, completed: true }],
  }],
};

describe('view rendering', () => {
  it('requires explicit week selection when the calendar is unknown', () => {
    const html = renderToStaticMarkup(<PlanView data={bootstrap} week={null} setWeek={noop}
      sessions={[]} busy={false} start={noop} action={noop} />);
    expect(html).toContain('Selecciona una semana');
    expect(html.match(/aria-pressed="false"/g)).toHaveLength(4);
    expect(html).not.toContain('Empezar entrenamiento');
    expect(html).toContain('calendario no completa');
    expect(html).toContain('Cambiar ejercicios · ir al chat');
    expect(html).toContain('Revisar ciclo · ir al chat');
  });

  it('shows the selected prescription, injury exclusions and current saved status', () => {
    const html = renderToStaticMarkup(<PlanView data={bootstrap} week={1} setWeek={noop}
      sessions={[session]} busy={false} start={noop} action={noop} />);
    expect(html).toContain('Sentadilla');
    expect(html).toContain('8–10');
    expect(html).toContain('Saltos');
    expect(html).toContain('Ver entrenamiento');
    expect(html).toContain('Completado');
  });

  it('renders completed history with disabled inputs and no write controls', () => {
    const html = renderToStaticMarkup(<SessionView session={session} draft={toDraft(session.exercises)}
      readOnly busy={false} dirty={false} conflict={false} update={noop} save={noop}
      reload={noop} rest={noop} />);
    expect(html).toContain('solo lectura');
    expect(html).toContain('Plan: 1');
    expect(html).toContain('<fieldset');
    expect(html).toContain('disabled=""');
    expect(html).not.toContain('Finalizar entrenamiento');
    expect(html).not.toContain('Marcar hecha y guardar');
    expect(html).not.toContain('Omitir este ejercicio');
  });

  it('makes conflicts explicit and locks writes until an acknowledged reload', () => {
    const html = renderToStaticMarkup(<SessionView session={{ ...session, status: 'in_progress' }}
      draft={toDraft(session.exercises)} readOnly={false} busy={false} dirty conflict
      update={noop} save={noop} reload={noop} rest={noop} />);
    expect(html).toContain('Cambios sin guardar');
    expect(html).toContain('No se han aplicado tus cambios');
    expect(html).toContain('Recargar sesión guardada');
    expect(html).toContain('disabled=""');
  });

  it('provides an accessible table alongside graphs without inferring bodyweight load', () => {
    const html = renderToStaticMarkup(<ProgressView progress={{
      completed_sessions: 1, history_limit: 100, history_truncated: false,
      exercises: [{
        exercise_id: 'squat', name: 'Sentadilla',
        history: [{
          date: '2026-10-01', session_id: 1, total_reps: 8, total_duration_seconds: null, total_sets: 1,
          max_weight_kg: null, average_rpe: null,
        }],
      }],
    }} />);
    expect(html).toContain('<caption>');
    expect(html).toContain('scope="col"');
    expect(html).toContain('scope="row"');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('peso corporal');
    expect(html).toContain('Sin estimaciones de IA');
    expect(html).toContain('<td>—</td>');
  });

  it('renders timed work as duration with absent repetitions shown as a dash', () => {
    const html = renderToStaticMarkup(<ProgressView progress={{
      completed_sessions: 1, history_limit: 100, history_truncated: true,
      exercises: [{
        exercise_id: 'plank', name: 'Plancha',
        history: [{
          date: '2026-10-01', session_id: 1, total_reps: null,
          total_duration_seconds: 90, total_sets: 2, max_weight_kg: null, average_rpe: null,
        }],
      }],
    }} />);
    expect(html).toContain('Duración (s)');
    expect(html).toContain('<td>90</td>');
    expect(html).toContain('<strong>—</strong>');
    expect(html).not.toContain('class="bar-fill"');
    expect(html).toContain('hasta 100 sesiones');
    expect(html).toContain('registros anteriores fuera');
    expect(html).toContain('total histórico');
  });
});
