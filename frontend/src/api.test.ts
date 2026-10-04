import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, apiErrorMessage, OPEN_FROM_BOT, request } from './api';

afterEach(() => vi.unstubAllGlobals());

function auth() {
  vi.stubGlobal('window', { Telegram: { WebApp: { initData: 'signed-telegram-data' } } });
}

describe('authenticated same-origin API', () => {
  it('rejects missing Telegram init data before making any request', async () => {
    vi.stubGlobal('window', {});
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    await expect(api.bootstrap()).rejects.toThrow(OPEN_FROM_BOT);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('sends init data on every request and never trusts a supplied auth header', async () => {
    auth();
    const fetch = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    await request('/bootstrap', { headers: { 'X-Telegram-Init-Data': 'wrong' } });
    expect(fetch).toHaveBeenCalledWith('/api/miniapp/bootstrap', expect.objectContaining({
      credentials: 'same-origin',
      headers: expect.objectContaining({ 'X-Telegram-Init-Data': 'signed-telegram-data' }),
    }));
  });

  it('keeps the start request UUID unchanged on retries', async () => {
    auth();
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValueOnce(new Response('{"id":1}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    const requestId = 'a4a6b32b-833f-4222-b9ed-c50374366f32';
    await expect(api.start(requestId, 2, 1, 3)).rejects.toMatchObject({ status: 0 });
    await api.start(requestId, 2, 1, 3);
    expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      request_id: requestId, plan_id: 2, week: 1, day: 3,
    });
  });

  it('PATCH sends the revision and full snapshot instead of a delta', async () => {
    auth();
    const fetch = vi.fn().mockResolvedValue(new Response('{"revision":2}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    const exercises = [
      { position: 0, skipped: false, sets: [{ number: 1, reps: 8, duration_seconds: null, weight_kg: null, rpe: null, completed: true }] },
      { position: 1, skipped: true, sets: [] },
    ];
    // Only the fields used by the transport are needed for this fixture.
    const session = { id: 5, revision: 1 } as Parameters<typeof api.save>[0];
    await api.save(session, exercises, 'in_progress');
    expect(fetch).toHaveBeenCalledWith('/api/miniapp/sessions/5', expect.objectContaining({ method: 'PATCH' }));
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      revision: 1, status: 'in_progress', exercises,
    });
  });

  it('surfaces optimistic conflicts distinctly and does not automatically retry PATCH', async () => {
    auth();
    const fetch = vi.fn().mockResolvedValue(new Response('{"detail":"conflict"}', { status: 409 }));
    vi.stubGlobal('fetch', fetch);
    await expect(request('/sessions/1', { method: 'PATCH', body: '{}' }))
      .rejects.toMatchObject({ status: 409, message: expect.stringContaining('Tus cambios siguen aquí') });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('preserves the 404 status for the no-plan screen and tolerates non-JSON errors', async () => {
    auth();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Not found', { status: 404 })));
    await expect(api.bootstrap()).rejects.toBeInstanceOf(ApiError);
    await expect(api.bootstrap()).rejects.toMatchObject({ status: 404 });
  });

  it('requires reopening the app on expired authorization', () => {
    expect(apiErrorMessage(401, { detail: 'private validation error' })).toContain('abre la Mini App desde el bot');
    expect(apiErrorMessage(403, null)).toContain('Telegram');
    expect(apiErrorMessage(422, { detail: [{ msg: 'invalid' }] })).toContain('Revisa los datos');
    expect(apiErrorMessage(400, { detail: 'El día no existe.' })).toBe('El día no existe.');
    expect(apiErrorMessage(500, null)).toContain('500');
  });

  it('passes plan-scoped handoffs to the bot, not autonomous plan edits', async () => {
    auth();
    const fetch = vi.fn().mockResolvedValue(new Response('{"message":"Continúa en el chat","bot_url":"https://t.me/fitcoach_bot"}'));
    vi.stubGlobal('fetch', fetch);
    await api.action(7, 'review');
    expect(fetch).toHaveBeenCalledWith('/api/miniapp/actions', expect.objectContaining({
      method: 'POST', body: '{"plan_id":7,"action":"review"}',
    }));
  });
});
