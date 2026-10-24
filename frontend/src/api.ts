import type { Bootstrap, BotAction, Progress, WorkoutSession, ActualExercise } from './types';

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export const OPEN_FROM_BOT = 'Abre esta Mini App desde el bot de FitCoach en Telegram.';

export function apiErrorMessage(status: number, body: unknown): string {
  if (status === 401 || status === 403) {
    return 'La autorización de Telegram ha caducado o no es válida. Cierra y abre la Mini App desde el bot.';
  }
  if (status === 409) {
    return 'La sesión ha cambiado en otro dispositivo. Tus cambios siguen aquí. Recarga la sesión para obtener la versión actual.';
  }
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    const detail = record.detail ?? record.message;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail)) return 'Revisa los datos introducidos antes de guardar.';
  }
  return `No se ha podido completar la solicitud (${status}). Inténtalo de nuevo.`;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const initData = window.Telegram?.WebApp.initData;
  if (!initData) throw new ApiError(401, OPEN_FROM_BOT);
  let response: Response;
  try {
    response = await fetch(`/api/miniapp${path}`, {
      ...options,
      credentials: 'same-origin',
      headers: {
        ...options.headers,
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        'X-Telegram-Init-Data': initData,
      },
    });
  } catch {
    throw new ApiError(0, 'No hay conexión con el servidor. Tus cambios no se han perdido. Reintenta cuando tengas conexión.');
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, apiErrorMessage(response.status, body));
  return body as T;
}

export const api = {
  bootstrap: () => request<Bootstrap>('/bootstrap'),
  sessions: () => request<WorkoutSession[]>('/sessions'),
  session: (id: number) => request<WorkoutSession>(`/sessions/${id}`),
  start: (requestId: string, planId: number, week: number, day: number) =>
    request<WorkoutSession>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId, plan_id: planId, week, day }),
    }),
  save: (
    session: WorkoutSession,
    exercises: ActualExercise[],
    status: WorkoutSession['status'],
  ) =>
    request<WorkoutSession>(`/sessions/${session.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ revision: session.revision, status, exercises }),
    }),
  progress: () => request<Progress>('/progress'),
  action: (planId: number, action: 'swap' | 'review') =>
    request<BotAction>('/actions', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId, action }),
    }),
};
