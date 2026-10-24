import { formatDate, progressRows, repetitionBars } from './helpers';
import type { Progress } from './types';

export function ProgressView({ progress }: { progress: Progress }) {
  return (
    <>
      <section className="hero">
        <span className="eyebrow">Tu constancia, en datos</span>
        <h1>Progreso</h1>
        <p className="stat">{progress.completed_sessions}<span> sesiones completadas · total histórico</span></p>
        <p>Detalle reciente guardado (hasta {progress.history_limit} sesiones). Sin estimaciones de IA.</p>
        {progress.history_truncated && <p className="notice">
          Hay registros anteriores fuera de este detalle reciente. El total de sesiones completadas sí incluye todo el historial.
        </p>}
      </section>
      <p className="notice">
        Compara cada ejercicio consigo mismo. Repeticiones, técnica y carga pueden variar:
        estas gráficas no comparan fuerza entre ejercicios ni estiman carga para peso corporal.
      </p>
      {progress.exercises.length === 0 && <section className="card">
        <h2>Tu progreso empieza aquí</h2>
        <p>Completa un entrenamiento para ver tus primeros registros.</p>
      </section>}
      {progress.exercises.map(exercise => (
        <section className="card" key={exercise.exercise_id}>
          <h2>{exercise.name}</h2>
          <h3>Repeticiones por sesión</h3>
          <div className="bars" aria-hidden="true">
            {repetitionBars(exercise).map(row => (
              <div className="bar-row" key={row.session_id}>
                <span>{formatDate(row.date)}</span>
                <div className="bar-track">
                  {row.percent !== null && <div className="bar-fill" style={{ width: `${row.percent}%` }} />}
                </div>
                <strong>{row.total_reps ?? '—'}</strong>
              </div>
            ))}
          </div>
          <div className="table-scroll" role="region" aria-label={`Datos de ${exercise.name}`} tabIndex={0}>
            <table>
              <caption>Registros recientes de {exercise.name}. «—» indica dato no registrado.</caption>
              <thead><tr>
                <th scope="col">Fecha</th><th scope="col">Series</th><th scope="col">Reps</th>
                <th scope="col">Duración (s)</th><th scope="col">Máx. kg</th><th scope="col">RPE medio</th>
              </tr></thead>
              <tbody>{progressRows(exercise).map(row => <tr key={row.session_id}>
                <th scope="row">{formatDate(row.date)}</th>
                <td>{row.total_sets}</td><td>{row.total_reps ?? '—'}</td>
                <td>{row.total_duration_seconds ?? '—'}</td>
                <td>{row.max_weight_kg ?? '—'}</td>
                <td>{row.average_rpe === null ? '—' : row.average_rpe.toFixed(1)}</td>
              </tr>)}</tbody>
            </table>
          </div>
          {exercise.history.length === 0 && <p className="muted">Aún no hay registros para este ejercicio.</p>}
        </section>
      ))}
    </>
  );
}
