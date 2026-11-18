// Код, що виконується ВСЕРЕДИНІ сторінки YouTube (світ MAIN, через chrome.scripting.executeScript).
// Функція серіалізується і передається у вкладку, тому вона повністю самодостатня:
// жодних посилань на змінні чи імпорти ззовні.
//
// Керуємо через власний API плеєра YouTube (#movie_player), щоб інтерфейс сайту
// (повзунок гучності, меню швидкості) лишався синхронним; <video> — запасний варіант.

export function pageCommand(name, arg) {
  try {
    const isMusic = location.hostname === 'music.youtube.com';
    const isShorts = location.pathname.startsWith('/shorts/');
    const q = (sel, root) => (root || document).querySelector(sel);
    const shown = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const click = (el) => { if (!el) return false; el.click(); return true; };

    // ---- пошук плеєра та відео
    let player = null;
    let video = null;
    if (isShorts) {
      const reel = q('ytd-reel-video-renderer[is-active]');
      player = q('#shorts-player') || (reel && q('.html5-video-player', reel));
      video = (reel && q('video', reel)) || (player && q('video', player));
    }
    if (!player) player = q('#movie_player') || q('.html5-video-player');
    if (!video) {
      const all = Array.from(document.querySelectorAll('video'));
      video = all.find((v) => !v.paused && !v.ended && v.readyState > 1) ||
              (player && (q('video.html5-main-video', player) || q('video', player))) ||
              all.find((v) => v.currentSrc || v.src) || null;
    }
    // Сторінка без відео (головна, пошук): немає чим керувати — нехай розширення спробує іншу вкладку
    if (!video || (!video.currentSrc && !video.src && video.readyState === 0)) {
      return { ok: false, err: 'no_video' };
    }

    const has = (fn) => !!player && typeof player[fn] === 'function';
    const call = (fn, ...a) => { try { return player[fn](...a); } catch (e) { return undefined; } };

    const getVol = () => {
      const v = has('getVolume') ? call('getVolume') : undefined;
      return typeof v === 'number' && isFinite(v) ? v : Math.round(video.volume * 100);
    };
    const isMuted = () => {
      const m = has('isMuted') ? call('isMuted') : undefined;
      return typeof m === 'boolean' ? m : video.muted;
    };
    const duration = () => (isFinite(video.duration) ? video.duration : 0);
    const seekTo = (t) => {
      const d = duration();
      const target = d > 0 ? clamp(t, 0, Math.max(0, d - 0.25)) : Math.max(0, t);
      if (has('seekTo')) call('seekTo', target, true); else video.currentTime = target;
      return target;
    };

    let note = '';
    let paused = video.paused;
    let time = video.currentTime;
    let rate = video.playbackRate;
    let vol = getVol();
    let muted = isMuted();

    const play = () => {
      if (has('playVideo')) call('playVideo');
      else { const p = video.play(); if (p && p.catch) p.catch(() => {}); }
      paused = false;
    };
    const pause = () => {
      if (has('pauseVideo')) call('pauseVideo'); else video.pause();
      paused = true;
    };

    switch (name) {
      case 'STATE':
        break;

      case 'PLAYPAUSE':
        if (video.paused || video.ended) play(); else pause();
        break;
      case 'PLAY':
        play();
        break;
      case 'PAUSE':
        pause();
        break;

      case 'SEEK':
        time = seekTo(video.currentTime + Number(arg || 0));
        break;
      case 'RESTART':
        time = seekTo(0);
        break;
      case 'SEEKPCT':
        if (duration() <= 0) return { ok: false, err: 'unsupported' };
        time = seekTo(duration() * clamp(Number(arg || 0), 0, 100) / 100);
        break;

      case 'VOL': {
        const delta = Number(arg || 0);
        vol = clamp(Math.round(getVol() + delta), 0, 100);
        const slider = isMusic ? q('#volume-slider') : null;
        if (slider && 'value' in slider) {
          // YouTube Music тримає гучність у власному повзунку
          slider.value = vol;
          slider.dispatchEvent(new Event('change', { bubbles: true }));
        } else if (has('setVolume')) {
          if (delta > 0 && isMuted() && has('unMute')) call('unMute');
          call('setVolume', vol);
        } else {
          video.volume = vol / 100;
          if (delta > 0) video.muted = false;
        }
        muted = delta > 0 ? false : isMuted();
        break;
      }
      case 'MUTE':
        if (has('mute') && has('unMute')) {
          if (isMuted()) { call('unMute'); muted = false; } else { call('mute'); muted = true; }
        } else {
          video.muted = !video.muted;
          muted = video.muted;
        }
        break;

      case 'SPEED':
      case 'SPEEDSET': {
        const avail = has('getAvailablePlaybackRates') ? call('getAvailablePlaybackRates') : null;
        const max = Array.isArray(avail) && avail.length ? Math.max(...avail) : 2;
        const wanted = name === 'SPEEDSET' ? Number(arg) : video.playbackRate + Number(arg || 0);
        rate = clamp(Math.round(wanted * 100) / 100, 0.25, Math.max(2, max));
        if (Array.isArray(avail) && avail.includes(rate) && has('setPlaybackRate')) call('setPlaybackRate', rate);
        else video.playbackRate = rate;
        break;
      }

      case 'NEXT':
        if (isShorts) {
          if (!click(q('#navigation-button-down button'))) return { ok: false, err: 'unsupported' };
        } else if (isMusic) {
          if (!click(q('ytmusic-player-bar .next-button')) && has('nextVideo')) call('nextVideo');
        } else {
          const btn = q('.ytp-next-button', player || document);
          if (shown(btn)) click(btn);
          else if (has('nextVideo')) call('nextVideo');
          else return { ok: false, err: 'unsupported' };
        }
        break;

      case 'PREV':
        if (isShorts) {
          if (!click(q('#navigation-button-up button'))) return { ok: false, err: 'unsupported' };
        } else if (isMusic) {
          if (!click(q('ytmusic-player-bar .previous-button')) && has('previousVideo')) call('previousVideo');
        } else if (video.currentTime > 5) {
          // як у звичайних плеєрах: спершу на початок, повторне натискання — попереднє відео
          time = seekTo(0);
          note = 'restart';
        } else {
          const btn = q('.ytp-prev-button', player || document);
          let prevIsVideo = false;
          try {
            const nav = window.navigation;
            const idx = nav && nav.currentEntry ? nav.currentEntry.index : -1;
            const prev = idx > 0 ? nav.entries()[idx - 1] : null;
            prevIsVideo = !!prev && /\/(watch|shorts\/|live\/)/.test(new URL(prev.url).pathname);
          } catch (e) { /* Navigation API недоступний */ }
          if (shown(btn)) click(btn);                 // плейлист
          else if (prevIsVideo) history.back();       // попереднє відео в цій вкладці
          else { time = seekTo(0); note = 'restart'; }
        }
        break;

      case 'CAPTIONS': {
        if (isMusic || isShorts) return { ok: false, err: 'unsupported' };
        const btn = q('.ytp-subtitles-button', player || document);
        if (!shown(btn) || btn.getAttribute('aria-disabled') === 'true' || btn.disabled) {
          note = 'na';
        } else {
          const wasOn = btn.getAttribute('aria-pressed') === 'true';
          click(btn);
          note = wasOn ? 'captions_off' : 'captions_on';
        }
        break;
      }

      case 'THEATER': {
        if (isMusic || isShorts) return { ok: false, err: 'unsupported' };
        const btn = q('.ytp-size-button', player || document);
        if (!shown(btn)) return { ok: false, err: 'unsupported' };
        click(btn);
        break;
      }

      case 'LIKE': {
        const scope = isShorts ? (q('ytd-reel-video-renderer[is-active]') || document) : document;
        const btn = isMusic
          ? q('ytmusic-player-bar ytmusic-like-button-renderer #button-shape-like button') ||
            q('ytmusic-player-bar ytmusic-like-button-renderer .like')
          : q('like-button-view-model button', scope) ||
            q('#segmented-like-button button', scope) ||
            q('ytd-toggle-button-renderer#like-button button', scope) ||
            q('#like-button button', scope);
        if (!btn) {
          note = 'na';
        } else {
          const wasOn = btn.getAttribute('aria-pressed') === 'true';
          click(btn);
          note = wasOn ? 'like_off' : 'like_on';
        }
        break;
      }

      default:
        return { ok: false, err: 'unknown' };
    }

    // ---- назва відео
    let title = '';
    const data = has('getVideoData') ? call('getVideoData') : null;
    if (data && typeof data.title === 'string') title = data.title;
    if (!title) title = document.title.replace(/^\(\d+\)\s*/, '').replace(/\s*[-–|]\s*YouTube( Music)?\s*$/i, '');
    const live = !isFinite(video.duration) || !!(data && data.isLive);

    return {
      ok: true,
      site: isMusic ? 'music' : (isShorts ? 'shorts' : 'yt'),
      title: String(title).slice(0, 160),
      paused, muted, live, note,
      time: Math.max(0, Number(time) || 0),
      dur: duration(),
      vol: Number(vol) || 0,
      rate: Number(rate) || 1,
    };
  } catch (e) {
    return { ok: false, err: 'failed', note: String(e && e.message || e).slice(0, 24) };
  }
}
