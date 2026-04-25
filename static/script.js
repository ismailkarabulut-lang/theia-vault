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
  wake:     { file: 'wake.mp4',       keywords: ['hey theia','theia','merhaba theia'] },
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
    .replace(/^---$/gm, '<hr>')
    .replace(/^## (.+)$/gm, '<br><strong>$1</strong><br>')
    .replace(/^### (.+)$/gm, '<em>$1</em><br>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- /gm, '• ')
    .replace(/\n/g, '<br>');
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

// ── /ekle wizard ──────────────────────────────────────────────────────────────

const ekle = { active: false, step: null, data: {}, cardEl: null };

function _ekleBtn(label, onClick) {
  const b = document.createElement('button');
  b.textContent = label;
  b.style.cssText = 'margin:4px 4px 4px 0;padding:8px 14px;background:#1a1a2e;color:#e2e8f0;'
    + 'border:1px solid #7c3aed;border-radius:6px;cursor:pointer;font-size:13px;';
  b.onmouseenter = () => { b.style.background = '#2d2d4e'; };
  b.onmouseleave = () => { b.style.background = '#1a1a2e'; };
  b.onclick = onClick;
  return b;
}

function _ekleInput(placeholder) {
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.placeholder = placeholder;
  inp.style.cssText = 'display:block;width:100%;margin-top:10px;padding:10px 14px;'
    + 'background:#1a1a2e;border:1px solid #1e1e3a;border-radius:6px;'
    + 'color:#e2e8f0;font-size:14px;outline:none;box-sizing:border-box;';
  inp.onfocus = () => { inp.style.borderColor = '#7c3aed'; };
  inp.onblur  = () => { inp.style.borderColor = '#1e1e3a'; };
  return inp;
}

function _scrollBottom() {
  const b = document.getElementById('chat-box');
  b.scrollTop = b.scrollHeight;
}

function ekleStart() {
  ekle.active = true;
  ekle.step = 'type';
  ekle.data = {};
  const chatBox = document.getElementById('chat-box');
  const card = document.createElement('div');
  card.className = 'msg theia';
  const lbl = document.createElement('div');
  lbl.className = 'label';
  lbl.textContent = 'Theia';
  card.appendChild(lbl);
  const body = document.createElement('div');
  card.appendChild(body);
  if (ekle.cardEl) ekle.cardEl.remove();
  ekle.cardEl = card;
  chatBox.appendChild(card);
  _scrollBottom();
  _ekleRender(body);
}

function _ekleRender(body) {
  body.innerHTML = '';

  if (ekle.step === 'type') {
    body.innerHTML = 'Ne eklemek istersiniz?<br><br>';
    [['Görev', 'task'], ['Rutin', 'routine'], ['Hatırlatma', 'reminder']].forEach(([lbl, val]) => {
      body.appendChild(_ekleBtn(lbl, () => {
        ekle.data.type = val;
        ekle.step = 'content';
        _ekleRender(body);
      }));
    });

  } else if (ekle.step === 'content') {
    const typeLabel = { task: 'Görev', routine: 'Rutin', reminder: 'Hatırlatma' }[ekle.data.type];
    body.innerHTML = `<strong>${typeLabel}</strong> seçildi.<br><br>İçerik nedir?`;
    const inp = _ekleInput('Örn: Raporu bitir');
    const btn = _ekleBtn('Devam →', () => {
      const val = inp.value.trim();
      if (!val) return;
      ekle.data.content = val;
      ekle.step = 'time';
      _ekleRender(body);
    });
    btn.style.marginTop = '10px';
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') btn.click(); });
    body.appendChild(inp);
    body.appendChild(btn);
    setTimeout(() => inp.focus(), 50);

  } else if (ekle.step === 'time') {
    body.innerHTML = 'Ne zaman?<br><small style="color:#64748b">Örn: 14:30 veya 23.04.2026 09:00</small>';
    const inp = _ekleInput('14:30');
    const btn = _ekleBtn('Devam →', () => {
      const val = inp.value.trim();
      if (!val) return;
      ekle.data.scheduled_time = val;
      ekle.step = 'check';
      _ekleRender(body);
    });
    btn.style.marginTop = '10px';
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') btn.click(); });
    body.appendChild(inp);
    body.appendChild(btn);
    setTimeout(() => inp.focus(), 50);

  } else if (ekle.step === 'check') {
    body.innerHTML = 'Kontrol süresi?<br><br>';
    [['5 dk', 5], ['10 dk', 10], ['15 dk', 15], ['30 dk', 30], ['1 saat', 60], ['Kontrol etme', 0]].forEach(([lbl, val]) => {
      body.appendChild(_ekleBtn(lbl, async () => {
        ekle.data.check_after = val;
        ekle.active = false;
        ekle.step = null;
        body.innerHTML = '<em style="color:#64748b">Kaydediliyor...</em>';
        await _ekleSubmit(body);
      }));
    });
  }

  _scrollBottom();
}

async function _ekleSubmit(body) {
  try {
    const res = await fetch('/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: ekle.data.type,
        content: ekle.data.content,
        scheduled_time: ekle.data.scheduled_time,
        check_after: ekle.data.check_after,
        recurrence: 'none',
      }),
    });
    const data = await res.json();
    body.innerHTML = data.ok
      ? `✅ Eklendi. <span style="color:#64748b">(#${data.id})</span>`
      : '❌ Eklenemedi.';
  } catch {
    body.innerHTML = '❌ Bağlantı hatası.';
  }
  ekle.cardEl = null;
  _scrollBottom();
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if (!text) return;

  if (text.toLowerCase() === '/ekle') {
    addMessage('user', text);
    input.value = '';
    input.style.height = 'auto';
    ekleStart();
    return;
  }

  addMessage('user', text);
  input.value = '';
  input.style.height = 'auto';

  const filename = detectMedia(text);
  playMedia(filename);
  setStatus('Düşünüyor...');

  const now = new Date();
  const timeStr = now.toLocaleString('tr-TR', {
    weekday: 'long', year: 'numeric', month: 'long',
    day: 'numeric', hour: '2-digit', minute: '2-digit'
  });
  const enriched = `[Şu an: ${timeStr}]\n${text}`;

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: enriched, tts: false }),
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
