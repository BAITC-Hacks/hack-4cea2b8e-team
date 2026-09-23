/* ============================================================
   ЗОНА НИКОНА. Логика экрана: запросы к API, состояния, рендер.
   Стили сюда не пишем — они в styles.css.
   ============================================================ */

const $ = (s) => document.querySelector(s);
const api = (p, o) => fetch(p, o).then((r) => r.json());
const esc = (s) => String(s).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

async function refresh() {
  const h = await api('/api/health');
  const mode = $('#mode');
  mode.textContent = h.demo_mode ? 'DEMO MODE (без ключа)' : 'LIVE';
  mode.className = 'badge' + (h.demo_mode ? '' : ' badge--live');
  $('#model').textContent = `${h.model} · ${h.llm_calls} вызовов`;

  const items = await api('/api/items');
  $('#items').innerHTML = items.length
    ? items
        .map(
          (i) => `<li class="list__item">
              <span>${esc(i.title)}</span>
              <span><span class="list__meta">${i.created_at}</span>
              <button class="btn--icon" data-del="${i.id}">×</button></span>
            </li>`
        )
        .join('')
    : '<p class="hint">Пока пусто.</p>';
}

document.addEventListener('click', async (e) => {
  const id = e.target.dataset?.del;
  if (!id) return;
  await fetch('/api/items/' + id, { method: 'DELETE' });
  refresh();
});

$('#go').onclick = async () => {
  const prompt = $('#prompt').value.trim();
  if (!prompt) return;
  $('#go').disabled = true;
  $('#out').textContent = '';
  try {
    const res = await fetch('/api/generate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, system: $('#system').value }),
    });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      $('#out').textContent += dec.decode(value, { stream: true });
    }
  } catch (err) {
    $('#out').textContent = 'Ошибка: ' + err.message;
  } finally {
    $('#go').disabled = false;
    refresh();
  }
};

$('#save').onclick = async () => {
  const text = $('#out').textContent.trim();
  if (!text) return;
  await fetch('/api/items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: text.slice(0, 80), payload: { text } }),
  });
  refresh();
};

refresh();
