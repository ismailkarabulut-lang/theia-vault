const MEDIA_MAP = {
  search:   { file: 'searching.mp4',  keywords: ['ara','bul','araştır','google'] },
  weather:  { file: 'weather.mp4',    keywords: ['hava','sıcaklık','yağmur','tahmin'] },
  reminder: { file: 'reminder.mp4',   keywords: ['hatırlat','alarm','bildir'] },
  routine:  { file: 'routine.mp4',    keywords: ['rutin','her gün','her sabah','her akşam'] },
  task:     { file: 'task.mp4',       keywords: ['görev','yapılacak','task'] },
  open:     { file: 'opening.mp4',    keywords: ['aç','başlat','çalıştır'] },
  memory:   { file: 'memory.mp4',     keywords: ['hatırlıyor musun','hafıza','ne biliyorsun'] },
  list:     { file: 'listing.mp4',    keywords: ['listele','göster','neler var'] },
  save:     { file: 'saving.mp4',     keywords: ['kaydet','hatırla','not al'] },
  thinking: { file: 'thinking.mp4',   keywords: ['analiz','düşün','ne yapmalı','önerin'] },
};
const FALLBACK_MEDIA = 'general.mp4';

function detectMedia(text) {
  const lower = text.toLowerCase();
  for (const [, val] of Object.entries(MEDIA_MAP)) {
    if (val.keywords.some(kw => lower.includes(kw))) {
      return val.file;
    }
  }
  return FALLBACK_MEDIA;
}

function playMedia(filename) {
  const video = document.getElementById('avatar-video');
  video.src = `media/${filename}`;
  video.classList.add('playing');
  video.play().catch(() => video.classList.remove('playing'));
  video.addEventListener('ended', () => video.classList.remove('playing'), { once: true });
  video.addEventListener('error', () => video.classList.remove('playing'), { once: true });
}

function renderMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- /gm, '• ');
}

function addMessage(role, text) {
  const box = document.getElementById('chat-box');
  const div = document.createElement('div');
  div.className = `msg ${role}`;

  const label = document.createElement('div');
  label.className = 'label';
  label.textContent = role === 'user' ? 'Kaptan' : 'Theia';
  div.appendChild(label);

  const content = document.createElement('div');
  if (role === 'theia') {
    content.innerHTML = renderMarkdown(text);
  } else {
    content.textContent = text;
  }
  div.appendChild(content);

  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function setStatus(text) {
  document.getElementById('status-text').textContent = text;
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if (!text) return;

  addMessage('user', text);
  input.value = '';
  input.style.height = 'auto';

  const filename = detectMedia(text);
  playMedia(filename);
  setStatus('Düşünüyor...');

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, tts: false }),
    });
    const data = await res.json();
    addMessage('theia', data.reply_text || 'Cevap alınamadı.');
  } catch {
    addMessage('theia', 'Bağlantı hatası Kaptan.');
  }

  setStatus('Hazır, Kaptan.');
}

async function checkPendings() {
  try {
    const res = await fetch('/pendings');
    const data = await res.json();
    if (data.pendings && data.pendings.length > 0) {
      addMessage('theia', data.pendings[0].text);
    }
  } catch {
    // sessiz kal
  }
}

document.getElementById('send-btn').addEventListener('click', sendMessage);

document.getElementById('msg-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

document.getElementById('msg-input').addEventListener('input', (e) => {
  e.target.style.height = 'auto';
  e.target.style.height = e.target.scrollHeight + 'px';
});

document.getElementById('mic-btn').addEventListener('click', () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    setStatus('Tarayıcı ses tanımayı desteklemiyor.');
    return;
  }
  const recognition = new SR();
  recognition.lang = 'tr-TR';
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = (e) => {
    const transcript = e.results[0][0].transcript;
    document.getElementById('msg-input').value = transcript;
    sendMessage();
  };
  recognition.onend = () => {
    document.getElementById('mic-btn').classList.remove('active');
  };

  recognition.start();
  document.getElementById('mic-btn').classList.add('active');
  setStatus('Dinliyorum...');
});

document.addEventListener('DOMContentLoaded', checkPendings);
