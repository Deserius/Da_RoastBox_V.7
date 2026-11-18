import { useEffect, useRef, useState } from "react";
import { isBrowserSpeechSupported, speakWithBrowserVoice, stopBrowserSpeech, unlockBrowserSpeech } from "@/lib/sandboxSpeech";
import { mediaObjectUrl } from "@/lib/media";

const REACTION_ICON = { ooh: "😮 ooh", groan: "😬 groan", cheer: "🙌 cheer" };

export const ShowTranscript = ({ transcript, personaById, activeIdx, emptyText }) => {
  const [playingIdx, setPlayingIdx] = useState(null);
  const stopRef = useRef(null);

  const stopLine = () => {
    stopRef.current?.();
    stopRef.current = null;
    setPlayingIdx(null);
  };

  useEffect(() => () => stopLine(), []);

  const playLine = async (line, i) => {
    if (playingIdx === i) {
      stopLine();
      return;
    }
    stopLine();
    unlockBrowserSpeech();
    setPlayingIdx(i);

    const p = personaById[line.introduced_persona_id || line.persona_id] || personaById[line.persona_id] || {};
    const useSpeech = (line.provider === "sandbox_preview" || !line.audio_url) && isBrowserSpeechSupported();

    if (useSpeech) {
      stopRef.current = speakWithBrowserVoice({
        text: line.text,
        personaId: line.introduced_persona_id || line.persona_id,
        personaMeta: p,
        emotion: line.emotion,
        rapidFire: !!line.rapid_fire,
        premiumVoice: !!line.premium_voice,
        onDone: () => {
          stopRef.current = null;
          setPlayingIdx((cur) => (cur === i ? null : cur));
        },
      });
      return;
    }

    if (line.audio_url) {
      let release = () => {};
      try {
        const { url, revoke } = await mediaObjectUrl(line.audio_url);
        release = revoke;
        const audio = new Audio(url);
        const cleanup = () => {
          audio.pause();
          release();
        };
        stopRef.current = cleanup;
        audio.onended = () => {
          cleanup();
          stopRef.current = null;
          setPlayingIdx((cur) => (cur === i ? null : cur));
        };
        audio.onerror = () => {
          cleanup();
          stopRef.current = null;
          setPlayingIdx((cur) => (cur === i ? null : cur));
        };
        await audio.play();
      } catch {
        release();
        stopLine();
      }
      return;
    }
    setPlayingIdx(null);
  };

  if (!transcript.length) return emptyText ? <div className="empty-state">{emptyText}</div> : null;
  return (
    <details className="transcript-disclosure" data-testid="transcript-disclosure">
      <summary>View full transcript</summary>
      <div className="transcript" data-testid="transcript">
        {transcript.map((line, i) => {
          const p = personaById[line.persona_id] || {};
          const t = line.type || "joke";
          const reaction = REACTION_ICON[line.reaction];
          const isLinePlaying = playingIdx === i;
          return (
            <div key={i} className={`transcript-line ${activeIdx === i ? "active" : ""} line-${t}`} data-testid={`transcript-line-${i}`}>
              <img className="avatar" src={`/${p.image || ""}`} alt={p.name || ""} />
              <div className="body">
                <div className="name" style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
                  <span>{p.displayName || p.name}</span>
                  <span className={`beat-tag tag-${t}`} data-testid={`beat-tag-${i}`}>{t.replace("_", " ").toUpperCase()}</span>
                  {line.emotion && <span className="emotion-tag" data-testid={`emotion-tag-${i}`}>{line.emotion.replace("_", " ")}</span>}
                  {line.laugh_after && line.laugh_after !== "none" && (
                    <span className="laugh-tag" data-testid={`laugh-tag-${i}`}>{reaction || "😂"} {line.laugh_after}</span>
                  )}
                  <button
                    type="button"
                    className="btn-secondary"
                    style={{ marginLeft: "auto", padding: "2px 8px", fontSize: 11, minHeight: 24 }}
                    onClick={() => playLine(line, i)}
                    data-testid={`play-line-${i}-btn`}
                  >
                    {isLinePlaying ? "⏹ Stop" : "🔊 Play"}
                  </button>
                </div>
                <div className="text">{line.text}</div>
              </div>
            </div>
          );
        })}
      </div>
    </details>
  );
};
