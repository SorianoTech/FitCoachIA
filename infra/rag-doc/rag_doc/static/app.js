const MAX_HISTORY = 6;
const history = [];

const form = document.getElementById('chat-form');
const input = document.getElementById('question');
const sendBtn = document.getElementById('send-btn');
const messages = document.getElementById('messages');
const offlineBanner = document.getElementById('offline-banner');
const installBtn = document.getElementById('install-btn');
const micBtn = document.getElementById('mic-btn');

// Turns each [n] with a matching source into a button that highlights its chip (DOM nodes only).
function renderCitations(body, text, chips) {
  for (const part of text.split(/(\[\d+\])/)) {
    const chip = chips.get(Number(part.slice(1, -1)));
    if (!/^\[\d+\]$/.test(part) || !chip) {
      body.appendChild(document.createTextNode(part));
      continue;
    }
    const cite = document.createElement('button');
    cite.type = 'button';
    cite.className = 'cite';
    cite.textContent = part;
    cite.addEventListener('click', () => {
      chip.classList.add('chip--active');
      chip.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      setTimeout(() => chip.classList.remove('chip--active'), 2500);
    });
    body.appendChild(cite);
  }
}

function addMessage(kind, text, sources) {
  document.getElementById('welcome')?.remove();
  const row = document.createElement('div');
  row.className = `row ${kind}`;
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = kind === 'user' ? '🙂' : kind === 'error' ? '⚠️' : '🤖';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  const body = document.createElement('div');
  body.className = 'text';
  bubble.appendChild(body);
  if (sources && sources.length) {
    const list = document.createElement('div');
    list.className = 'sources';
    const chips = new Map();
    for (const s of sources) {
      const chip = document.createElement('span');
      chip.className = 'chip';
      const num = document.createElement('b');
      num.className = 'chip-num';
      num.textContent = `[${s.number}]`;
      chip.append(num, ` ${s.source.split('/').pop()}${s.heading ? ` › ${s.heading}` : ''}`);
      chip.title = s.heading ? `${s.source} — ${s.heading}` : s.source;
      chips.set(s.number, chip);
      list.appendChild(chip);
    }
    renderCitations(body, text, chips);
    bubble.appendChild(list);
  } else {
    body.textContent = text; // never innerHTML: the answer comes from an LLM
  }
  row.append(avatar, bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  return { row, bubble };
}

function addThinking() {
  const { row, bubble } = addMessage('assistant', '');
  bubble.querySelector('.text').innerHTML = '<span class="dots"><i></i><i></i><i></i></span>'; // static markup
  return row;
}

// Only one answer is read aloud at a time; clicking the active button stops it
let activeSpeech = null;

function stopSpeech() {
  if (!activeSpeech) return;
  const { audio, url, button, controller } = activeSpeech;
  activeSpeech = null;
  controller.abort();
  audio?.pause();
  if (url) URL.revokeObjectURL(url);
  setSpeakState(button, 'idle');
}

function setSpeakState(button, state) {
  button.dataset.state = state;
  button.disabled = false;
  button.textContent = { idle: '🔊 Escuchar', loading: '⏳ Preparando…', playing: '⏹ Parar' }[state];
}

async function speak(text, button) {
  const wasActive = activeSpeech?.button === button;
  stopSpeech();
  if (wasActive) return;
  const session = { button, audio: null, url: null, controller: new AbortController() };
  activeSpeech = session;
  setSpeakState(button, 'loading');
  try {
    const response = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal: session.controller.signal,
    });
    if (!response.ok) throw Object.assign(new Error('http'), { status: response.status });
    session.url = URL.createObjectURL(await response.blob());
    if (activeSpeech !== session) {
      URL.revokeObjectURL(session.url);
      return;
    }
    session.audio = new Audio(session.url);
    session.audio.addEventListener('ended', () => activeSpeech === session && stopSpeech());
    setSpeakState(button, 'playing');
    await session.audio.play();
  } catch (err) {
    if (err.name === 'AbortError') return;
    if (activeSpeech === session) stopSpeech();
    addMessage('error', errorText(err.status));
  }
}

function addAnswer(text, sources) {
  const { bubble } = addMessage('assistant', text, sources);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'speak-btn';
  setSpeakState(button, 'idle');
  button.addEventListener('click', () => speak(text, button));
  bubble.appendChild(button);
}

function errorText(status) {
  if (status === 413) return 'El audio es demasiado largo (máximo 30 segundos).';
  if (status === 415 || status === 422) return 'No se ha podido entender la entrada. Inténtalo de nuevo.';
  if (status === 429) return 'Demasiadas consultas seguidas o límite diario alcanzado. Espera un momento.';
  if (status === 502) return 'El modelo no está disponible ahora mismo. Inténtalo de nuevo en un rato.';
  if (status === 422) return 'La pregunta no es válida (vacía o demasiado larga).';
  return 'Ha ocurrido un error. Inténtalo de nuevo.';
}

async function ask(question) {
  const pending = addThinking();
  try {
    const response = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history: history.slice(-MAX_HISTORY) }),
    });
    if (!response.ok) throw Object.assign(new Error('http'), { status: response.status });
    const data = await response.json();
    pending.remove();
    addAnswer(data.answer, data.sources);
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
  await submitQuestion(question);
});

for (const chip of document.querySelectorAll('.suggestion')) {
  chip.addEventListener('click', () => navigator.onLine && submitQuestion(chip.textContent));
}

async function submitQuestion(question) {
  input.value = '';
  addMessage('user', question);
  sendBtn.disabled = true;
  await ask(question);
  sendBtn.disabled = !navigator.onLine;
  input.focus();
}

// ─── Voice input: record with MediaRecorder, transcribe on the server, then ask ───
const MAX_RECORD_MS = 30000;
let recorder = null;
let recordTimer = null;

async function toggleRecording() {
  if (recorder) {
    recorder.stop();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    addMessage('error', 'No se ha podido acceder al micrófono.');
    return;
  }
  const chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.addEventListener('dataavailable', (e) => chunks.push(e.data));
  recorder.addEventListener('stop', async () => {
    clearTimeout(recordTimer);
    stream.getTracks().forEach((t) => t.stop());
    const type = recorder.mimeType || 'audio/webm';
    recorder = null;
    micBtn.classList.remove('recording');
    await transcribeAndAsk(new Blob(chunks, { type }));
  });
  recorder.start();
  micBtn.classList.add('recording');
  recordTimer = setTimeout(() => recorder?.stop(), MAX_RECORD_MS);
}

async function transcribeAndAsk(blob) {
  const type = blob.type.split(';')[0];
  micBtn.disabled = true;
  try {
    const response = await fetch('/api/stt', { method: 'POST', headers: { 'Content-Type': type }, body: blob });
    if (!response.ok) throw Object.assign(new Error('http'), { status: response.status });
    const { text } = await response.json();
    await submitQuestion(text);
  } catch (err) {
    addMessage('error', errorText(err.status));
  } finally {
    micBtn.disabled = false;
  }
}

if (navigator.mediaDevices?.getUserMedia && window.MediaRecorder) {
  micBtn.hidden = false;
  micBtn.addEventListener('click', toggleRecording);
}

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
