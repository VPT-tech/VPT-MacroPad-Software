// VPT Pad — YouTube Control: фоновий service worker (Manifest V3).
//
// Тримає WebSocket з програмою VPT | Pad (ws://localhost:8765), отримує від неї команди
// (YT_PLAYPAUSE, YT_FWD:10, YT_VOL:-5 ...), обирає ОДНУ вкладку YouTube і виконує команду в ній.
// Результат (назва відео, позиція, гучність ...) надсилається назад — програма показує його в OSD.

import { YT_URL_PATTERNS, siteOf, parseCommand, rankTargets } from './targeting.js';
import { pageCommand } from './page.js';

const WS_URL = 'ws://localhost:8765';
const KEEPALIVE_MS = 20000;          // обмін повідомленнями не дає Chrome приспати service worker (Chrome 116+)
const RECONNECT_ALARM = 'vpt-reconnect';
const RECONNECT_PERIOD_MIN = 0.5;    // коли програма не запущена — пробуємо підключитись двічі на хвилину

let ws = null;
let keepaliveTimer = null;
let queue = Promise.resolve();       // команди виконуються строго по черзі (важливо для перемотки енкодером)

// ---------------------------------------------------------------- стан
async function getState() {
  const s = await chrome.storage.session.get(['pinnedTabId', 'lastTargetId']);
  return { pinnedTabId: s.pinnedTabId ?? null, lastTargetId: s.lastTargetId ?? null };
}

async function listYouTubeTabs() {
  try {
    return await chrome.tabs.query({ url: YT_URL_PATTERNS });
  } catch (e) {
    return [];
  }
}

async function rankedTabs() {
  const state = await getState();
  let focusedWindowId = null;
  try {
    focusedWindowId = (await chrome.windows.getLastFocused()).id;
  } catch (e) { /* немає вікон */ }
  const tabs = await listYouTubeTabs();
  return { state, ranked: rankTargets(tabs, { ...state, focusedWindowId }), tabs };
}

// ---------------------------------------------------------------- зв'язок з програмою
function isConnected() {
  return !!ws && ws.readyState === WebSocket.OPEN;
}

function send(obj) {
  if (!isConnected()) return false;
  try {
    ws.send(JSON.stringify(obj));
    return true;
  } catch (e) {
    return false;
  }
}

function updateBadge() {
  const on = isConnected();
  try {
    chrome.action.setBadgeText({ text: on ? '' : '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#ff3366' });
    chrome.action.setTitle({
      title: on ? 'VPT Pad — підключено до програми' : 'VPT Pad — програма VPT | Pad не запущена',
    });
  } catch (e) { /* action недоступний під час зупинки */ }
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  let socket;
  try {
    socket = new WebSocket(WS_URL);
  } catch (e) {
    return;
  }
  ws = socket;

  socket.onopen = () => {
    send({ t: 'hello', v: chrome.runtime.getManifest().version });
    clearInterval(keepaliveTimer);
    keepaliveTimer = setInterval(() => send({ t: 'ping' }), KEEPALIVE_MS);
    updateBadge();
    announceIfPlaying();
  };
  socket.onmessage = (ev) => {
    if (typeof ev.data !== 'string') return;
    const cmd = parseCommand(ev.data);
    if (!cmd) return;
    queue = queue.then(async () => {
      const res = await runCommand(cmd);
      send({ t: 'result', cmd: cmd.name, ...res });
    }).catch(() => {});
  };
  const onGone = () => {
    if (ws === socket) ws = null;
    clearInterval(keepaliveTimer);
    keepaliveTimer = null;
    updateBadge();
  };
  socket.onclose = onGone;
  socket.onerror = () => { /* onclose прийде слідом */ };
}

async function ensureAlarm() {
  try {
    if (!(await chrome.alarms.get(RECONNECT_ALARM))) {
      chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: RECONNECT_PERIOD_MIN });
    }
  } catch (e) { /* ignore */ }
}

/** Якщо YouTube вже звучить у цьому браузері — кажемо програмі, що команди варто слати сюди. */
async function announceIfPlaying() {
  const tabs = await listYouTubeTabs();
  if (tabs.some((t) => t.audible)) send({ t: 'active' });
}

// ---------------------------------------------------------------- виконання команди
async function runCommand(cmd) {
  const { ranked } = await rankedTabs();
  let last = { ok: false, err: 'no_tab' };
  for (const tab of ranked) {
    let res = null;
    try {
      const out = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: 'MAIN',
        func: pageCommand,
        args: [cmd.name, cmd.arg ?? null],
      });
      res = out && out[0] ? out[0].result : null;
    } catch (e) {
      continue;                     // вкладка недоступна (вивантажена, помилка сторінки) — пробуємо наступну
    }
    if (!res) continue;
    if (res.ok) {
      await chrome.storage.session.set({ lastTargetId: tab.id });
      return { ...res, tabId: tab.id };
    }
    last = res;
    if (res.err !== 'no_video') break;   // у цій вкладці відео є, але дія недоступна — іншу вкладку не чіпаємо
  }
  return last;
}

// ---------------------------------------------------------------- події браузера
chrome.runtime.onInstalled.addListener(() => { ensureAlarm(); connect(); });
chrome.runtime.onStartup.addListener(() => { ensureAlarm(); connect(); });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONNECT_ALARM) connect();
});

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  // Вкладка YouTube почала звучати — вона стає «останньою ціллю»:
  // якщо її поставити на паузу з макропада, наступне натискання продовжить саме її.
  if (info.audible === true && siteOf(tab.url)) {
    chrome.storage.session.set({ lastTargetId: tabId });
    connect();
    send({ t: 'active' });
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const s = await getState();
  const patch = {};
  if (s.pinnedTabId === tabId) patch.pinnedTabId = null;
  if (s.lastTargetId === tabId) patch.lastTargetId = null;
  if (Object.keys(patch).length) await chrome.storage.session.set(patch);
});

// ---------------------------------------------------------------- вікно розширення (popup)
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || sender.id !== chrome.runtime.id) return false;
  (async () => {
    if (msg.type === 'status') {
      connect();
      const { state, ranked, tabs } = await rankedTabs();
      const autoRanked = rankTargets(tabs, { ...state, pinnedTabId: null });
      sendResponse({
        connected: isConnected(),
        version: chrome.runtime.getManifest().version,
        pinnedTabId: state.pinnedTabId,
        targetTabId: ranked.length ? ranked[0].id : null,
        autoTargetTabId: autoRanked.length ? autoRanked[0].id : null,
        tabs: autoRanked.map((t) => ({ id: t.id, title: t.title || t.url, audible: !!t.audible, site: siteOf(t.url) })),
      });
    } else if (msg.type === 'pin') {
      await chrome.storage.session.set({ pinnedTabId: Number.isInteger(msg.tabId) ? msg.tabId : null });
      sendResponse({ ok: true });
    } else if (msg.type === 'cmd') {
      const cmd = parseCommand(msg.raw);
      sendResponse(cmd ? await runCommand(cmd) : { ok: false, err: 'unknown' });
    } else {
      sendResponse(null);
    }
  })();
  return true;   // відповідь асинхронна
});

// Виконується при кожному старті service worker-а
ensureAlarm();
updateBadge();
connect();
