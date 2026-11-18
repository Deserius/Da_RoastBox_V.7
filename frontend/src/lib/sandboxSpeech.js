// Browser Web Speech API helper for Arena.ai Workspace Preview Mode when
// outbound AI/TTS APIs are blocked by the sandbox network.

let _activeUtterance = null;
let _voicesCache = [];

export function isBrowserSpeechSupported() {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

function hashString(str) {
  let h = 2166136261;
  const s = String(str || "host");
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function refreshVoices() {
  if (!isBrowserSpeechSupported()) return [];
  const list = window.speechSynthesis.getVoices() || [];
  if (list.length) _voicesCache = list;
  return _voicesCache;
}

export function warmBrowserVoices() {
  if (!isBrowserSpeechSupported()) return Promise.resolve([]);
  const existing = refreshVoices();
  if (existing.length) return Promise.resolve(existing);
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.speechSynthesis.removeEventListener?.("voiceschanged", onChange);
      resolve(refreshVoices());
    };
    const onChange = () => finish();
    window.speechSynthesis.addEventListener?.("voiceschanged", onChange);
    setTimeout(finish, 350);
  });
}

// Call synchronously inside a click handler so Chrome/Safari grants speech autoplay.
export function unlockBrowserSpeech() {
  if (!isBrowserSpeechSupported()) return;
  try {
    refreshVoices();
    const synth = window.speechSynthesis;
    if (synth.paused) synth.resume();
    if (!synth.speaking && !synth.pending) {
      const prime = new window.SpeechSynthesisUtterance(" ");
      prime.volume = 0;
      prime.rate = 2;
      synth.speak(prime);
    }
  } catch {
    // Ignore browser speech priming failures.
  }
}

const FEMALE_RE = /female|zira|aria|jenny|michelle|ana|samantha|victoria|karen|moira|tessa|fiona|susan|hazel|libby|sonia|natasha|ava|allison|kate|serena|veena|sara|emma|amy|joanna|kimberly|kendra|ivy/i;
const MALE_RE = /\bmale\b|david|mark|guy|ryan|christopher|eric|roger|steffan|alex|daniel|fred|george|arthur|oliver|thomas|james|rishi|matthew|joey|justin|brian|russell|lee/i;

function pickVoice(personaMeta, personaId) {
  const all = refreshVoices();
  if (!all.length) return null;
  const english = all.filter((v) => String(v.lang || "").toLowerCase().startsWith("en"));
  const pool = english.length ? english : all;
  const gender = String(personaMeta?.gender || "").toLowerCase();
  let gendered = pool;
  if (gender === "female") {
    const f = pool.filter((v) => FEMALE_RE.test(v.name || ""));
    if (f.length) gendered = f;
  } else if (gender === "male") {
    const m = pool.filter((v) => MALE_RE.test(v.name || "") && !FEMALE_RE.test(v.name || ""));
    if (m.length) gendered = m;
  }
  const h = hashString(personaId || personaMeta?.id || "host");
  return gendered[h % gendered.length] || pool[h % pool.length] || null;
}

export function stopBrowserSpeech() {
  _activeUtterance = null;
  if (!isBrowserSpeechSupported()) return;
  try {
    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
      window.speechSynthesis.cancel();
    }
  } catch {
    // Ignore browser speech cleanup failures.
  }
}

