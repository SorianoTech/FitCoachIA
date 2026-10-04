import { formatDate } from './helpers';
import type { Bootstrap, WorkoutSession } from './types';

interface Props {
  data: Bootstrap;
  week: number | null;
  setWeek: (week: number) => void;
  sessions: WorkoutSession[];
  busy: boolean;
  start: (day: number) => void;
  action: (action: 'swap' | 'review') => void;
}

export function PlanView({ data, week, setWeek, sessions, busy, start, action }: Props) {
  const selected = data.plan.weeks.find(item => item.week === week);
  return (
    <>
      <section className="hero" aria-labelledby="plan-title">
        <span className="eyebrow">Tu plan · versión {data.version}</span>
        <h1 id="plan-title">{data.plan.goal}</h1>
        <p>{data.plan.days_per_week} días por semana · {data.plan.environment}</p>
        <div className="pill-row">
          <span className="pill">{data.current_week === null ? 'Semana por confirmar' : `Semana actual ${data.current_week}`}</span>
          <span className="pill">{data.cycle?.completed_at ? 'Ciclo revisado' : data.cycle ? 'Ciclo en curso' : 'Ciclo pendiente de inicio'}</span>
        </div>
        {data.cycle && <p className="muted">
          Inicio: {formatDate(data.cycle.started_at)} · Fin previsto: {formatDate(data.cycle.expected_end_at)}
        </p>}
        <p className="muted">Las fechas son orientativas: el calendario no completa ni revisa el ciclo automáticamente.</p>
        <details>
          <summary>Estado del calendario</summary>
          <p>{data.calendar_status}</p>
        </details>
      </section>
      <section aria-labelledby="weeks-title">
        <div className="section-heading">
          <h2 id="weeks-title">Tu semana</h2>
          <span className="muted">4 semanas</span>
        </div>
        <div className="week-grid" role="group" aria-label="Elegir semana del plan">
          {[1, 2, 3, 4].map(number => (
            <button type="button" key={number} className={week === number ? 'selected' : 'secondary'}
              aria-pressed={week === number} disabled={busy} onClick={() => setWeek(number)}>
              <span>Semana</span><strong>{number}</strong>
              {number === data.current_week && <small>Actual</small>}
            </button>
          ))}
        </div>
        {week === null && <div className="notice">No conocemos tu semana actual. Selecciona una semana para consultar y registrar sus días.</div>}
        {week !== null && !selected && <p className="notice">Esta semana no tiene días prescritos en el plan.</p>}
        {selected && <>
          <p className="muted">{selected.intensity}</p>
          <div className="day-grid">
            {selected.days.map(day => {
              const recorded = sessions.find(session =>
                session.plan_id === data.plan_id && session.week === week && session.day === day.day);
              return (
                <article className="card day-card" key={day.day}>
                  <div className="section-heading">
                    <span className="eyebrow">Día {day.day}</span>
                    <span className={`badge ${recorded?.status === 'completed' ? 'success' : ''}`}>
                      {recorded?.status === 'completed' ? 'Completado' : recorded ? 'En curso' : `${day.estimated_minutes} min`}
                    </span>
                  </div>
                  <h3>{day.focus}</h3>
                  <p className="muted">{day.exercises.length} ejercicios · {day.estimated_minutes} min aprox.</p>
                  <details>
                    <summary>Ver prescripción</summary>
                    <ol className="prescription-list">
                      {day.exercises.map((exercise, index) => <li key={`${exercise.exercise_id}-${index}`}>
                        <strong>{exercise.name}</strong>
                        <span>{exercise.sets} × {exercise.reps} · descanso {exercise.rest_seconds}s</span>
                        {exercise.rpe !== null && <span>RPE objetivo {exercise.rpe}</span>}
                        {exercise.notes && <p className="muted">{exercise.notes}</p>}
                      </li>)}
                    </ol>
                  </details>
                  <button type="button" disabled={busy} onClick={() => start(day.day)}>
                    {recorded?.status === 'completed' ? 'Ver entrenamiento' : recorded ? 'Continuar entrenamiento' : 'Empezar entrenamiento'}
                  </button>
                </article>
              );
            })}
          </div>
        </>}
      </section>
      <section className="card" aria-labelledby="guidance-title">
        <h2 id="guidance-title">Indicaciones del plan</h2>
        <p className="preserve-lines">{data.plan.progression_notes || 'Sin indicaciones adicionales.'}</p>
        {data.plan.excluded_by_injury.length > 0 && <>
          <h3>Exclusiones por lesión</h3>
          <ul>{data.plan.excluded_by_injury.map((item, index) => <li key={index}>{item}</li>)}</ul>
        </>}
      </section>
      <section className="card bot-card" aria-labelledby="bot-title">
        <span className="eyebrow">Decisiones con tu entrenador</span>
        <h2 id="bot-title">Continúa la conversación</h2>
        <p>Los cambios y la revisión se proponen y aprueban en el chat. Esta app no modifica tu plan.</p>
        <div className="button-row">
          <button type="button" className="secondary" disabled={busy} onClick={() => action('swap')}>
            Cambiar ejercicios · ir al chat
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => action('review')}>
            Revisar ciclo · ir al chat
          </button>
        </div>
      </section>
    </>
  );
}
