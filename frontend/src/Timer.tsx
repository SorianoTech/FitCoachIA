import { useEffect, useState } from 'react';
import { formatDuration, remainingSeconds } from './helpers';

export function Timer({ seconds, onClose }: { seconds: number; onClose: () => void }) {
  const [deadline, setDeadline] = useState<number | null>(() => Date.now() + seconds * 1000);
  const [paused, setPaused] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now);
  const remaining = paused ?? remainingSeconds(deadline, now);

  useEffect(() => {
    const refresh = () => setNow(Date.now());
    const interval = window.setInterval(refresh, 500);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('pageshow', refresh);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', refresh);
      window.removeEventListener('pageshow', refresh);
    };
  }, []);

  function togglePause() {
    const current = Date.now();
    setNow(current);
    if (paused !== null) {
      setDeadline(current + paused * 1000);
      setPaused(null);
    } else {
      setPaused(remainingSeconds(deadline, current));
      setDeadline(null);
    }
  }

  return (
    <aside className="timer" aria-label="Temporizador de descanso">
      <div>
        <span className="eyebrow">Descanso {paused !== null ? '· pausado' : ''}</span>
        <div className="timer-value" role="timer" aria-label={`${remaining} segundos restantes`}>
          {formatDuration(remaining)}
        </div>
      </div>
      <div className="button-row">
        {remaining > 0 && <button type="button" className="secondary" onClick={togglePause}>
          {paused !== null ? 'Reanudar' : 'Pausar'}
        </button>}
        <button type="button" className="secondary" onClick={onClose}>
          {remaining === 0 ? 'Cerrar' : 'Cancelar'}
        </button>
      </div>
      {remaining === 0 && <p role="status">Descanso terminado.</p>}
      <p className="muted timer-note">Sin avisos en segundo plano. El tiempo se actualiza al volver a la app.</p>
    </aside>
  );
}
