// Імітація YouTube для наскрізного тесту розширення: ті самі селектори та API плеєра
// (#movie_player.playVideo/seekTo/setVolume..., .ytp-next-button, .ytp-subtitles-button ...),
// які використовує extension/page.js. Справжній youtube.com з тестового середовища недоступний.
const https = require('node:https');

function toneWav(seconds = 120, rate = 8000) {
  const n = seconds * rate;
  const buf = Buffer.alloc(44 + n);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n, 4); buf.write('WAVEfmt ', 8);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate, 28); buf.writeUInt16LE(1, 32); buf.writeUInt16LE(8, 34);
  buf.write('data', 36); buf.writeUInt32LE(n, 40);
  for (let i = 0; i < n; i++) buf[44 + i] = 128 + Math.round(60 * Math.sin(2 * Math.PI * 440 * i / rate));
  return buf;
}

const NEXT_OF = { aaa: 'aa2', bbb: 'bb2', ccc: 'cc2' };

function watchPage(id) {
  const next = NEXT_OF[id] || id + 'x';
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>(3) Video ${id} - YouTube</title></head><body>
<div id="movie_player" class="html5-video-player">
  <video class="html5-main-video" src="/media/tone.wav?${id}" preload="auto" loop></video>
  <a class="ytp-prev-button" style="display:none" href="#">prev</a>
  <a class="ytp-next-button" href="/watch?v=${next}">next</a>
  <button class="ytp-subtitles-button" aria-pressed="false">cc</button>
  <button class="ytp-size-button">theater</button>
</div>
<like-button-view-model><button aria-pressed="false">like</button></like-button-view-model>
<script>
  window.__calls = [];
  const p = document.getElementById('movie_player');
  const v = p.querySelector('video');
  const log = (name, ...a) => window.__calls.push([name, ...a]);
  let vol = 100, muted = false;
  Object.assign(p, {
    playVideo() { log('playVideo'); v.play().catch(() => {}); },
    pauseVideo() { log('pauseVideo'); v.pause(); },
    seekTo(t) { log('seekTo', t); v.currentTime = t; },
    getVolume() { return vol; },
    setVolume(x) { log('setVolume', x); vol = x; v.volume = x / 100; },
    isMuted() { return muted; },
    mute() { log('mute'); muted = true; v.muted = true; },
    unMute() { log('unMute'); muted = false; v.muted = false; },
    getAvailablePlaybackRates() { return [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2]; },
    setPlaybackRate(r) { log('setPlaybackRate', r); v.playbackRate = r; },
    getVideoData() { return { title: 'Video ${id}', isLive: false }; },
  });
  for (const sel of ['.ytp-subtitles-button', 'like-button-view-model button']) {
    const b = document.querySelector(sel);
    b.addEventListener('click', () => b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true')));
  }
  document.querySelector('.ytp-size-button').addEventListener('click', () => document.body.toggleAttribute('data-theater'));
  window.__state = () => ({ paused: v.paused, time: v.currentTime, vol, muted, rate: v.playbackRate,
    cc: document.querySelector('.ytp-subtitles-button').getAttribute('aria-pressed'),
    like: document.querySelector('like-button-view-model button').getAttribute('aria-pressed'),
    theater: document.body.hasAttribute('data-theater'), ready: v.readyState, calls: window.__calls });
</script></body></html>`;
}

const HOME = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>YouTube</title></head><body><h1>Home (no video)</h1></body></html>';

function start({ key, cert }) {
  const wav = toneWav();
  const server = https.createServer({ key, cert }, (req, res) => {
    const url = new URL(req.url, 'https://www.youtube.com');
    if (url.pathname === '/media/tone.wav') {
      // Підтримка Range потрібна, щоб <video> умів перемотувати
      const range = /bytes=(\d+)-(\d*)/.exec(req.headers.range || '');
      if (range) {
        const startB = Number(range[1]);
        const endB = range[2] ? Number(range[2]) : wav.length - 1;
        res.writeHead(206, { 'Content-Type': 'audio/wav', 'Accept-Ranges': 'bytes',
          'Content-Range': `bytes ${startB}-${endB}/${wav.length}`, 'Content-Length': endB - startB + 1 });
        res.end(wav.subarray(startB, endB + 1));
      } else {
        res.writeHead(200, { 'Content-Type': 'audio/wav', 'Accept-Ranges': 'bytes', 'Content-Length': wav.length });
        res.end(wav);
      }
    } else if (url.pathname === '/watch') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(watchPage(url.searchParams.get('v') || 'x'));
    } else {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(HOME);
    }
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port })));
}

module.exports = { start };
