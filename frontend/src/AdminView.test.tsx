import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { AdminView, QuotaForm } from './AdminView';

describe('administration', () => {
  it('renders policy inputs and computed soft threshold', () => {
    const html = renderToStaticMarkup(<QuotaForm
      value={{ token_limit: 150000, soft_ratio: .66, window_minutes: 1440 }}
      busy={false} onSave={() => {}} />);
    expect(html).toContain('Límite de tokens');
    expect(html).toContain('Ventana móvil (minutos)');
    expect(html).toContain((99000).toLocaleString());
    expect(html).toContain('Una llamada autorizada puede superar');
    expect(html).not.toContain('disabled=""');
  });
  it('disables changes while saving', () => {
    const html = renderToStaticMarkup(<QuotaForm
      value={{ token_limit: 100, soft_ratio: .5, window_minutes: 60 }}
      busy onSave={() => {}} />);
    expect(html).toContain('disabled=""');
  });
  it('describes precedence and includes explicit user lookup', () => {
    const html = renderToStaticMarkup(<AdminView />);
    expect(html).toContain('Excepción individual');
    expect(html).toContain('global del panel');
    expect(html).toContain('Buscar por chat_id');
    expect(html).not.toContain('Reiniciar consumo');
  });
});
