import { formatDate, type DraftExercise, type DraftSet } from './helpers';
import type { WorkoutSession } from './types';

interface Props {
  session: WorkoutSession;
  draft: DraftExercise[];
  readOnly: boolean;
  busy: boolean;
  dirty: boolean;
  conflict: boolean;
  update: (draft: DraftExercise[]) => void;
  save: (draft: DraftExercise[], complete?: boolean) => void;
  reload: () => void;
  rest: (seconds: number) => void;
}

export function SessionView({
  session, draft, readOnly, busy, dirty, conflict, update, save, reload, rest,
}: Props) {
  function updateExercise(position: number, patch: Partial<DraftExercise>) {
    update(draft.map(item => item.position === position ? { ...item, ...patch } : item));
  }

  function setField(position: number, number: number, field: keyof DraftSet, value: string) {
    update(draft.map(item => item.position === position ? {
      ...item,
      sets: item.sets.map(set => set.number === number ? { ...set, [field]: value } : set),
    } : item));
  }

  function toggleComplete(position: number, number: number) {
    const next = draft.map(item => item.position === position ? {
      ...item,
      sets: item.sets.map(set => set.number === number ? { ...set, completed: !set.completed } : set),
    } : item);
    // Save the complete snapshot, including other edited sets, with the current revision.
    update(next);
    save(next);
  }

  return (
    <>
      <section className="hero">
        <span className="eyebrow">Semana {session.week} · Día {session.day}</span>
        <h1>{session.prescription.focus}</h1>
        <p>{session.status === 'completed' ? `Completado · ${formatDate(session.completed_at)}` : `Iniciado · ${formatDate(session.started_at)}`}</p>
        <p className="muted">Plan #{session.plan_id} · registro #{session.id} · versión {session.revision}</p>
        {readOnly
          ? <p className="notice">Registro de solo lectura. La prescripción es la guardada con esta sesión.</p>
          : <p>Registra lo que has hecho, no lo que esperabas hacer. Peso y RPE son opcionales.</p>}
      </section>
      {!readOnly && <>
        <div className={`save-state ${dirty ? 'unsaved' : ''}`} role="status" aria-live="polite">
          {busy ? 'Guardando… No cierres la app.' : dirty ? 'Cambios sin guardar · solo en esta pantalla' : 'Todos los cambios están guardados'}
        </div>
        <p className="muted">Marcar una serie hecha guarda toda la sesión. También puedes guardar un registro parcial. RPE: esfuerzo percibido de 1 a 10.</p>
        {conflict && <section className="notice conflict" aria-label="Conflicto de versión">
          <h2>Hay una versión más reciente</h2>
          <p>No se han aplicado tus cambios. Puedes revisarlos aquí antes de recargar.
            Recargar sustituye los datos locales por los del servidor.</p>
          <button type="button" className="secondary" disabled={busy} onClick={reload}>Recargar sesión guardada</button>
        </section>}
      </>}
      {session.prescription.exercises.map((prescribed, position) => {
        const actual = draft.find(item => item.position === position);
        return (
          <section className="card exercise-card" key={position} aria-labelledby={`exercise-${position}`}>
            <span className="eyebrow">Ejercicio {position + 1}</span>
            <h2 id={`exercise-${position}`}>{prescribed.name}</h2>
            <p className="planned">Plan: {prescribed.sets} × {prescribed.reps} · {prescribed.rest_seconds}s descanso
              {prescribed.rpe !== null ? ` · RPE ${prescribed.rpe}` : ''}</p>
            {prescribed.notes && <p className="muted preserve-lines">{prescribed.notes}</p>}
            {!actual && <p className="notice">No hay registro de este ejercicio.</p>}
            {actual && <>
              {!readOnly ? <label className="check-label">
                <input type="checkbox" checked={actual.skipped} disabled={busy || conflict}
                  onChange={event => updateExercise(position, { skipped: event.target.checked })} />
                Omitir este ejercicio
              </label> : actual.skipped && <p className="badge">Ejercicio omitido</p>}
              {actual.skipped && !readOnly && <p className="muted">No se exige completar sus series. Los valores anteriores se conservan.</p>}
              {actual.sets.map(set => (
                <fieldset className={`set-row ${set.completed ? 'done' : ''}`} key={set.number}
                  disabled={readOnly || busy || conflict || actual.skipped}>
                  <legend>Serie {set.number} {set.completed ? '· hecha' : '· pendiente'}</legend>
                  <div className="set-inputs">
                    <label>Repeticiones
                      <input type="text" inputMode="numeric" pattern="[0-9]*" value={set.reps}
                        placeholder="—" autoComplete="off"
                        onChange={event => setField(position, set.number, 'reps', event.target.value)} />
                    </label>
                    <label>Duración (s)
                      <input type="text" inputMode="numeric" pattern="[0-9]*" value={set.duration_seconds}
                        placeholder="—" autoComplete="off"
                        onChange={event => setField(position, set.number, 'duration_seconds', event.target.value)} />
                    </label>
                    <label>Peso (kg)
                      <input type="text" inputMode="decimal" value={set.weight_kg}
                        placeholder="Opcional" autoComplete="off"
                        onChange={event => setField(position, set.number, 'weight_kg', event.target.value)} />
                    </label>
                    <label>RPE (1–10)
                      <input type="text" inputMode="decimal" value={set.rpe}
                        placeholder="Opcional" autoComplete="off"
                        onChange={event => setField(position, set.number, 'rpe', event.target.value)} />
                    </label>
                  </div>
                  {!readOnly && <button type="button" className={set.completed ? 'secondary' : ''}
                    aria-pressed={set.completed} onClick={() => toggleComplete(position, set.number)}>
                    {set.completed ? 'Desmarcar serie' : 'Marcar hecha y guardar'}
                  </button>}
                </fieldset>
              ))}
              {!readOnly && prescribed.rest_seconds > 0 && <button type="button"
                className="secondary rest-button" onClick={() => rest(prescribed.rest_seconds)}>
                Descansar {prescribed.rest_seconds}s
              </button>}
            </>}
          </section>
        );
      })}
      {!readOnly && <section className="card save-panel">
        <h2>Guarda tu entrenamiento</h2>
        <p>Para finalizar, completa todas las series prescritas o marca el ejercicio como omitido.
          Los entrenamientos finalizados no se pueden editar.</p>
        <div className="button-row">
          <button type="button" className="secondary" disabled={busy || conflict || !dirty}
            onClick={() => save(draft)}>Guardar cambios</button>
          <button type="button" disabled={busy || conflict} onClick={() => save(draft, true)}>
            Finalizar entrenamiento
          </button>
        </div>
      </section>}
    </>
  );
}
