// Наскрізний тест розширення YouTube у справжньому Chromium:
//
//   програма (threads.WebSocketServerThread, через app_bridge.py)
//        <— WebSocket —>  розширення (extension/, завантажене як розпаковане)
//        <— chrome.scripting —>  дві вкладки з імітацією YouTube (fake_youtube.cjs)
//
// Запуск:  node tests/extension/e2e.cjs     (потрібні Playwright + Chromium, python з PySide6/websockets)
// Змінні:  VPT_PYTHON — інтерпретатор для містка (за замовчуванням python3)
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { chromium } = require('playwright');
const fakeYouTube = require('./fake_youtube.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const EXT_DIR = path.join(ROOT, 'extension');
const WS_PORT = 8765;   // порт зашитий у розширенні

let checks = 0;
const failures = [];
function check(cond, what) {
  checks++;
  if (!cond) { failures.push(what); console.error('  FAIL:', what); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, what, timeout = 8000) {
  const end = Date.now() + timeout;
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() > end) throw new Error('timeout: ' + what);
    await sleep(50);
  }
}

// ---------------------------------------------------------------- місток до програми
function startBridge() {
  const py = process.env.VPT_PYTHON || 'python3';
  const proc = spawn(py, [path.join(__dirname, 'app_bridge.py'), String(WS_PORT)], {
    env: { ...process.env, QT_QPA_PLATFORM: 'offscreen' }, stdio: ['pipe', 'pipe', 'inherit'],
  });
  const bridge = { proc, feedback: [], clients: 0, versions: '', rejected: [], ready: false, noClient: [] };
  readline.createInterface({ input: proc.stdout }).on('line', (line) => {
    if (line.startsWith('READY')) bridge.ready = true;
    else if (line.startsWith('CLIENTS ')) { const p = line.split(' '); bridge.clients = Number(p[1]); bridge.versions = p[2] || ''; }
    else if (line.startsWith('FEEDBACK ')) bridge.feedback.push(JSON.parse(line.slice(9)));
    else if (line.startsWith('REJECTED ')) bridge.rejected.push(line.slice(9));
    else if (line.startsWith('NOCLIENT ')) bridge.noClient.push(line.slice(9));
  });
  /** Надсилає команду і чекає відповідь розширення. */
  bridge.cmd = async (text) => {
    const before = bridge.feedback.length;
    proc.stdin.write(text + '\n');
    await waitFor(() => bridge.feedback.length > before, 'feedback for ' + text);
    return bridge.feedback[bridge.feedback.length - 1];
  };
  bridge.stop = () => { try { proc.stdin.write('QUIT\n'); } catch (e) { /* вже завершився */ } };
  return bridge;
}

