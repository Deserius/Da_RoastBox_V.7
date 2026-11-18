import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";
import { useToast } from "@/lib/ToastContext";

function VerificationBadge({ result }) {
  if (!result) return null;
  const color = result.ok ? "#4ade80" : "#f87171";
  const prefix = result.ok ? "✓" : "✗";
  return (
    <div style={{ fontSize: 12, color, marginTop: 4 }} role="status">
      {prefix} {result.message}
    </div>
  );
}

export default function SettingsPage() {
  const { user, refresh } = useAuth();
  const { toast } = useToast();
  const [openaiKey, setOpenaiKey] = useState("");
  const [openrouterKey, setOpenrouterKey] = useState("");
  const [elevenKey, setElevenKey] = useState("");
  const [emergentKey, setEmergentKey] = useState("");
  const [stripeApiKey, setStripeApiKey] = useState("");
  const [stripeWebhookSecret, setStripeWebhookSecret] = useState("");
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleClientSecret, setGoogleClientSecret] = useState("");
  const [verifyResults, setVerifyResults] = useState({});
  const [busy, setBusy] = useState(false);
  const [services, setServices] = useState(null);
  const [servicesError, setServicesError] = useState("");

  const loadDiagnostics = () => {
    api.get("/diagnostics").then(({ data }) => {
      setServices(data.config || {});
    }).catch(() => {
      setServicesError("Could not load service configuration. Check the app connection.");
    });
  };

  useEffect(() => {
    let active = true;
    api.get("/diagnostics").then(({ data }) => {
      if (active) setServices(data.config || {});
    }).catch(() => {
      if (active) setServicesError("Could not load service configuration. Check the app connection.");
    });
    return () => { active = false; };
  }, []);

  const aiStatus = (user?.has_byok_openai || user?.has_byok_openrouter)
    ? "Personal AI key active"
    : (services?.openrouter_hosted_key || services?.openai_hosted_key || services?.emergent_llm_key)
      ? `Hosted ${services?.roast_writer_profile || "free"} writer configured (${services?.roast_writer_model || "auto"})`
      : user?.is_preview ? "Add your own OpenRouter or OpenAI key below" : "Not configured";
  const elevenStatus = user?.has_byok_elevenlabs
    ? "Personal ElevenLabs key active"
    : services?.elevenlabs_hosted_key ? "Hosted ElevenLabs key configured" : "Optional; OpenAI / Browser preview voices active";
  const paymentStatus = services?.test_payments_enabled
    ? "Stripe Test Mode enabled (test purchases active)"
    : user?.is_preview ? "Purchases disabled in preview"
    : services?.stripe_api_key && services?.stripe_webhook_secret ? "Stripe configured" : "Stripe key and/or webhook secret missing";

  const payload = () => ({
    openai_key: openaiKey || undefined,
    openrouter_key: openrouterKey || undefined,
    elevenlabs_key: elevenKey || undefined,
    emergent_llm_key: emergentKey || undefined,
    stripe_api_key: stripeApiKey || undefined,
    stripe_webhook_secret: stripeWebhookSecret || undefined,
    google_client_id: googleClientId || undefined,
    google_client_secret: googleClientSecret || undefined,
  });

  const checkOnly = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/voice-settings/verify", { ...payload(), activate: false });
      setVerifyResults(data.results || {});
      toast("All entered keys passed verification!", "success");
    } catch (e) {
      const res = e?.response?.data;
      if (res?.results) setVerifyResults(res.results);
      toast(res?.detail || "Verification failed: " + e.message, "error");
    } finally { setBusy(false); }
  };

  const verifyAndActivate = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/voice-settings/verify-and-save", { ...payload(), activate: true });
      setVerifyResults(data.results || {});
      await refresh();
      loadDiagnostics();
      setOpenaiKey(""); setOpenrouterKey(""); setElevenKey("");
      setEmergentKey(""); setStripeApiKey(""); setStripeWebhookSecret("");
      setGoogleClientId(""); setGoogleClientSecret("");
      toast("All entered keys verified and activated!", "success");
    } catch (e) {
      const res = e?.response?.data;
      if (res?.results) setVerifyResults(res.results);
      toast(res?.detail || "Key check failed — nothing was activated.", "error");
    } finally { setBusy(false); }
  };

  const saveQuickByok = async () => {
    setBusy(true);
    try {
      await api.post("/voice-settings/keys", {
        openai_key: openaiKey || undefined,
        openrouter_key: openrouterKey || undefined,
        elevenlabs_key: elevenKey || undefined,
      });
      await refresh();
      setOpenaiKey(""); setOpenrouterKey(""); setElevenKey("");
      toast("Keys saved (encrypted at rest)", "success");
    } catch (e) {
      toast("Failed: " + (e?.response?.data?.detail || e.message), "error");
    } finally { setBusy(false); }
  };

  const clearAll = async () => {
    setBusy(true);
    try {
      await api.delete("/voice-settings/keys");
      setVerifyResults({});
      await refresh();
      toast("BYOK keys cleared. Using app defaults.", "success");
    } catch (e) {
      toast("Failed: " + e.message, "error");
    } finally { setBusy(false); }
  };

  return (
    <div className="workspace" style={{ gridTemplateColumns: "1fr" }} data-testid="settings-page">
      <div className="panel" style={{ maxWidth: 760, margin: "0 auto", width: "100%" }}>
        <h2>Account</h2>
        <p>Signed in as <strong>{user?.email}</strong></p>
        <p>Current credits: <strong>{user?.credits ?? 0}</strong></p>

        <div className="divider" />
        <h2>Service Configuration</h2>
        {servicesError && <p role="alert" className="text-muted">{servicesError}</p>}
        {!services && !servicesError && <p className="text-muted">Checking service settings…</p>}
        {services && <div data-testid="service-configuration" className="text-muted" style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div><strong>AI writing &amp; roast generator:</strong> {aiStatus}</div>
          <div><strong>ElevenLabs voices:</strong> {elevenStatus}</div>
          <div><strong>Stripe checkout:</strong> {paymentStatus}</div>
          <div><strong>Google OAuth:</strong> {services.google_oauth_configured ? "Configured" : "Not configured"}</div>
          <div><strong>Media storage:</strong> {services.storage_backend === "local" ? "Local workspace" : services.storage_backend}</div>
          {services.preview_sandbox_fallback && (
            <div style={{ color: "var(--accent-alt)" }}>
              <strong>Workspace preview fallback:</strong> Active (browser speech &amp; local script fallback when outbound AI hosts are firewalled)
            </div>
          )}
        </div>}

        <div className="divider" />
        <h2>API Keys &amp; Pre-Activation Check</h2>
        <p className="text-muted" style={{ fontSize: 13 }}>
          Enter any API keys below. <strong>Verify &amp; Activate</strong> checks key format and tests live provider connectivity before saving — invalid keys are rejected and never activated.
        </p>

        <label className="label" style={{ marginTop: 12 }}>
          OpenRouter API Key (Free &amp; Premium Models) {(user?.has_byok_openrouter || services?.openrouter_hosted_key) && <span className="text-accent">(active)</span>}
        </label>
        <input
          className="input"
          placeholder="sk-or-v1-..."
          type="password"
          value={openrouterKey}
          onChange={(e) => setOpenrouterKey(e.target.value)}
          data-testid="openrouter-key-input"
        />
        <VerificationBadge result={verifyResults.openrouter_key} />

        <label className="label" style={{ marginTop: 12 }}>
          OpenAI API Key (Writer, Vision &amp; Voices) {(user?.has_byok_openai || services?.openai_hosted_key) && <span className="text-accent">(active)</span>}
        </label>
        <input
          className="input"
          placeholder="sk-..."
          type="password"
          value={openaiKey}
          onChange={(e) => setOpenaiKey(e.target.value)}
          data-testid="openai-key-input"
        />
        <VerificationBadge result={verifyResults.openai_key} />

        <label className="label" style={{ marginTop: 12 }}>
          ElevenLabs API Key (Premium Persona Voices) {(user?.has_byok_elevenlabs || services?.elevenlabs_hosted_key) && <span className="text-accent">(active)</span>}
        </label>
        <input
          className="input"
          placeholder="sk_... or xi-..."
          type="password"
          value={elevenKey}
          onChange={(e) => setElevenKey(e.target.value)}
          data-testid="elevenlabs-key-input"
        />
        <VerificationBadge result={verifyResults.elevenlabs_key} />

        {services?.preview_sandbox_fallback && (
          <>
            <div className="divider" />
            <h3 style={{ fontSize: 16, marginBottom: 4 }}>App, Payment &amp; OAuth Keys (Workspace Mode)</h3>
            <p className="text-muted" style={{ fontSize: 12 }}>
              In workspace preview mode you can also check and activate Stripe test keys, Emergent LLM, and Google OAuth credentials here.
            </p>

            <label className="label" style={{ marginTop: 10 }}>
              Stripe Test Secret Key {services?.stripe_api_key && <span className="text-accent">(configured)</span>}
            </label>
            <input
              className="input"
              placeholder="sk_test_..."
              type="password"
              value={stripeApiKey}
              onChange={(e) => setStripeApiKey(e.target.value)}
              data-testid="stripe-key-input"
            />
            <VerificationBadge result={verifyResults.stripe_api_key} />

            <label className="label" style={{ marginTop: 10 }}>
              Stripe Webhook Secret {services?.stripe_webhook_secret && <span className="text-accent">(configured)</span>}
            </label>
            <input
              className="input"
              placeholder="whsec_..."
              type="password"
              value={stripeWebhookSecret}
              onChange={(e) => setStripeWebhookSecret(e.target.value)}
              data-testid="stripe-webhook-input"
            />
            <VerificationBadge result={verifyResults.stripe_webhook_secret} />

            <label className="label" style={{ marginTop: 10 }}>
              Emergent LLM Key {services?.emergent_llm_key && <span className="text-accent">(configured)</span>}
            </label>
            <input
              className="input"
              placeholder="sk-emergent-..."
              type="password"
              value={emergentKey}
              onChange={(e) => setEmergentKey(e.target.value)}
              data-testid="emergent-key-input"
            />
            <VerificationBadge result={verifyResults.emergent_llm_key} />

            <label className="label" style={{ marginTop: 10 }}>
              Google OAuth Client ID {services?.google_oauth_configured && <span className="text-accent">(configured)</span>}
            </label>
            <input
              className="input"
              placeholder="123456.apps.googleusercontent.com"
              type="text"
              value={googleClientId}
              onChange={(e) => setGoogleClientId(e.target.value)}
              data-testid="google-client-id-input"
            />
            <VerificationBadge result={verifyResults.google_client_id} />

            <label className="label" style={{ marginTop: 10 }}>
              Google OAuth Client Secret
            </label>
            <input
              className="input"
              placeholder="GOCSPX-..."
              type="password"
              value={googleClientSecret}
              onChange={(e) => setGoogleClientSecret(e.target.value)}
              data-testid="google-client-secret-input"
            />
            <VerificationBadge result={verifyResults.google_client_secret} />
          </>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 16 }}>
          <button className="btn-primary" onClick={verifyAndActivate} disabled={busy} data-testid="save-keys-btn">
            Verify &amp; Activate Keys
          </button>
          <button className="btn-secondary" onClick={checkOnly} disabled={busy} data-testid="check-keys-btn">
            Check Keys Only
          </button>
          <button className="btn-secondary" onClick={saveQuickByok} disabled={busy} data-testid="quick-save-keys-btn">
            Quick Save BYOK
          </button>
          <button className="btn-secondary" onClick={clearAll} disabled={busy} data-testid="clear-keys-btn">
            Clear All
          </button>
        </div>

        <div className="divider" />
        <h2>About Voices</h2>
        <p className="text-muted" style={{ fontSize: 13 }}>
          When ElevenLabs key is set, each persona uses a unique, distinctly-mapped voice.
          Without it, Da RoastBox uses OpenAI TTS or browser speech synthesis in workspace preview mode.
        </p>
      </div>
    </div>
  );
}
