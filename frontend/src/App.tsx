import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, OPEN_FROM_BOT } from './api';
import { formatDate, isDirty, serializeDraft, toDraft, validateCompletion, type DraftExercise } from './helpers';
import { PlanView } from './PlanView';
import { ProgressView } from './ProgressView';
import { SessionView } from './SessionView';
import { Timer } from './Timer';
import type { Bootstrap, BotAction, Progress, WorkoutSession } from './types';

type View = 'plan' | 'train' | 'history' | 'progress' | 'detail';
const tabs = [
  { view: 'plan', label: 'Plan', icon: '▦' },
  { view: 'train', label: 'Entrenar', icon: '▶' },
  { view: 'history', label: 'Historial', icon: '◷' },
  { view: 'progress', label: 'Progreso', icon: '↗' },
] as const;
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Ha ocurrido un error. Inténtalo de nuevo.';

export function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [loading, setLoading] = useState(true);
  const [noPlan, setNoPlan] = useState(false);
  const [error, setError] = useState('');
  const [view, setView] = useState<View>('plan');
  const [week, setWeek] = useState<number | null>(null);
  const [sessions, setSessions] = useState<WorkoutSession[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [progress, setProgress] = useState<Progress | null>(null);
  const [progressLoading, setProgressLoading] = useState(false);
  const [progressError, setProgressError] = useState('');
  const [session, setSession] = useState<WorkoutSession | null>(null);
  const [draft, setDraft] = useState<DraftExercise[]>([]);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [timer, setTimer] = useState<{ seconds: number; key: number } | null>(null);
  const [botAction, setBotAction] = useState<BotAction | null>(null);
  const writeLock = useRef(false);
  const requestIds = useRef(new Map<string, string>());
  const heading = useRef<HTMLElement>(null);
  const errorRegion = useRef<HTMLDivElement>(null);
  const dirty = isDirty(session, draft);

  const fetchSessions = useCallback(async () => {
    setListLoading(true);
    setListError('');
    try {
      setSessions(await api.sessions());
    } catch (reason) {
      setListError(errorText(reason));
    } finally {
      setListLoading(false);
    }
  }, []);

  const fetchProgress = useCallback(async () => {
    setProgressLoading(true);
    setProgressError('');
    try {
      setProgress(await api.progress());
    } catch (reason) {
      setProgressError(errorText(reason));
    } finally {
      setProgressLoading(false);
    }
  }, []);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    setError('');
    setNoPlan(false);
    try {
      const result = await api.bootstrap();
      setData(result);
      setWeek(result.current_week !== null && result.current_week >= 1 && result.current_week <= 4
        ? result.current_week : null);
      void fetchSessions();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) setNoPlan(true);
      else setError(errorText(reason));
    } finally {
      setLoading(false);
    }
  }, [fetchSessions]);

  useEffect(() => {
    const telegram = window.Telegram?.WebApp;
    telegram?.ready();
    telegram?.expand();
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    const telegram = window.Telegram?.WebApp;
    if (dirty || busy) telegram?.enableClosingConfirmation();
    else telegram?.disableClosingConfirmation();
    function warn(event: BeforeUnloadEvent) {
      if (!dirty && !busy) return;
      event.preventDefault();
      event.returnValue = '';
    }
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, busy]);

  function acceptLeaving(): boolean {
    if (writeLock.current) return false;
    if (dirty && !window.confirm('Hay cambios sin guardar. ¿Descartarlos y salir de esta pantalla?')) return false;
    if (dirty && session) setDraft(toDraft(session.exercises));
    return true;
  }

  function navigate(next: View) {
    if (next === view || !acceptLeaving()) return;
    setView(next);
    setError('');
    setBotAction(null);
    if (next === 'history') void fetchSessions();
    if (next === 'progress') void fetchProgress();
  }

  // The Telegram back button follows the same unsaved-change guard as in-app navigation.
  useEffect(() => {
    const backButton = window.Telegram?.WebApp.BackButton;
    const back = () => navigate(view === 'detail' ? 'history' : 'plan');
    if (view === 'plan') backButton?.hide();
    else {
      backButton?.show();
      backButton?.onClick(back);
    }
    return () => backButton?.offClick(back);
  });

  useEffect(() => {
    heading.current?.focus();
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [view]);

  useEffect(() => {
    if (error) {
      errorRegion.current?.focus();
      errorRegion.current?.scrollIntoView({ block: 'center' });
    }
  }, [error]);

  function adoptSession(result: WorkoutSession) {
    setSession(result);
    setDraft(toDraft(result.exercises));
    setConflict(false);
    setSessions(existing => [result, ...existing.filter(item => item.id !== result.id)]);
  }

  async function start(day: number) {
    if (!data || week === null || writeLock.current || !acceptLeaving()) return;
    writeLock.current = true;
    setBusy(true);
    setError('');
    try {
      const key = `${data.plan_id}:${week}:${day}`;
      let requestId = requestIds.current.get(key);
      if (!requestId) {
        requestId = crypto.randomUUID();
        requestIds.current.set(key, requestId);
      }
      const result = await api.start(requestId, data.plan_id, week, day);
      adoptSession(result);
      setView('train');
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      writeLock.current = false;
      setBusy(false);
    }
  }

  async function openSession(id: number) {
    if (writeLock.current || !acceptLeaving()) return;
    writeLock.current = true;
    setBusy(true);
    setError('');
    try {
      adoptSession(await api.session(id));
      setView('detail');
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      writeLock.current = false;
      setBusy(false);
    }
  }

  async function save(next: DraftExercise[], complete = false) {
    if (!session || session.status === 'completed' || writeLock.current || conflict) return;
    setError('');
    let exercises;
    try {
      exercises = serializeDraft(next);
      if (complete) {
        validateCompletion(exercises, session.prescription);
        if (!window.confirm('¿Finalizar este entrenamiento? Después será de solo lectura.')) return;
      }
    } catch (reason) {
      setError(errorText(reason));
      return;
    }
    writeLock.current = true;
    setBusy(true);
    try {
      const result = await api.save(session, exercises, complete ? 'completed' : 'in_progress');
      adoptSession(result);
      if (complete) {
        setTimer(null);
        setProgress(null);
        heading.current?.focus();
        window.scrollTo({ top: 0, behavior: 'instant' });
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) setConflict(true);
      setError(errorText(reason));
    } finally {
      writeLock.current = false;
      setBusy(false);
    }
  }

  async function reloadSession() {
    if (!session || writeLock.current) return;
    if (dirty && !window.confirm('Recargar descartará tus cambios locales. ¿Cargar la sesión guardada en el servidor?')) return;
    writeLock.current = true;
    setBusy(true);
    setError('');
    try {
      adoptSession(await api.session(session.id));
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      writeLock.current = false;
      setBusy(false);
    }
  }

  function openBot(url: string) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== 'https:' || !['t.me', 'telegram.me'].includes(parsed.hostname)) {
        throw new Error('El enlace del bot no es válido. Vuelve al chat de FitCoach en Telegram.');
      }
      if (!window.Telegram?.WebApp) throw new Error(OPEN_FROM_BOT);
      window.Telegram.WebApp.openTelegramLink(url);
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function action(kind: 'swap' | 'review') {
    if (!data || writeLock.current) return;
    writeLock.current = true;
    setBusy(true);
    setError('');
    setBotAction(null);
    try {
      const result = await api.action(data.plan_id, kind);
      setBotAction(result);
      openBot(result.bot_url);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      writeLock.current = false;
      setBusy(false);
    }
  }

  const sortedSessions = [...sessions].sort((a, b) =>
    b.started_at.localeCompare(a.started_at) || b.id - a.id);
  const hasAuth = !!window.Telegram?.WebApp.initData;
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#main" aria-label="FitCoach, ir al contenido">FIT<span>COACH</span><small>Entrena con intención</small></a>
        <span className="header-tag">MINI APP</span>
      </header>
      <main id="main" ref={heading} tabIndex={-1}>
        {view !== 'plan' && data && <button type="button" className="back-link" disabled={busy}
          onClick={() => navigate(view === 'detail' ? 'history' : 'plan')}>← {view === 'detail' ? 'Historial' : 'Volver al plan'}</button>}
        {error && <div className="notice error" role="alert" ref={errorRegion} tabIndex={-1}>
          <strong>No se ha podido continuar</strong><p>{error}</p>
        </div>}
        {botAction && <section className="notice" role="status">
          <p>{botAction.message}</p>
          <button type="button" onClick={() => openBot(botAction.bot_url)}>Continuar en el bot</button>
        </section>}
        {loading && <p className="loading" role="status">Preparando tu entrenamiento…</p>}
        {!loading && !hasAuth && <section className="card">
          <h1>Abre FitCoach desde Telegram</h1><p>{OPEN_FROM_BOT}</p>
          <p className="muted">No se puede iniciar sesión desde un navegador externo.</p>
        </section>}
        {!loading && hasAuth && !data && <section className="card">
          <h1>{noPlan ? 'Primero, tu plan' : 'No pudimos cargar tu plan'}</h1>
          {noPlan && <p>Vuelve al bot y envía <code>/interview</code> y después <code>/train</code> para crear tu plan. Después abre de nuevo esta Mini App.</p>}
          <button type="button" onClick={() => void bootstrap()}>Volver a intentar</button>
        </section>}
        {!loading && data && hasAuth && <>
          {view === 'plan' && <>
            {listError && <div className="notice"><p>No se pudo comprobar el estado de los días: {listError}</p>
              <button type="button" className="secondary" disabled={listLoading} onClick={() => void fetchSessions()}>Reintentar estados</button>
            </div>}
            <PlanView data={data} week={week} setWeek={setWeek} sessions={sessions}
              busy={busy} start={day => void start(day)} action={kind => void action(kind)} />
          </>}
          {view === 'train' && !session && <section className="card">
            <span className="eyebrow">Un paso cada vez</span><h1>¿Qué día entrenas?</h1>
            <p>Elige una semana y un día en tu plan para empezar o retomar su registro.</p>
            <button type="button" onClick={() => navigate('plan')}>Elegir día del plan</button>
          </section>}
          {(view === 'train' || view === 'detail') && session && <SessionView session={session}
            draft={draft} readOnly={view === 'detail' || session.status === 'completed'}
            busy={busy} dirty={dirty} conflict={conflict} update={setDraft}
            save={(next, complete) => void save(next, complete)} reload={() => void reloadSession()}
            rest={seconds => setTimer({ seconds, key: Date.now() })} />}
          {view === 'detail' && session?.status === 'in_progress' && session.plan_id === data.plan_id &&
            <button type="button" onClick={() => navigate('train')}>Continuar esta sesión</button>}
          {view === 'history' && <>
            <section className="hero"><span className="eyebrow">Tu diario de entrenamiento</span>
              <h1>Historial reciente</h1>
              <p>Hasta 100 sesiones recientes. Cada registro conserva la prescripción de ese día, aunque cambie el plan.</p>
            </section>
            <button type="button" className="secondary" disabled={listLoading || busy}
              onClick={() => void fetchSessions()}>Actualizar historial</button>
            {listLoading && <p role="status">Cargando registros…</p>}
            {listError && <p className="notice error" role="alert">{listError}</p>}
            {!listLoading && !listError && sessions.length === 0 && <section className="card">
              <h2>Aún no hay entrenamientos</h2><p>Elige un día de tu plan para crear tu primer registro.</p>
            </section>}
            <ul className="history-list">
              {sortedSessions.map(item => <li key={item.id}>
                <button type="button" className="history-item" disabled={busy} onClick={() => void openSession(item.id)}>
                  <span><strong>{item.prescription.focus}</strong>
                    <span>Semana {item.week} · Día {item.day} · Plan #{item.plan_id}</span>
                    <span>{formatDate(item.completed_at ?? item.started_at)}</span>
                  </span>
                  <span className={`badge ${item.status === 'completed' ? 'success' : ''}`}>
                    {item.status === 'completed' ? 'Completado' : 'En curso'} →
                  </span>
                </button>
              </li>)}
            </ul>
          </>}
          {view === 'progress' && <>
            <button type="button" className="secondary" disabled={progressLoading}
              onClick={() => void fetchProgress()}>Actualizar progreso</button>
            {progressLoading && <p role="status">Cargando progreso…</p>}
            {progressError && <p className="notice error" role="alert">{progressError}</p>}
            {progress && <ProgressView progress={progress} />}
          </>}
        </>}
      </main>
      {timer && <Timer key={timer.key} seconds={timer.seconds} onClose={() => setTimer(null)} />}
      {data && hasAuth && <nav className="bottom-nav" aria-label="Navegación principal">
        {tabs.map(tab => <button type="button" key={tab.view} disabled={busy}
          aria-current={view === tab.view || (view === 'detail' && tab.view === 'history') ? 'page' : undefined}
          onClick={() => navigate(tab.view)}>
          <span aria-hidden="true">{tab.icon}</span>{tab.label}
        </button>)}
      </nav>}
    </div>
  );
}
