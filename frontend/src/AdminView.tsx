import { useEffect, useState } from 'react';
import { request } from './api';

export interface QuotaConfig {
  token_limit: number;
  soft_ratio: number;
  window_minutes: number;
}
interface Settings {
  global: QuotaConfig | null;
  defaults: QuotaConfig;
  effective: QuotaConfig;
}
interface UserQuota {
  chat_id: number;
  used_tokens: number;
  hard_tokens: number;
  soft_tokens: number;
  window_minutes: number;
  source: 'user' | 'global' | 'environment';
  override: QuotaConfig | null;
}
interface Page {
  users: UserQuota[];
  offset: number;
  limit: number;
  has_more: boolean;
}
const sources = { user: 'Excepción individual', global: 'Global del panel', environment: 'Entorno' };
const message = (error: unknown) => error instanceof Error ? error.message : 'No se pudo completar la operación.';

export function QuotaForm({ value, busy, onSave }: {
  value: QuotaConfig; busy: boolean; onSave: (config: QuotaConfig) => void;
}) {
  const [limit, setLimit] = useState(String(value.token_limit));
  const [ratio, setRatio] = useState(String(value.soft_ratio));
  const [windowMinutes, setWindowMinutes] = useState(String(value.window_minutes));
  return <form onSubmit={event => {
    event.preventDefault();
    onSave({ token_limit: Number(limit), soft_ratio: Number(ratio), window_minutes: Number(windowMinutes) });
  }}>
    <fieldset disabled={busy}>
      <label>Límite de tokens<input required type="number" min="1" max="1000000000" step="1"
        value={limit} onChange={event => setLimit(event.target.value)} /></label>
      <label>Ratio del umbral blando<input required type="number" min="0.000001" max="1" step="any"
        value={ratio} onChange={event => setRatio(event.target.value)} /></label>
      <label>Ventana móvil (minutos)<input required type="number" min="1" max="525600" step="1"
        value={windowMinutes} onChange={event => setWindowMinutes(event.target.value)} /></label>
      <p className="muted">Umbral blando: {Math.floor(Number(limit) * Number(ratio)).toLocaleString()} tokens.
        La ventana no se reinicia a medianoche. Una llamada autorizada puede superar el límite.</p>
      <button type="submit">Guardar límites</button>
    </fieldset>
  </form>;
}

export function AdminView() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<UserQuota | null>(null);
  const [chat, setChat] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [formRevision, setFormRevision] = useState(0);

  async function load(nextOffset: number) {
    setBusy(true); setError('');
    try {
      const [nextSettings, nextPage] = await Promise.all([
        request<Settings>('/admin/settings'),
        request<Page>(`/admin/users?offset=${nextOffset}&limit=25`),
      ]);
      setSettings(nextSettings); setPage(nextPage); setOffset(nextOffset);
      setFormRevision(current => current + 1);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(0); }, []);

  async function mutate(path: string, config?: QuotaConfig) {
    setBusy(true); setError(''); setNotice('');
    try {
      await request<unknown>(path, config
        ? { method: 'PUT', body: JSON.stringify(config) } : { method: 'DELETE' });
      // Saving settings never deletes usage, nor grants administrator permissions.
      setNotice('Configuración guardada. Se aplica a la siguiente comprobación de cuota.');
      if (selected) setSelected(await request<UserQuota>(`/admin/users/${selected.chat_id}`));
      await load(offset);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  async function inspect() {
    setBusy(true); setError('');
    try {
      if (!/^[1-9]\d*$/.test(chat) || !Number.isSafeInteger(Number(chat))) {
        throw new Error('Introduce un chat_id positivo válido.');
      }
      setSelected(await request<UserQuota>(`/admin/users/${chat}`));
      setFormRevision(current => current + 1);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  return <>
    <section className="hero"><span className="eyebrow">Administración</span>
      <h1>Cuotas del LLM</h1>
      <p>Excepción individual → global del panel → entorno. Consultar y registrar entrenamientos no consume cuota LLM.</p>
    </section>
    {error && <p className="notice error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    <button disabled={busy} className="secondary" onClick={() => void load(offset)}>Actualizar consumo</button>
    {busy && <p role="status">Procesando…</p>}
    {settings && <section className="card">
      <h2>Límites globales</h2>
      <p>Origen: {settings.global ? 'Base de datos' : 'Variables de entorno'}.
        Valores de respaldo: {settings.defaults.token_limit.toLocaleString()} tokens,
        ratio {settings.defaults.soft_ratio}, ventana {settings.defaults.window_minutes} minutos.</p>
      <QuotaForm key={`global-${formRevision}`} value={settings.effective} busy={busy}
        onSave={config => void mutate('/admin/settings', config)} />
      {settings.global && <button className="secondary" disabled={busy} onClick={() => {
        if (window.confirm('¿Restaurar los valores globales del entorno? Las excepciones individuales no cambian.')) {
          void mutate('/admin/settings');
        }
      }}>Restaurar entorno</button>}
    </section>}
    <section className="card"><h2>Buscar por chat_id</h2>
      <form onSubmit={event => { event.preventDefault(); void inspect(); }}>
        <label>chat_id de Telegram<input required inputMode="numeric" pattern="[1-9][0-9]*"
          value={chat} onChange={event => setChat(event.target.value)} disabled={busy} /></label>
        <button disabled={busy}>Consultar usuario</button>
      </form>
    </section>
    {selected && settings && <section className="card">
      <h2>Usuario {selected.chat_id}</h2>
      <p>{sources[selected.source]} · {selected.used_tokens.toLocaleString()} tokens usados
        en {selected.window_minutes} minutos.</p>
      <p>Límite: {selected.hard_tokens.toLocaleString()} · Blando: {selected.soft_tokens.toLocaleString()} ·
        Disponible orientativo: {Math.max(0, selected.hard_tokens - selected.used_tokens).toLocaleString()}</p>
      <QuotaForm key={`user-${selected.chat_id}-${formRevision}`}
        value={selected.override ?? settings.effective} busy={busy}
        onSave={config => void mutate(`/admin/users/${selected.chat_id}`, config)} />
      {selected.override && <button disabled={busy} className="secondary" onClick={() => {
        if (window.confirm('¿Eliminar la excepción y heredar los límites globales?')) {
          void mutate(`/admin/users/${selected.chat_id}`);
        }
      }}>Eliminar excepción</button>}
    </section>}
    {page && <section className="card"><h2>Usuarios y consumo</h2>
      <p className="muted">Cada consumo usa la ventana efectiva de ese usuario. No se borran consumos al cambiar límites.</p>
      <ul className="history-list">{page.users.map(user => <li key={user.chat_id}>
        <button type="button" disabled={busy} className="history-item" onClick={() => {
          setSelected(user); setFormRevision(current => current + 1);
        }}>
          <span><strong>{user.chat_id}</strong><span>{sources[user.source]}</span>
            <span>{user.used_tokens.toLocaleString()} / {user.hard_tokens.toLocaleString()} tokens · {user.window_minutes} min</span></span>
        </button>
      </li>)}</ul>
      {page.users.length === 0 && <p>No hay usuarios registrados.</p>}
      <div className="button-row">
        <button disabled={busy || offset === 0} onClick={() => void load(Math.max(0, offset - 25))}>Anterior</button>
        <button disabled={busy || !page.has_more} onClick={() => void load(offset + 25)}>Siguiente</button>
      </div>
    </section>}
  </>;
}
