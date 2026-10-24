const MAX_HISTORY = 6;
const history = [];

const form = document.getElementById('chat-form');
const input = document.getElementById('question');
const sendBtn = document.getElementById('send-btn');
const messages = document.getElementById('messages');
const offlineBanner = document.getElementById('offline-banner');
const installBtn = document.getElementById('install-btn');

function addMessage(kind, text, sources) {
  messages.querySelector('.hint')?.remove();
  const el = document.createElement('div');
  el.className = `msg ${kind}`;
  el.textContent = text; // never innerHTML: the answer comes from an LLM
  if (sources && sources.length) {
    const list = document.createElement('ul');
    list.className = 'sources';
    for (const s of sources) {
      const li = document.createElement('li');
      li.textContent = s.heading ? `${s.source} — ${s.heading}` : s.source;
      list.appendChild(li);
    }
    el.appendChild(list);
  }
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

function errorText(status) {
  if (status === 429) return 'Demasiadas preguntas seguidas. Espera un momento.';
  if (status === 502) return 'El modelo no está disponible ahora mismo. Inténtalo de nuevo en un rato.';
  if (status === 422) return 'La pregunta no es válida (vacía o demasiado larga).';
  return 'Ha ocurrido un error. Inténtalo de nuevo.';
}

async function ask(question) {
  const pending = addMessage('assistant', 'Pensando...');
  try {
    const response = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history: history.slice(-MAX_HISTORY) }),
    });
    if (!response.ok) throw Object.assign(new Error('http'), { status: response.status });
    const data = await response.json();
    pending.remove();
    addMessage('assistant', data.answer, data.sources);
    history.push({ role: 'user', content: question }, { role: 'assistant', content: data.answer });
  } catch (err) {
    pending.remove();
    addMessage('error', errorText(err.status));
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question || !navigator.onLine) return;
  input.value = '';
  addMessage('user', question);
  sendBtn.disabled = true;
  await ask(question);
  sendBtn.disabled = false;
  input.focus();
});

function updateOnline() {
  offlineBanner.hidden = navigator.onLine;
  sendBtn.disabled = !navigator.onLine;
}
window.addEventListener('online', updateOnline);
window.addEventListener('offline', updateOnline);
updateOnline();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => console.error('SW', err));
  });
}

let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  deferredPrompt = event;
  installBtn.hidden = false;
});
installBtn.addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  installBtn.hidden = true;
});
window.addEventListener('appinstalled', () => { installBtn.hidden = true; });