export function speakWithBrowserVoice({
  text,
  personaId,
  personaMeta,
  emotion = "",
  rapidFire = false,
  premiumVoice = false,
  onStart,
  onDone,
  onBlocked,
}) {
  if (!isBrowserSpeechSupported() || !String(text || "").trim()) {
    onDone?.();
    return () => {};
  }

  let cancelled = false;
  let finished = false;
  let startTimer = null;
  let blockCheckTimer = null;
  let maxTimer = null;
  let keepAlive = null;

  const finish = () => {
    if (finished) return;
    finished = true;
    if (startTimer) clearTimeout(startTimer);
    if (blockCheckTimer) clearTimeout(blockCheckTimer);
    if (maxTimer) clearTimeout(maxTimer);
    if (keepAlive) clearInterval(keepAlive);
    if (_activeUtterance && _activeUtterance._token === token) {
      _activeUtterance = null;
    }
    onDone?.();
  };

  const token = Symbol("utterance");

  const startSpeaking = async () => {
    if (cancelled || finished) return;
    await warmBrowserVoices();
    if (cancelled || finished) return;

    const synth = window.speechSynthesis;
    if (synth.paused) {
      try { synth.resume(); } catch {}
    }
    const u = new window.SpeechSynthesisUtterance(String(text).trim());
    u._token = token;
    _activeUtterance = u;

    const voice = pickVoice(personaMeta, personaId);
    if (voice) u.voice = voice;

    const h = hashString(personaId || "host");
    const gender = String(personaMeta?.gender || "").toLowerCase();
    const basePitch = gender === "female" ? 1.08 : gender === "male" ? 0.91 : 1.0;
    const pitchOffset = ((h % 13) - 6) * 0.02;
    let pitch = basePitch + pitchOffset;
    let rate = 1.03 + ((h % 7) - 3) * 0.02;

    if (rapidFire || emotion === "hype" || emotion === "excited") {
      rate += premiumVoice ? 0.11 : 0.07;
      if (premiumVoice) pitch += 0.06;
    } else if (emotion === "outraged" || emotion === "incredulous") {
      if (premiumVoice) { pitch += 0.08; rate += 0.05; }
    } else if (emotion === "deadpan" || emotion === "smug") {
      rate -= premiumVoice ? 0.09 : 0.05;
      if (premiumVoice) pitch -= 0.05;
    } else if (emotion === "whisper" || emotion === "mock_sympathy") {
      if (premiumVoice) { rate -= 0.08; pitch -= 0.04; }
    }

    u.pitch = Math.max(0.76, Math.min(1.34, pitch));
    u.rate = Math.max(0.86, Math.min(1.26, rate));
    u.volume = 1.0;

    let started = false;
    const markStarted = () => {
      if (started || cancelled || finished) return;
      started = true;
      if (blockCheckTimer) { clearTimeout(blockCheckTimer); blockCheckTimer = null; }
      onStart?.();
    };

    u.onstart = markStarted;
    u.onend = finish;
    u.onerror = (evt) => {
      if (evt?.error === "not-allowed" && onBlocked && !cancelled && !finished) {
        if (maxTimer) clearTimeout(maxTimer);
        onBlocked();
        return;
      }
      finish();
    };

    const words = String(text).trim().split(/\s+/).filter(Boolean).length;
    const maxWaitMs = Math.max(4000, Math.min(20000, words * 650 + 2500));
    maxTimer = setTimeout(finish, maxWaitMs);
    keepAlive = setInterval(() => {
      try {
        if (!cancelled && !finished && synth.paused) synth.resume();
      } catch {
        // Ignore resume errors.
      }
    }, 3500);

    // If the browser blocks autoplay without throwing (never starts speaking),
    // prompt the user with the tap-to-play button on beat 0.
    if (onBlocked) {
      blockCheckTimer = setTimeout(() => {
        if (!started && !cancelled && !finished && !synth.speaking) {
          if (maxTimer) clearTimeout(maxTimer);
          onBlocked();
        }
      }, 1100);
    }

    // Smooth fallback caption start if onstart lags slightly while speaking.
    startTimer = setTimeout(() => {
      if (!started && !cancelled && !finished && synth.speaking) markStarted();
    }, 260);

    try {
      synth.speak(u);
    } catch {
      finish();
    }
  };

  try {
    const synth = window.speechSynthesis;
    if (synth.speaking || synth.pending) {
      synth.cancel();
      startTimer = setTimeout(startSpeaking, 30);
    } else {
      startSpeaking();
    }
  } catch {
    finish();
  }

  return () => {
    cancelled = true;
    if (startTimer) clearTimeout(startTimer);
    if (blockCheckTimer) clearTimeout(blockCheckTimer);
    if (maxTimer) clearTimeout(maxTimer);
    if (keepAlive) clearInterval(keepAlive);
    if (_activeUtterance && _activeUtterance._token === token) {
      stopBrowserSpeech();
    }
    finish();
  };
}