async function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vpt-ext-e2e-'));
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=www.youtube.com',
    '-keyout', path.join(tmp, 'key.pem'), '-out', path.join(tmp, 'cert.pem')], { stdio: 'ignore' });
  const { server, port } = await fakeYouTube.start({
    key: fs.readFileSync(path.join(tmp, 'key.pem')), cert: fs.readFileSync(path.join(tmp, 'cert.pem')),
  });

  const bridge = startBridge();
  let context;
  try {
    await waitFor(() => bridge.ready, 'app WebSocket server');

    context = await chromium.launchPersistentContext(path.join(tmp, 'profile'), {
      channel: 'chromium',              // повноцінний Chromium у новому headless-режимі (вміє розширення)
      headless: true,
      ignoreHTTPSErrors: true,
      args: [
        `--disable-extensions-except=${EXT_DIR}`,
        `--load-extension=${EXT_DIR}`,
        `--host-resolver-rules=MAP www.youtube.com 127.0.0.1:${port}, MAP music.youtube.com 127.0.0.1:${port}, MAP evil.example 127.0.0.1:${port}`,
        '--ignore-certificate-errors',
        '--no-proxy-server',
        '--autoplay-policy=no-user-gesture-required',
        '--mute-audio',
      ],
    });

    // 1. Розширення підключилось до програми з origin chrome-extension:// і назвало свою версію
    await waitFor(() => bridge.clients === 1, 'extension connects to the app');
    const version = JSON.parse(fs.readFileSync(path.join(EXT_DIR, 'manifest.json'), 'utf8')).version;
    check(bridge.versions === version, `hello carries version ${version}, got "${bridge.versions}"`);
    check(bridge.rejected.length === 0, 'extension origin is accepted');

    // 2. Немає вкладок YouTube -> чесна відповідь, а не тиша
    let fb = await bridge.cmd('YT_PLAYPAUSE');
    check(fb.ok === false && fb.err === 'no_tab', 'no YouTube tabs -> no_tab');

    const pageA = await context.newPage();
    await pageA.goto('https://www.youtube.com/watch?v=aaa');
    const pageB = await context.newPage();
    await pageB.goto('https://www.youtube.com/watch?v=bbb');
    const st = (page) => page.evaluate(() => window.__state());
    await waitFor(async () => (await st(pageA)).ready >= 1 && (await st(pageB)).ready >= 1, 'media metadata');
    await pageB.bringToFront();

    // 3. Дві вкладки, обидві на паузі: грати починає ЛИШЕ активна (раніше команда йшла в усі вкладки)
    fb = await bridge.cmd('YT_PLAYPAUSE');
    check(fb.ok && fb.paused === false && fb.title === 'Video bbb', 'play starts in the active tab: ' + JSON.stringify(fb));
    await waitFor(async () => !(await st(pageB)).paused, 'tab B playing');
    check((await st(pageA)).paused === true, 'tab A stays paused');
    check((await st(pageB)).calls.some((c) => c[0] === 'playVideo'), 'uses the YouTube player API');

    // 4. Користувач перейшов на вкладку A, а грає B: пауза має зупинити B, а не запустити A
    await pageA.bringToFront();
    await sleep(300);
    fb = await bridge.cmd('YT_PLAYPAUSE');
    check(fb.ok && fb.paused === true && fb.title === 'Video bbb', 'pause hits the playing tab: ' + JSON.stringify(fb));
    await waitFor(async () => (await st(pageB)).paused, 'tab B paused');
    check((await st(pageA)).paused === true, 'tab A was not started');

    // 5. Повторне натискання продовжує те саме відео (B), хоча активна вкладка — A
    fb = await bridge.cmd('YT_PLAYPAUSE');
    check(fb.ok && fb.paused === false && fb.title === 'Video bbb', 'resume returns to the same tab');
    await waitFor(async () => !(await st(pageB)).paused, 'tab B resumed');
    check((await st(pageA)).paused === true, 'tab A still paused');

    // 6. Перемотка
    const t0 = (await st(pageB)).time;
    fb = await bridge.cmd('YT_FWD:30');
    check(fb.ok && fb.cmd === 'SEEK' && fb.dur > 100 && Math.abs(fb.time - (t0 + 30)) < 3, 'seek forward: ' + JSON.stringify(fb));
    await waitFor(async () => (await st(pageB)).time > t0 + 25, 'tab B seeked');
    fb = await bridge.cmd('YT_BACK:10');
    check(fb.ok && fb.time < t0 + 25, 'seek back');
    fb = await bridge.cmd('YT_RESTART');
    check(fb.ok && fb.time < 1, 'restart');

    // 7. Гучність і звук — через API плеєра (інтерфейс сайту лишається синхронним)
    fb = await bridge.cmd('YT_VOL:-15');
    check(fb.ok && fb.cmd === 'VOL' && fb.vol === 85, 'volume down: ' + JSON.stringify(fb));
    check((await st(pageB)).vol === 85 && (await st(pageA)).vol === 100, 'only the target tab volume changed');
    fb = await bridge.cmd('YT_MUTE');
    check(fb.ok && fb.muted === true && (await st(pageB)).muted === true, 'mute');
    fb = await bridge.cmd('YT_VOL:5');
    check(fb.ok && fb.muted === false && fb.vol === 90 && (await st(pageB)).muted === false, 'volume up unmutes');

    // 8. Швидкість
    fb = await bridge.cmd('YT_SPEED:0.25');
    check(fb.ok && fb.rate === 1.25 && (await st(pageB)).rate === 1.25, 'speed up');
    fb = await bridge.cmd('YT_SPEED:=1');
    check(fb.ok && fb.rate === 1 && (await st(pageB)).rate === 1, 'speed reset');

    // 9. Субтитри, режим кінотеатру, лайк
    fb = await bridge.cmd('YT_CAPTIONS');
    check(fb.ok && fb.note === 'captions_on' && (await st(pageB)).cc === 'true', 'captions on');
    fb = await bridge.cmd('YT_THEATER');
    check(fb.ok && (await st(pageB)).theater === true, 'theater mode');
    fb = await bridge.cmd('YT_LIKE');
    check(fb.ok && fb.note === 'like_on' && (await st(pageB)).like === 'true', 'like');
    check((await st(pageA)).like === 'false' && (await st(pageA)).cc === 'false', 'other tab untouched');

    // 10. Наступне відео
    fb = await bridge.cmd('YT_NEXT');
    check(fb.ok && fb.cmd === 'NEXT', 'next video');
    await waitFor(() => pageB.url().includes('v=bb2'), 'tab B navigated to the next video');

    // 11. Вкладку з відео закрили -> керування переходить на ту, що лишилась
    await pageB.close();
    fb = await bridge.cmd('YT_PLAYPAUSE');
    check(fb.ok && fb.title === 'Video aaa' && fb.paused === false, 'falls back to the remaining tab: ' + JSON.stringify(fb));
    await waitFor(async () => !(await st(pageA)).paused, 'tab A playing');

    // 12. Вкладка YouTube без відео (головна) + вкладка з відео: команда йде туди, де відео
    const home = await context.newPage();
    await home.goto('https://www.youtube.com/');
    await home.bringToFront();
    fb = await bridge.cmd('YT_PLAYPAUSE');
    check(fb.ok && fb.title === 'Video aaa' && fb.paused === true, 'skips the page without video');
    await pageA.close();
    fb = await bridge.cmd('YT_PLAYPAUSE');
    check(fb.ok === false && fb.err === 'no_video', 'only a page without video -> no_video: ' + JSON.stringify(fb));

    // 13. Сторонній сайт не може підключитись до програми
    const evil = await context.newPage();
    await evil.goto('https://evil.example/');
    const closeCode = await evil.evaluate((wsPort) => new Promise((resolve) => {
      const ws = new WebSocket('ws://localhost:' + wsPort);
      ws.onclose = (e) => resolve(e.code);
      setTimeout(() => resolve('still-open'), 4000);
    }), WS_PORT);
    check(closeCode === 1008, 'foreign website is rejected with 1008, got ' + closeCode);
    await waitFor(() => bridge.rejected.length > 0, 'app reports the rejected origin', 3000).catch(() => {});
    check(bridge.rejected.includes('https://evil.example'), 'app logged the rejected origin: ' + JSON.stringify(bridge.rejected));
    check(bridge.clients === 1, 'extension is still the only client');
  } finally {
    if (context) await context.close().catch(() => {});
    bridge.stop();
    server.close();
    await sleep(300);
    try { bridge.proc.kill(); } catch (e) { /* already gone */ }
    fs.rmSync(tmp, { recursive: true, force: true });
  }

  if (failures.length) {
    console.error(`E2E FAILED: ${failures.length} of ${checks} checks`);
    process.exit(1);
  }
  console.log(`E2E OK: ${checks} checks passed`);
}

main().catch((e) => { console.error('E2E ERROR:', e && e.stack || e); process.exit(2); });
