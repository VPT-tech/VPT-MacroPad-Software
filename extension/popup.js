// Вікно розширення: стан підключення до програми та вибір вкладки, якою керує макропад.

const $ = (id) => document.getElementById(id);
const ask = (msg) => chrome.runtime.sendMessage(msg);

function cleanTitle(title) {
  return String(title || '').replace(/^\(\d+\)\s*/, '').replace(/\s*[-–|]\s*YouTube( Music)?\s*$/i, '') || 'YouTube';
}

function tabRow({ value, checked, name, sub, badge }) {
  const label = document.createElement('label');
  label.className = 'tab' + (checked ? ' selected' : '');
  const input = document.createElement('input');
  input.type = 'radio';
  input.name = 'target';
  input.value = value;
  input.checked = checked;
  input.addEventListener('change', async () => {
    await ask({ type: 'pin', tabId: value === 'auto' ? null : Number(value) });
    render();
  });
  const text = document.createElement('span');
  text.className = 'name';
  text.textContent = name;
  if (sub) {
    const s = document.createElement('span');
    s.className = 'sub';
    s.textContent = sub;
    text.appendChild(s);
  }
  label.append(input, text);
  if (badge) {
    const b = document.createElement('span');
    b.className = 'badge';
    b.textContent = badge;
    label.appendChild(b);
  }
  return label;
}

async function render() {
  let st = null;
  try {
    st = await ask({ type: 'status' });
  } catch (e) { /* service worker ще запускається */ }
  if (!st) return;

  $('status').className = 'status ' + (st.connected ? 'on' : 'off');
  $('status-text').textContent = st.connected ? 'Підключено' : 'Не підключено';
  const hint = $('hint');
  hint.hidden = st.connected;
  hint.textContent = st.connected ? '' : 'Запустіть програму VPT | Pad — розширення підключиться саме протягом пів хвилини.';

  const box = $('tabs');
  box.replaceChildren();
  if (!st.tabs.length) {
    const p = document.createElement('div');
    p.className = 'empty';
    p.textContent = 'Немає відкритих вкладок YouTube.';
    box.appendChild(p);
    return;
  }
  const autoTab = st.tabs.find((t) => t.id === st.autoTargetTabId);
  box.appendChild(tabRow({
    value: 'auto',
    checked: st.pinnedTabId == null,
    name: 'Автоматично',
    sub: autoTab ? 'зараз: ' + cleanTitle(autoTab.title) : 'вкладка, що грає, або остання активна',
  }));
  for (const t of st.tabs) {
    box.appendChild(tabRow({
      value: String(t.id),
      checked: st.pinnedTabId === t.id,
      name: cleanTitle(t.title),
      sub: t.site === 'music' ? 'YouTube Music' : '',
      badge: t.audible ? 'ГРАЄ' : '',
    }));
  }
}

$('test').addEventListener('click', async () => {
  const out = $('result');
  out.className = 'result';
  out.textContent = '…';
  const res = await ask({ type: 'cmd', raw: 'YT_PLAYPAUSE' });
  if (res && res.ok) {
    out.textContent = (res.paused ? 'Пауза: ' : 'Грає: ') + cleanTitle(res.title);
  } else {
    out.className = 'result bad';
    out.textContent = 'Відео не знайдено';
  }
  render();
});

render();
