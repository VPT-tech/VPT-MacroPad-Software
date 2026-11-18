// Модульні тести розширення (без браузера):  node --test tests/extension/
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseCommand, rankTargets, siteOf, isMediaUrl } from '../../extension/targeting.js';

const W = 'https://www.youtube.com/watch?v=';
const tab = (id, url, extra = {}) => ({ id, url, audible: false, active: false, windowId: 1, lastAccessed: id, ...extra });
const ids = (tabs) => tabs.map((t) => t.id);

test('siteOf / isMediaUrl', () => {
  assert.equal(siteOf(W + 'a'), 'yt');
  assert.equal(siteOf('https://music.youtube.com/'), 'music');
  assert.equal(siteOf('https://youtube.com.evil.example/watch?v=a'), null);
  assert.equal(siteOf('http://www.youtube.com/watch?v=a'), null);
  assert.equal(siteOf('not a url'), null);
  assert.ok(isMediaUrl(W + 'a'));
  assert.ok(isMediaUrl('https://www.youtube.com/shorts/abc'));
  assert.ok(isMediaUrl('https://music.youtube.com/playlist?list=x'));
  assert.ok(!isMediaUrl('https://www.youtube.com/'));
  assert.ok(!isMediaUrl('https://www.youtube.com/results?search_query=x'));
});

test('parseCommand: старі команди програми працюють як раніше', () => {
  assert.deepEqual(parseCommand('YT_PLAYPAUSE'), { name: 'PLAYPAUSE', arg: null });
  assert.deepEqual(parseCommand('YT_FWD:10'), { name: 'SEEK', arg: 10 });
  assert.deepEqual(parseCommand('YT_BACK:5'), { name: 'SEEK', arg: -5 });
  assert.deepEqual(parseCommand('YT_FWD'), { name: 'SEEK', arg: 10 });
});

test('parseCommand: нові команди', () => {
  assert.deepEqual(parseCommand('YT_VOL:-5'), { name: 'VOL', arg: -5 });
  assert.deepEqual(parseCommand('YT_SPEED:0.25'), { name: 'SPEED', arg: 0.25 });
  assert.deepEqual(parseCommand('YT_SPEED:=1'), { name: 'SPEEDSET', arg: 1 });
  assert.deepEqual(parseCommand(' YT_NEXT '), { name: 'NEXT', arg: null });
  for (const c of ['YT_PREV', 'YT_MUTE', 'YT_RESTART', 'YT_CAPTIONS', 'YT_THEATER', 'YT_LIKE']) {
    assert.ok(parseCommand(c), c);
  }
});

test('parseCommand: сміття та небезпечні значення відкидаються або обрізаються', () => {
  for (const bad of ['', 'PLAY', 'YT_UNKNOWN', 'YT_FWD:abc', 'YT_FWD:-3', 'YT_VOL:', 'YT_VOL:0', 'YT_SPEED:=',
    'YT_PLAYPAUSE:1', 'YT_FWD:1e999', null, 42, {}, 'YT_FWD:' + '9'.repeat(100)]) {
    assert.equal(parseCommand(bad), null, String(bad));
  }
  assert.deepEqual(parseCommand('YT_FWD:99999'), { name: 'SEEK', arg: 600 });
  assert.deepEqual(parseCommand('YT_VOL:999'), { name: 'VOL', arg: 100 });
  assert.deepEqual(parseCommand('YT_SPEED:=99'), { name: 'SPEEDSET', arg: 4 });
});

test('дві вкладки з відео: керуємо тією, що звучить, а не обома', () => {
  const tabs = [tab(1, W + 'a', { active: true }), tab(2, W + 'b', { audible: true })];
  assert.deepEqual(ids(rankTargets(tabs, { focusedWindowId: 1 })), [2, 1]);
});

test('після паузи наступне натискання повертається до тієї самої вкладки', () => {
  // вкладку 2 поставили на паузу з макропада (вже не звучить), користувач дивиться на вкладку 1
  const tabs = [tab(1, W + 'a', { active: true }), tab(2, W + 'b')];
  assert.equal(rankTargets(tabs, { focusedWindowId: 1, lastTargetId: 2 })[0].id, 2);
});

test('нічого не грало: активна вкладка з відео у вікні, що у фокусі', () => {
  const tabs = [
    tab(1, W + 'a', { lastAccessed: 900 }),
    tab(2, W + 'b', { active: true, windowId: 7, lastAccessed: 100 }),
    tab(3, W + 'c', { active: true, windowId: 8, lastAccessed: 950 }),
  ];
  assert.equal(rankTargets(tabs, { focusedWindowId: 7 })[0].id, 2);
});

test('сторінка без відео (головна) поступається вкладці з відео', () => {
  const tabs = [tab(1, 'https://www.youtube.com/', { active: true }), tab(2, W + 'b')];
  assert.deepEqual(ids(rankTargets(tabs, { focusedWindowId: 1 })), [2, 1]);
});

test('серед рівних — та, де були останньою', () => {
  const tabs = [tab(1, W + 'a', { lastAccessed: 10 }), tab(2, W + 'b', { lastAccessed: 30 }), tab(3, W + 'c', { lastAccessed: 20 })];
  assert.deepEqual(ids(rankTargets(tabs, {})), [2, 3, 1]);
});

test('закріплена вручну вкладка — єдина ціль, навіть якщо звучить інша', () => {
  const tabs = [tab(1, W + 'a'), tab(2, W + 'b', { audible: true })];
  assert.deepEqual(ids(rankTargets(tabs, { pinnedTabId: 1 })), [1]);
  // закріплену вкладку закрили — повертаємось до автоматичного вибору
  assert.deepEqual(ids(rankTargets(tabs, { pinnedTabId: 99 })), [2, 1]);
});

test('чужі сайти та вивантажені вкладки не розглядаються', () => {
  const tabs = [tab(1, 'https://example.com/watch?v=a', { audible: true }), tab(2, W + 'b', { discarded: true }), tab(3, W + 'c')];
  assert.deepEqual(ids(rankTargets(tabs, {})), [3]);
  assert.deepEqual(rankTargets([], {}), []);
  assert.deepEqual(rankTargets(null, {}), []);
});

test('YouTube Music у фоні звучить — керуємо ним', () => {
  const tabs = [tab(1, W + 'a', { active: true }), tab(2, 'https://music.youtube.com/', { audible: true })];
  assert.equal(rankTargets(tabs, { focusedWindowId: 1 })[0].id, 2);
});
