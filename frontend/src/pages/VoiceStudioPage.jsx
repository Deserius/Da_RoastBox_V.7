import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";
import { useToast } from "@/lib/ToastContext";
import { mediaObjectUrl } from "@/lib/media";
import { isBrowserSpeechSupported, speakWithBrowserVoice, stopBrowserSpeech, unlockBrowserSpeech } from "@/lib/sandboxSpeech";

const STATUS_COLORS = {
  operational: "#4ade80",
  available: "#60a5fa",
  missing_model_files: "#fbbf24",
  missing_api_key: "#a1a1aa",
  missing_dependencies: "#f87171",
};

export default function VoiceStudioPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [health, setHealth] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [voices, setVoices] = useState([]);
  const [deliveryProfiles, setDeliveryProfiles] = useState([]);
  const [personasById, setPersonasById] = useState({});
  const [selectedId, setSelectedId] = useState("persona_1");

  // Search & filters
  const [search, setSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState("all");
  const [accentFilter, setAccentFilter] = useState("all");
  const [ageFilter, setAgeFilter] = useState("all");
  const [depthFilter, setDepthFilter] = useState("all");
  const [speedFilter, setSpeedFilter] = useState("all");
  const [tierFilter, setTierFilter] = useState("all");
  const [styleFilter, setStyleFilter] = useState("all");

  // Active editor state
  const [provider, setProvider] = useState("free_local");
  const [voiceId, setVoiceId] = useState("am_adam");
  const [speed, setSpeed] = useState(1.0);
  const [pitch, setPitch] = useState(1.0);
  const [deliveryStyle, setDeliveryStyle] = useState("casual");
  const [roomAmbience, setRoomAmbience] = useState(false);
  const [sampleText, setSampleText] = useState("");
  const [compareVoiceA, setCompareVoiceA] = useState("am_adam");
  const [compareVoiceB, setCompareVoiceB] = useState("af_heart");
  const [compareResults, setCompareResults] = useState([]);

  const [busy, setBusy] = useState(false);
  const [playingLabel, setPlayingLabel] = useState("");
  const [installJob, setInstallJob] = useState(null);
  const audioStopRef = useRef(null);

  const stopPlayback = useCallback(() => {
    audioStopRef.current?.();
    audioStopRef.current = null;
    stopBrowserSpeech();
    setPlayingLabel("");
  }, []);

  useEffect(() => () => stopPlayback(), [stopPlayback]);

  const loadAll = useCallback(async () => {
    try {
      const [hRes, pRes, vRes, dRes, catRes] = await Promise.all([
        api.get("/tts/health"),
        api.get("/tts/profiles"),
        api.get("/tts/voices"),
        api.get("/tts/delivery-profiles"),
        api.get("/personas"),
      ]);
      setHealth(hRes.data);
      setInstallJob(hRes.data?.install_job || null);
      const profs = pRes.data?.profiles || [];
      setProfiles(profs);
      setVoices(vRes.data?.voices || []);
      setDeliveryProfiles(dRes.data?.delivery_profiles || []);
      const map = {};
      (catRes.data?.personas || []).forEach((p) => { map[p.id] = p; });
      setPersonasById(map);
    } catch (e) {
      toast("Failed to load Voice Studio: " + (e?.response?.data?.detail || e.message), "error");
    }
  }, [toast]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const activeProfile = useMemo(
    () => profiles.find((p) => p.persona_id === selectedId) || profiles[0] || null,
    [profiles, selectedId]
  );

  useEffect(() => {
    if (!activeProfile) return;
    setProvider(activeProfile.voice_provider || "free_local");
    setVoiceId(activeProfile.voice_id || "af_heart");
    setSpeed(Number(activeProfile.speaking_rate ?? 1.0));
    setPitch(Number(activeProfile.pitch_adjustment ?? 1.0));
    setDeliveryStyle(activeProfile.speaking_style || "casual");
    setRoomAmbience(!!activeProfile.audio_processing?.room_ambience);
    setSampleText(activeProfile.sample_preview_text || "");
    setCompareVoiceA(activeProfile.voice_id || "am_adam");
  }, [activeProfile]);

  // Poll install progress while running
  useEffect(() => {
    if (installJob?.status !== "running") return;
    const t = setInterval(async () => {
      try {
        const { data } = await api.get("/tts/models/status");
        setInstallJob(data.job);
        if (data.job?.status !== "running") {
          loadAll();
        }
      } catch {
        // ignore transient poll errors
      }
    }, 1500);
    return () => clearInterval(t);
  }, [installJob?.status, loadAll]);

  const filteredProfiles = useMemo(() => {
    const q = search.trim().toLowerCase();
    return profiles.filter((p) => {
      if (q && !(`${p.persona_name} ${p.delivery_personality} ${p.voice_display_name} ${p.accent}`.toLowerCase().includes(q))) return false;
      if (tierFilter !== "all" && p.tier !== tierFilter) return false;
      if (genderFilter !== "all" && p.gender_presentation !== genderFilter) return false;
      if (accentFilter !== "all" && p.accent.toLowerCase() !== accentFilter.toLowerCase()) return false;
      if (ageFilter !== "all" && p.vocal_age !== ageFilter) return false;
      if (depthFilter !== "all" && p.vocal_depth !== depthFilter) return false;
      if (speedFilter === "fast" && p.speaking_rate < 1.08) return false;
      if (speedFilter === "slow" && p.speaking_rate > 0.94) return false;
      if (speedFilter === "normal" && (p.speaking_rate < 0.94 || p.speaking_rate > 1.08)) return false;
      if (styleFilter === "comedic" && !["high_energy_comedy", "sarcastic", "aggressive_roast", "fast_energetic"].includes(p.speaking_style)) return false;
      if (styleFilter === "dramatic" && !["dramatic", "emotional", "slow_deliberate", "whispering"].includes(p.speaking_style)) return false;
      return true;
    });
  }, [profiles, search, tierFilter, genderFilter, accentFilter, ageFilter, depthFilter, speedFilter, styleFilter]);

  const filteredVoices = useMemo(() => {
    return voices.filter((v) => {
      if (genderFilter !== "all" && v.gender !== genderFilter) return false;
      if (accentFilter !== "all" && v.accent.toLowerCase() !== accentFilter.toLowerCase()) return false;
      if (ageFilter !== "all" && v.vocal_age !== ageFilter) return false;
      if (depthFilter !== "all" && v.vocal_depth !== depthFilter) return false;
      return true;
    });
  }, [voices, genderFilter, accentFilter, ageFilter, depthFilter]);

  const playGeneratedResult = async (res, label) => {
    stopPlayback();
    setPlayingLabel(label);
    const meta = personasById[selectedId] || { id: selectedId, gender: activeProfile?.gender_presentation };
    if (res.sandbox_preview && isBrowserSpeechSupported()) {
      audioStopRef.current = speakWithBrowserVoice({
        text: res.text || sampleText,
        personaId: selectedId,
        personaMeta: meta,
        emotion: activeProfile?.default_emotion || "",
        premiumVoice: provider === "elevenlabs" || activeProfile?.tier === "premium",
        onDone: () => setPlayingLabel(""),
      });
      return;
    }
    try {
      const { url, revoke } = await mediaObjectUrl(res.audio_url);
      const audio = new Audio(url);
      audioStopRef.current = () => {
        audio.pause();
        revoke();
      };
      audio.onended = () => { revoke(); setPlayingLabel(""); };
      audio.onerror = () => { revoke(); setPlayingLabel(""); };
      await audio.play();
    } catch {
      setPlayingLabel("");
    }
  };

  const previewVoice = async (overrideVoiceId = null, overrideProvider = null, label = "Preview") => {
    unlockBrowserSpeech();
    setBusy(true);
    try {
      const { data } = await api.post("/tts/preview", {
        text: sampleText || activeProfile?.sample_preview_text || "Welcome to Da RoastBox!",
        persona_id: selectedId,
        provider: overrideProvider || provider,
        voice_id: overrideVoiceId || voiceId,
        speed,
        pitch,
        delivery_style: deliveryStyle,
        room_ambience: roomAmbience,
      });
      await playGeneratedResult(data, label);
      toast(`Playing via ${data.provider} (${data.engine})`, "success");
    } catch (e) {
      toast("Preview failed: " + (e?.response?.data?.detail || e.message), "error");
    } finally {
      setBusy(false);
    }
  };

  const generateSampleRoast = async () => {
    const pName = activeProfile?.persona_name || "Roaster";
    const line = `${pName} checking in on Da RoastBox — looking at that profile photo, even autocorrect gave up and switched to 'thoughts and prayers.'`;
    setSampleText(line);
    unlockBrowserSpeech();
    setBusy(true);
    try {
      const { data } = await api.post("/tts/speak", {
        text: line,
        persona_id: selectedId,
        provider,
        voice_id: voiceId,
        speed,
        pitch,
        delivery_style: deliveryStyle,
        room_ambience: roomAmbience,
      });
      await playGeneratedResult(data, "Sample Roast");
    } catch (e) {
      toast("Roast line failed: " + (e?.response?.data?.detail || e.message), "error");
    } finally {
      setBusy(false);
    }
  };

  const runCompare = async () => {
    unlockBrowserSpeech();
    setBusy(true);
    try {
      const { data } = await api.post("/tts/compare", {
        text: sampleText || activeProfile?.sample_preview_text || "You really walked out the house looking like a group project nobody edited.",
        persona_id: selectedId,
        candidates: [
          { label: `Candidate A (${compareVoiceA})`, provider: "free_local", voice_id: compareVoiceA, speed, pitch, delivery_style: deliveryStyle },
          { label: `Candidate B (${compareVoiceB})`, provider: "free_local", voice_id: compareVoiceB, speed, pitch, delivery_style: deliveryStyle },
        ],
      });
      setCompareResults(data.comparisons || []);
    } catch (e) {
      toast("Comparison failed: " + (e?.response?.data?.detail || e.message), "error");
    } finally {
      setBusy(false);
    }
  };

  const saveAssignment = async () => {
    setBusy(true);
    try {
      const chosenVoice = voices.find((v) => v.voice_id === voiceId);
      const { data } = await api.put(`/tts/profiles/${selectedId}`, {
        voice_provider: provider,
        voice_id: voiceId,
        voice_display_name: chosenVoice?.display_name || voiceId,
        speaking_rate: speed,
        pitch_adjustment: pitch,
        speaking_style: deliveryStyle,
        audio_processing: { trim_silence: true, normalize: true, room_ambience: roomAmbience },
        sample_preview_text: sampleText,
      });
      setProfiles((prev) => prev.map((p) => (p.persona_id === selectedId ? data.profile : p)));
      toast(`Saved voice assignment for ${activeProfile?.persona_name}!`, "success");
    } catch (e) {
      toast("Save failed: " + (e?.response?.data?.detail || e.message), "error");
    } finally {
      setBusy(false);
    }
  };

  const restoreDefault = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/tts/profiles/${selectedId}/reset`);
      setProfiles((prev) => prev.map((p) => (p.persona_id === selectedId ? data.profile : p)));
      toast(`Restored default voice for ${activeProfile?.persona_name}`, "success");
    } catch (e) {
      toast("Restore failed: " + (e?.response?.data?.detail || e.message), "error");
    } finally {
      setBusy(false);
    }
  };

  const installModel = async (target) => {
    try {
      const { data } = await api.post("/tts/models/install", { target });
      setInstallJob(data.job);
      toast(`Started ${target} model download...`, "success");
    } catch (e) {
      toast("Install error: " + (e?.response?.data?.detail || e.message), "error");
    }
  };

  const providers = health?.providers || {};

  return (
    <div className="workspace" style={{ gridTemplateColumns: "1fr" }} data-testid="voice-studio-page">
      <div className="panel" style={{ maxWidth: 1260, margin: "0 auto", width: "100%" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2>🎙️ Da RoastBox Voice Studio</h2>
            <p className="text-muted" style={{ marginBottom: 0 }}>
              40 distinct character voice profiles · Free Local AI (Kokoro-82M / Piper) + ElevenLabs Premium preservation
            </p>
          </div>
          {playingLabel && (
            <button className="btn-secondary" onClick={stopPlayback} data-testid="voice-studio-stop-btn">
              ⏹ Stop ({playingLabel})
            </button>
          )}
        </div>

        {/* Provider Health & Installer */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginTop: 14 }}>
          {["kokoro", "piper", "elevenlabs", "edge_tts", "browser_speech"].map((key) => {
            const p = providers[key];
            if (!p) return null;
            return (
              <div key={key} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "10px 12px", background: "rgba(255,255,255,0.02)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                  <strong style={{ fontSize: 13 }}>{p.display_name}</strong>
                  <span style={{ fontSize: 11, color: STATUS_COLORS[p.status] || "#a1a1aa", fontWeight: 600 }}>
                    {p.is_free ? "FREE" : "PREMIUM"} · {String(p.status || "").replace(/_/g, " ")}
                  </span>
                </div>
                <div className="text-muted" style={{ fontSize: 11, marginTop: 4 }}>{p.detail}</div>
              </div>
            );
          })}
        </div>

        {!health?.free_local_ready && (
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, marginTop: 12, padding: 12, borderRadius: 10, border: "1px solid rgba(251,191,36,0.35)", background: "rgba(251,191,36,0.06)" }}>
            <div style={{ flex: 1, minWidth: 240, fontSize: 13 }}>
              <strong>Free Local Neural Models:</strong>{" "}
              {installJob?.status === "running"
                ? `${installJob.message} (${installJob.progress}%)`
                : installJob?.status === "failed"
                  ? `Install failed: ${installJob.error} (browser speech fallback remains active)`
                  : "Download Kokoro-82M (~337 MB, Apache-2.0) or Piper (~60 MB, MIT) once for offline CPU voice synthesis."}
            </div>
            <button className="btn-primary" onClick={() => installModel("kokoro")} disabled={installJob?.status === "running"} data-testid="install-kokoro-btn">
              {installJob?.status === "running" ? `Installing ${installJob.progress}%` : "Install Kokoro-82M"}
            </button>
            <button className="btn-secondary" onClick={() => installModel("piper")} disabled={installJob?.status === "running"} data-testid="install-piper-btn">
              Install Piper Fallback
            </button>
          </div>
        )}

        <div className="divider" />

        {/* Search & Filters */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(145px, 1fr))", gap: 8 }}>
          <input className="input" placeholder="Search 40 personas..." value={search} onChange={(e) => setSearch(e.target.value)} data-testid="voice-search-input" />
          <select className="input" value={tierFilter} onChange={(e) => setTierFilter(e.target.value)}>
            <option value="all">All Tiers (40)</option>
            <option value="free">Free Personas</option>
            <option value="premium">Premium Personas</option>
          </select>
          <select className="input" value={genderFilter} onChange={(e) => setGenderFilter(e.target.value)}>
            <option value="all">All Genders</option>
            <option value="male">Male Voices</option>
            <option value="female">Female Voices</option>
            <option value="other">Other</option>
          </select>
          <select className="input" value={accentFilter} onChange={(e) => setAccentFilter(e.target.value)}>
            <option value="all">All Accents</option>
            <option value="American">American</option>
            <option value="British">British</option>
          </select>
          <select className="input" value={ageFilter} onChange={(e) => setAgeFilter(e.target.value)}>
            <option value="all">All Ages</option>
            <option value="young_adult">Younger</option>
            <option value="adult">Adult</option>
            <option value="mature">Mature</option>
            <option value="older">Older</option>
          </select>
          <select className="input" value={depthFilter} onChange={(e) => setDepthFilter(e.target.value)}>
            <option value="all">All Depths</option>
            <option value="very_deep">Very Deep</option>
            <option value="deep">Deep</option>
            <option value="medium">Medium</option>
            <option value="bright">Higher / Bright</option>
          </select>
          <select className="input" value={speedFilter} onChange={(e) => setSpeedFilter(e.target.value)}>
            <option value="all">All Speeds</option>
            <option value="fast">Fast Speakers</option>
            <option value="normal">Balanced Pace</option>
            <option value="slow">Slow Speakers</option>
          </select>
          <select className="input" value={styleFilter} onChange={(e) => setStyleFilter(e.target.value)}>
            <option value="all">All Styles</option>
            <option value="comedic">Comedic Delivery</option>
            <option value="dramatic">Dramatic Delivery</option>
          </select>
        </div>

        {/* Two-column Workspace: 40 Personas List + Active Voice Inspector */}
        <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 340px) 1fr", gap: 18, marginTop: 16 }}>
          <div style={{ maxHeight: 620, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, paddingRight: 4 }} data-testid="voice-persona-list">
            {filteredProfiles.map((p) => {
              const active = p.persona_id === selectedId;
              const meta = personasById[p.persona_id] || {};
              return (
                <button
                  key={p.persona_id}
                  type="button"
                  onClick={() => setSelectedId(p.persona_id)}
                  data-testid={`voice-persona-${p.persona_id}`}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, textAlign: "left",
                    padding: "9px 10px", borderRadius: 10, cursor: "pointer",
                    border: active ? "1px solid #c084fc" : "1px solid var(--border)",
                    background: active ? "rgba(192,132,252,0.12)" : "rgba(255,255,255,0.02)",
                    color: "var(--text)",
                  }}
                >
                  {meta.image && <img src={`/${meta.image}`} alt={p.persona_name} style={{ width: 38, height: 38, borderRadius: 8, objectFit: "cover" }} />}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>{p.persona_name}</div>
                    <div className="text-muted" style={{ fontSize: 11, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {p.voice_display_name} · {p.accent}
                    </div>
                  </div>
                  <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 99, background: p.tier === "premium" ? "rgba(245,158,11,0.2)" : "rgba(74,222,128,0.15)", color: p.tier === "premium" ? "#fbbf24" : "#4ade80" }}>
                    {p.tier === "premium" ? "PRO" : "FREE"}
                  </span>
                </button>
              );
            })}
          </div>

          {activeProfile && (
            <div style={{ border: "1px solid var(--border)", borderRadius: 14, padding: 16, background: "rgba(255,255,255,0.02)" }} data-testid="voice-profile-editor">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10 }}>
                <div>
                  <h3 style={{ margin: 0 }}>{activeProfile.persona_name}</h3>
                  <div className="text-muted" style={{ fontSize: 13 }}>{activeProfile.delivery_personality}</div>
                  <div style={{ fontSize: 12, marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <span className="badge">{activeProfile.native_voice_identity ? "Native Neural Identity" : "Customized Profile Tuning"}</span>
                    <span className="badge">{activeProfile.gender_presentation} · {activeProfile.vocal_age} · {activeProfile.accent}</span>
                    <span className="badge">Status: {activeProfile.assignment_status}</span>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn-secondary" onClick={() => previewVoice(null, null, activeProfile.persona_name)} disabled={busy} data-testid="preview-current-voice-btn">
                    🔊 Listen
                  </button>
                  <button className="btn-secondary" onClick={generateSampleRoast} disabled={busy} data-testid="generate-sample-roast-btn">
                    🔥 Sample Roast
                  </button>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 14 }}>
                <div>
                  <label className="label">Voice Provider</label>
                  <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)} data-testid="voice-provider-select">
                    <option value="free_local">Free Local AI (Kokoro-82M → Piper)</option>
                    <option value="kokoro">Kokoro-82M (Free Local)</option>
                    <option value="piper">Piper TTS (Free Lightweight)</option>
                    <option value="edge_tts">Edge-TTS (Free Online Fallback)</option>
                    <option value="elevenlabs">ElevenLabs (Premium — requires key)</option>
                  </select>
                </div>
                <div>
                  <label className="label">Compatible Voice ({filteredVoices.length})</label>
                  <select className="input" value={voiceId} onChange={(e) => setVoiceId(e.target.value)} data-testid="voice-id-select">
                    {filteredVoices.map((v) => (
                      <option key={`${v.provider}:${v.voice_id}`} value={v.voice_id}>
                        [{v.provider.toUpperCase()} · {v.is_free ? "FREE" : "PRO"}] {v.display_name} ({v.accent}, {v.gender})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginTop: 12 }}>
                <div>
                  <label className="label">Speed ({speed.toFixed(2)}x)</label>
                  <input type="range" min="0.80" max="1.30" step="0.02" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} style={{ width: "100%" }} data-testid="voice-speed-slider" />
                </div>
                <div>
                  <label className="label">Pitch ({pitch.toFixed(2)}x)</label>
                  <input type="range" min="0.85" max="1.15" step="0.01" value={pitch} onChange={(e) => setPitch(Number(e.target.value))} style={{ width: "100%" }} data-testid="voice-pitch-slider" />
                </div>
                <div>
                  <label className="label">Delivery Style</label>
                  <select className="input" value={deliveryStyle} onChange={(e) => setDeliveryStyle(e.target.value)} data-testid="voice-delivery-select">
                    {deliveryProfiles.map((d) => (
                      <option key={d.id} value={d.id}>{d.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 13 }}>
                <input type="checkbox" checked={roomAmbience} onChange={(e) => setRoomAmbience(e.target.checked)} />
                Subtle Comedy Club Room Ambience (light FFmpeg studio warmth)
              </label>

              <label className="label" style={{ marginTop: 12 }}>Sample Preview Text (used for preview &amp; side-by-side comparison)</label>
              <textarea className="input" rows={2} value={sampleText} onChange={(e) => setSampleText(e.target.value)} data-testid="voice-sample-text" />

              <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12 }}>
                <button className="btn-primary" onClick={saveAssignment} disabled={busy} data-testid="save-voice-assignment-btn">
                  💾 Save Voice Assignment
                </button>
                <button className="btn-secondary" onClick={restoreDefault} disabled={busy} data-testid="restore-voice-default-btn">
                  ↩ Restore Default
                </button>
              </div>

              <div className="divider" />
              <h4 style={{ margin: "0 0 8px" }}>⚖️ Compare Two Voices (Identical Text)</h4>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, alignItems: "center" }}>
                <select className="input" value={compareVoiceA} onChange={(e) => setCompareVoiceA(e.target.value)}>
                  {voices.map((v) => <option key={`a:${v.provider}:${v.voice_id}`} value={v.voice_id}>A: {v.display_name}</option>)}
                </select>
                <select className="input" value={compareVoiceB} onChange={(e) => setCompareVoiceB(e.target.value)}>
                  {voices.map((v) => <option key={`b:${v.provider}:${v.voice_id}`} value={v.voice_id}>B: {v.display_name}</option>)}
                </select>
                <button className="btn-secondary" onClick={runCompare} disabled={busy} data-testid="compare-voices-btn">Compare A vs B</button>
              </div>
              {compareResults.length > 0 && (
                <div style={{ display: "flex", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
                  {compareResults.map((c, idx) => (
                    <button
                      key={idx}
                      type="button"
                      className="btn-secondary"
                      disabled={!c.ok}
                      onClick={() => playGeneratedResult({ ...c, text: sampleText }, c.label)}
                    >
                      {c.ok ? `▶ ${c.label} (${c.provider})` : `✗ ${c.label}: ${c.error}`}
                    </button>
                  ))}
                </div>
              )}

              {provider === "elevenlabs" && !user?.has_byok_elevenlabs && !providers.elevenlabs?.operational && (
                <p className="text-muted" style={{ fontSize: 12, marginTop: 10 }}>
                  ElevenLabs key not set in Settings — Free Local voices remain ready at zero cost.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
