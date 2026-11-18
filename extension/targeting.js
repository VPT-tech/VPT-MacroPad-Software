// Чисті функції: розбір команд програми та вибір вкладки, якою керувати.
// Тут немає звернень до chrome.*, тому цей файл тестується звичайним Node (tests/extension).

export const YT_URL_PATTERNS = [
  'https://www.youtube.com/*',
  'https://m.youtube.com/*',
  'https://music.youtube.com/*',
];

/** 'yt' | 'music' | null */
export function siteOf(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:') return null;
    if (u.hostname === 'music.youtube.com') return 'music';
    if (u.hostname === 'www.youtube.com' || u.hostname === 'm.youtube.com') return 'yt';
  } catch (e) { /* не URL */ }
  return null;
}

/** Сторінка, на якій точно є плеєр (відео, Shorts, трансляція, YouTube Music). */
export function isMediaUrl(url) {
  const site = siteOf(url);
  if (!site) return false;
  if (site === 'music') return true;
  const p = new URL(url).pathname;
  return p === '/watch' || p.startsWith('/shorts/') || p.startsWith('/live/') ||
         p.startsWith('/embed/') || p.startsWith('/clip/');
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

const SIMPLE = {
  YT_PLAYPAUSE: 'PLAYPAUSE', YT_PLAY: 'PLAY', YT_PAUSE: 'PAUSE', YT_MUTE: 'MUTE',
  YT_NEXT: 'NEXT', YT_PREV: 'PREV', YT_RESTART: 'RESTART', YT_CAPTIONS: 'CAPTIONS',
  YT_THEATER: 'THEATER', YT_LIKE: 'LIKE', YT_STATE: 'STATE',
};

/**
 * Команда програми (рядок) -> {name, arg} або null, якщо команда невідома/некоректна.
 * Старі команди YT_PLAYPAUSE / YT_FWD:n / YT_BACK:n працюють як і раніше.
 */
export function parseCommand(raw) {
  if (typeof raw !== 'string' || raw.length > 64) return null;
  const text = raw.trim();
  const sep = text.indexOf(':');
  const head = sep === -1 ? text : text.slice(0, sep);
  const tail = sep === -1 ? '' : text.slice(sep + 1).trim();

  if (SIMPLE[head] && tail === '') return { name: SIMPLE[head], arg: null };

  if (head === 'YT_FWD' || head === 'YT_BACK') {
    const n = tail === '' ? 10 : Number(tail);
    if (!Number.isFinite(n) || n <= 0) return null;
    const secs = clamp(n, 1, 600);
    return { name: 'SEEK', arg: head === 'YT_FWD' ? secs : -secs };
  }
  if (head === 'YT_VOL') {
    const n = Number(tail);
    if (tail === '' || !Number.isFinite(n) || n === 0) return null;
    return { name: 'VOL', arg: clamp(Math.round(n), -100, 100) };
  }
  if (head === 'YT_SPEED') {
    if (tail.startsWith('=')) {
      const n = Number(tail.slice(1));
      if (tail.length < 2 || !Number.isFinite(n)) return null;
      return { name: 'SPEEDSET', arg: clamp(n, 0.25, 4) };
    }
    const n = Number(tail);
    if (tail === '' || !Number.isFinite(n) || n === 0) return null;
    return { name: 'SPEED', arg: clamp(n, -2, 2) };
  }
  if (head === 'YT_SEEKPCT') {
    const n = Number(tail);
    if (tail === '' || !Number.isFinite(n)) return null;
    return { name: 'SEEKPCT', arg: clamp(n, 0, 100) };
  }
  return null;
}

/**
 * Впорядковує вкладки YouTube за тим, наскільки ймовірно користувач хоче керувати саме нею.
 * Команда виконується в ПЕРШІЙ вкладці, де справді є відео, — тобто завжди тільки в одній
 * (раніше пауза ставилась в усіх відкритих вкладках одразу).
 *
 *  1. вкладка, яку користувач закріпив вручну у вікні розширення (тоді лише вона);
 *  2. вкладка, що зараз звучить;
 *  3. вкладка, якою керували / яка звучала останньою (щоб «пауза → продовжити» влучало в те саме відео);
 *  4. активна вкладка з відео у вікні, що у фокусі;
 *  5. інші вкладки з відео — спершу ті, де були нещодавно;
 *  6. решта вкладок YouTube (на них може грати міні-плеєр).
 *
 * @param tabs  [{id, url, audible, active, windowId, lastAccessed, discarded}]
 * @param state {pinnedTabId, lastTargetId, focusedWindowId}
 */
export function rankTargets(tabs, state = {}) {
  const cands = (tabs || []).filter((t) => t && t.id != null && siteOf(t.url) && !t.discarded);
  if (state.pinnedTabId != null) {
    const pinned = cands.find((t) => t.id === state.pinnedTabId);
    if (pinned) return [pinned];
  }
  const inFocus = (t) => !!t.active && t.windowId === state.focusedWindowId;
  const score = (t) => {
    if (t.audible) return 5;
    if (t.id === state.lastTargetId) return 4;
    if (inFocus(t) && isMediaUrl(t.url)) return 3;
    if (isMediaUrl(t.url)) return 2;
    return 1;
  };
  return cands
    .map((t) => ({ t, s: score(t) }))
    .sort((a, b) =>
      b.s - a.s ||
      Number(inFocus(b.t)) - Number(inFocus(a.t)) ||
      Number(!!b.t.active) - Number(!!a.t.active) ||
      (b.t.lastAccessed || 0) - (a.t.lastAccessed || 0) ||
      b.t.id - a.t.id)
    .map((x) => x.t);
}
