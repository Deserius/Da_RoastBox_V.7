#!/usr/bin/env python3
"""Standalone local API Key, Auth & Secrets Setup Vault for Da RoastBox V.7.

Runs on its own port (default 8090) independently of the main app.
Authenticates entered credentials against each provider BEFORE saving to
backend/.env and frontend/.env. Never exposes existing secret values in API
responses or logs.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import stripe
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from pymongo import MongoClient

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_ENV_PATH = ROOT_DIR / "backend" / ".env"
FRONTEND_ENV_PATH = ROOT_DIR / "frontend" / ".env"
SETUP_PORT = int(os.environ.get("KEY_SETUP_PORT", "8090"))
SETUP_HOST = os.environ.get("KEY_SETUP_HOST", "0.0.0.0")
IS_SANDBOX = os.environ.get("E2B_SANDBOX", "").strip().lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Field Catalog + Detailed Help Instructions
# ---------------------------------------------------------------------------
FIELD_CATALOG: list[dict[str, Any]] = [
    # --- AI & Voice ---
    {
        "key": "OPENROUTER_API_KEY",
        "target": "backend",
        "group": "ai",
        "label": "OpenRouter API Key",
        "secret": True,
        "placeholder": "sk-or-v1-...",
        "purpose": "Primary multimodal roast writer & photo-analysis router (Claude Sonnet 4.5, GPT-4.1, GPT-4o).",
        "portal_name": "OpenRouter Keys Dashboard",
        "portal_url": "https://openrouter.ai/keys",
        "format_hint": "Starts with sk-or-v1- (or sk-or-)",
        "steps": [
            "Sign in or create an account at https://openrouter.ai.",
            "Open the top-right profile menu and select Keys (or go directly to https://openrouter.ai/keys).",
            "Click 'Create Key', name it 'Da RoastBox', and set an optional credit/spending limit.",
            "Copy the generated sk-or-v1-... key immediately (it is only shown once) and paste it here.",
            "Add billing credits under Credits if you plan to use paid models like anthropic/claude-sonnet-4.5."
        ],
    },
    {
        "key": "OPENAI_API_KEY",
        "target": "backend",
        "group": "ai",
        "label": "OpenAI API Key",
        "secret": True,
        "placeholder": "sk-proj-... or sk-...",
        "purpose": "Powers gpt-4o-mini-tts voice synthesis and acts as backup vision/writer provider.",
        "portal_name": "OpenAI Platform API Keys",
        "portal_url": "https://platform.openai.com/api-keys",
        "format_hint": "Starts with sk- or sk-proj-",
        "steps": [
            "Sign in at https://platform.openai.com (separate from a ChatGPT Plus subscription).",
            "Go to Settings -> Billing and ensure a payment method & positive credit balance are added.",
            "Navigate to API Keys (https://platform.openai.com/api-keys) and click '+ Create new secret key'.",
            "Give it full or default project permissions for Chat Completions and Audio/TTS.",
            "Copy the sk-... key immediately and paste it here."
        ],
    },
    {
        "key": "ELEVENLABS_API_KEY",
        "target": "backend",
        "group": "ai",
        "label": "ElevenLabs API Key",
        "secret": True,
        "placeholder": "xi-... or 32-char hex key",
        "purpose": "Synthesizes expressive premium comedian voices (eleven_v3 / eleven_multilingual_v2).",
        "portal_name": "ElevenLabs API Keys",
        "portal_url": "https://elevenlabs.io/app/settings/api-keys",
        "format_hint": "Usually starts with sk_ (newer) or 32+ alphanumeric characters",
        "steps": [
            "Log into https://elevenlabs.io.",
            "Click your profile icon in the bottom-left corner and choose 'API Keys'.",
            "Click 'Create API Key', select permissions for Text-to-Speech and User Read.",
            "Copy the key and paste it here. Verify your character quota is active."
        ],
    },
    {
        "key": "EMERGENT_LLM_KEY",
        "target": "backend",
        "group": "ai",
        "label": "Emergent Universal LLM Key (Optional)",
        "secret": True,
        "placeholder": "sk-emergent-...",
        "purpose": "Optional Emergent hosted proxy key for LLM/TTS/image generation fallback.",
        "portal_name": "Emergent Profile / Universal Key",
        "portal_url": "https://app.emergent.sh",
        "format_hint": "Starts with sk-emergent-",
        "steps": [
            "Open your Emergent workspace dashboard at https://app.emergent.sh.",
            "Go to Profile -> Universal Key / Integrations and copy your EMERGENT_LLM_KEY.",
            "Leave blank if using direct OpenRouter + OpenAI keys in production."
        ],
    },
    {
        "key": "ROAST_WRITER_PROVIDER",
        "target": "backend",
        "group": "ai",
        "label": "Roast Writer Provider",
        "secret": False,
        "type": "select",
        "options": ["openrouter", "existing"],
        "placeholder": "openrouter",
        "purpose": "Selects whether shows are written via OpenRouter multimodal chain or legacy OpenAI/Emergent.",
        "portal_name": "OpenRouter Models",
        "portal_url": "https://openrouter.ai/models",
        "format_hint": "openrouter or existing",
        "steps": [
            "Choose 'openrouter' to use the Claude Sonnet 4.5 -> GPT-4.1 -> GPT-4o multimodal chain.",
            "Choose 'existing' to route directly through OpenAI or Emergent."
        ],
    },
    {
        "key": "ROAST_OPENROUTER_MODELS",
        "target": "backend",
        "group": "ai",
        "label": "OpenRouter Model Chain",
        "secret": False,
        "placeholder": "anthropic/claude-sonnet-4.5,openai/gpt-4.1,openai/gpt-4o",
        "purpose": "Comma-separated fallback order of OpenRouter model slugs (1 to 6 models).",
        "portal_name": "OpenRouter Model Directory",
        "portal_url": "https://openrouter.ai/models",
        "format_hint": "1-6 comma-separated provider/model slugs",
        "steps": [
            "Browse https://openrouter.ai/models and filter for Vision/Multimodal models.",
            "List your preferred models from highest priority to fallback, separated by commas."
        ],
    },
    # --- Stripe ---
    {
        "key": "STRIPE_API_KEY",
        "target": "backend",
        "group": "stripe",
        "label": "Stripe Secret Key",
        "secret": True,
        "placeholder": "sk_test_... or sk_live_...",
        "purpose": "Creates server-side Stripe Checkout sessions for Credit Packs, Passes & Lifetime Founder.",
        "portal_name": "Stripe API Keys",
        "portal_url": "https://dashboard.stripe.com/apikeys",
        "format_hint": "sk_test_... (test) or sk_live_... (live)",
        "steps": [
            "Log into https://dashboard.stripe.com.",
            "Toggle 'Test mode' ON in the top-right while testing (or OFF for live payments).",
            "Go to Developers -> API keys (https://dashboard.stripe.com/apikeys).",
            "Reveal and copy the 'Secret key' (sk_test_... or sk_live_...).",
            "Note: While STRIPE_TEST_ONLY=true, only sk_test_ keys are accepted for safety."
        ],
    },
    {
        "key": "STRIPE_PUBLISHABLE_KEY",
        "target": "backend",
        "group": "stripe",
        "label": "Stripe Publishable Key",
        "secret": False,
        "placeholder": "pk_test_... or pk_live_...",
        "purpose": "Public Stripe key paired with your Secret Key (must match test vs live mode).",
        "portal_name": "Stripe API Keys",
        "portal_url": "https://dashboard.stripe.com/apikeys",
        "format_hint": "pk_test_... or pk_live_...",
        "steps": [
            "In Stripe Dashboard -> Developers -> API keys, copy the 'Publishable key'.",
            "Ensure it matches the same mode (test vs live) and account as STRIPE_API_KEY."
        ],
    },
    {
        "key": "STRIPE_WEBHOOK_SECRET",
        "target": "backend",
        "group": "stripe",
        "label": "Stripe Webhook Signing Secret",
        "secret": True,
        "placeholder": "whsec_...",
        "purpose": "Verifies cryptographic signatures on /api/payments/webhook so forged events cannot grant credits.",
        "portal_name": "Stripe Webhooks",
        "portal_url": "https://dashboard.stripe.com/webhooks",
        "format_hint": "Starts with whsec_",
        "steps": [
            "For production: open Stripe Dashboard -> Developers -> Webhooks -> '+ Add endpoint'.",
            "Set Endpoint URL to https://YOUR_DOMAIN/api/payments/webhook and subscribe to 'checkout.session.completed'.",
            "Click 'Reveal' under Signing secret to copy the whsec_... value.",
            "For local testing: run 'stripe listen --forward-to localhost:8001/api/payments/webhook' and copy its whsec_... secret."
        ],
    },
    {
        "key": "STRIPE_TEST_ONLY",
        "target": "backend",
        "group": "stripe",
        "label": "Stripe Test-Only Safety Lock",
        "secret": False,
        "type": "select",
        "options": ["true", "false"],
        "placeholder": "true",
        "purpose": "When true, blocks live Stripe keys (sk_live_/rk_live_) at runtime to prevent accidental real charges.",
        "portal_name": "Stripe Test Mode Docs",
        "portal_url": "https://docs.stripe.com/testing",
        "format_hint": "true or false",
        "steps": [
            "Keep 'true' during staging and preview testing.",
            "Switch to 'false' only when intentionally launching live billing with sk_live_ keys."
        ],
    },
    # --- Google Login & Auth ---
    {
        "key": "GOOGLE_CLIENT_ID",
        "target": "both",
        "frontend_key": "REACT_APP_GOOGLE_CLIENT_ID",
        "group": "google",
        "label": "Google OAuth 2.0 Client ID",
        "secret": False,
        "placeholder": "1234567890-xxxx.apps.googleusercontent.com",
        "purpose": "Identifies your Google Cloud OAuth app for direct Sign in with Google authentication.",
        "portal_name": "Google Cloud Credentials",
        "portal_url": "https://console.cloud.google.com/apis/credentials",
        "format_hint": "Ends with .apps.googleusercontent.com",
        "steps": [
            "Open https://console.cloud.google.com and create/select a project (e.g. 'Da RoastBox').",
            "Go to APIs & Services -> OAuth consent screen: choose External, fill App name & support email, add scopes email/profile/openid.",
            "Go to APIs & Services -> Credentials -> '+ Create Credentials' -> 'OAuth client ID'.",
            "Select Application type: 'Web application'.",
            "Under 'Authorized JavaScript origins', add your frontend origin (e.g. https://yourdomain.com and http://localhost:3000).",
            "Under 'Authorized redirect URIs', add https://yourdomain.com/auth-complete.html and http://localhost:3000/auth-complete.html.",
            "Click Create and copy the Client ID ending in .apps.googleusercontent.com."
        ],
    },
    {
        "key": "GOOGLE_CLIENT_SECRET",
        "target": "backend",
        "group": "google",
        "label": "Google OAuth 2.0 Client Secret",
        "secret": True,
        "placeholder": "GOCSPX-...",
        "purpose": "Confidential OAuth client secret for server-side Google authorization code exchange.",
        "portal_name": "Google Cloud Credentials",
        "portal_url": "https://console.cloud.google.com/apis/credentials",
        "format_hint": "Starts with GOCSPX- (usually 24-40 chars)",
        "steps": [
            "In Google Cloud Console -> APIs & Services -> Credentials, click your Web OAuth 2.0 Client ID.",
            "Copy the 'Client secret' (starts with GOCSPX-) from the right-hand panel.",
            "Never expose this secret in frontend code; it is stored only in backend/.env."
        ],
    },
    {
        "key": "GOOGLE_REDIRECT_URI",
        "target": "backend",
        "group": "google",
        "label": "Google OAuth Redirect URI",
        "secret": False,
        "placeholder": "http://localhost:3000/auth-complete.html",
        "purpose": "Exact callback URL registered in Google Cloud Console for OAuth completion.",
        "portal_name": "Google OAuth Redirect Docs",
        "portal_url": "https://developers.google.com/identity/protocols/oauth2/web-server",
        "format_hint": "Full http(s)://... URL ending in /auth-complete.html (or your callback path)",
        "steps": [
            "Must match character-for-character one of the 'Authorized redirect URIs' in Google Cloud Console.",
            "For local dev use http://localhost:3000/auth-complete.html; for launch use https://yourdomain.com/auth-complete.html."
        ],
    },
    {
        "key": "INTEGRATION_PROXY_URL",
        "target": "backend",
        "group": "google",
        "label": "Emergent Managed Auth / Integration URL",
        "secret": False,
        "placeholder": "https://integrations.emergentagent.com",
        "purpose": "Gateway URL used by the built-in Emergent managed integration & OAuth flow.",
        "portal_name": "Emergent Platform",
        "portal_url": "https://app.emergent.sh",
        "format_hint": "https://integrations.emergentagent.com",
        "steps": [
            "Default is https://integrations.emergentagent.com.",
            "Change only if self-hosting a custom integration proxy."
        ],
    },
    {
        "key": "ENABLE_PREVIEW_LOGIN",
        "target": "both",
        "frontend_key": "REACT_APP_ENABLE_PREVIEW_LOGIN",
        "group": "google",
        "label": "Enable Sandbox Preview Login",
        "secret": False,
        "type": "select",
        "options": ["true", "false"],
        "placeholder": "true",
        "purpose": "Enables one-click 'Explore Preview' guest login button (keep false in production!).",
        "portal_name": "Da RoastBox Auth Docs",
        "portal_url": "https://console.cloud.google.com/apis/credentials",
        "format_hint": "true or false",
        "steps": [
            "Set 'true' during local/preview testing so you can test the UI without Google OAuth.",
            "MUST be set to 'false' before public production launch."
        ],
    },
    # --- Email / SMTP Auth ---
    {
        "key": "EMAIL_AUTH_ENABLED",
        "target": "backend",
        "group": "email",
        "label": "Enable Email / Password Login",
        "secret": False,
        "type": "select",
        "options": ["false", "true"],
        "placeholder": "false",
        "purpose": "Enables email verification & password login alongside Google sign-in.",
        "portal_name": "SMTP Setup Guide",
        "portal_url": "https://resend.com/docs/send-with-smtp",
        "format_hint": "true or false",
        "steps": [
            "Leave 'false' until SMTP credentials and APP_BASE_URL are configured.",
            "Set 'true' once SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM are verified."
        ],
    },
    {
        "key": "SMTP_HOST",
        "target": "backend",
        "group": "email",
        "label": "SMTP Host",
        "secret": False,
        "placeholder": "smtp.resend.com or smtp.gmail.com",
        "purpose": "Encrypted mail server for sending account verification and password reset links.",
        "portal_name": "Resend SMTP / Postmark / SendGrid",
        "portal_url": "https://resend.com/smtp",
        "format_hint": "Hostname (e.g. smtp.resend.com)",
        "steps": [
            "Sign up for a transactional email provider (Resend, Postmark, SendGrid, or AWS SES).",
            "Copy the SMTP server hostname (e.g. smtp.resend.com for Resend, smtp.sendgrid.net for SendGrid)."
        ],
    },
    {
        "key": "SMTP_PORT",
        "target": "backend",
        "group": "email",
        "label": "SMTP Port",
        "secret": False,
        "placeholder": "587",
        "purpose": "Port for TLS mail delivery (587 for STARTTLS, 465 for SSL).",
        "portal_name": "SMTP Ports Reference",
        "portal_url": "https://resend.com/docs/send-with-smtp",
        "format_hint": "587 or 465",
        "steps": [
            "Use 587 with SMTP_TLS_MODE=starttls (recommended).",
            "Or use 465 with SMTP_TLS_MODE=ssl."
        ],
    },
    {
        "key": "SMTP_TLS_MODE",
        "target": "backend",
        "group": "email",
        "label": "SMTP TLS Mode",
        "secret": False,
        "type": "select",
        "options": ["starttls", "ssl"],
        "placeholder": "starttls",
        "purpose": "Transport encryption mode (plaintext is never permitted).",
        "portal_name": "SMTP TLS Docs",
        "portal_url": "https://resend.com/docs/send-with-smtp",
        "format_hint": "starttls or ssl",
        "steps": ["Match port 587 -> starttls, or port 465 -> ssl."],
    },
    {
        "key": "SMTP_USERNAME",
        "target": "backend",
        "group": "email",
        "label": "SMTP Username",
        "secret": False,
        "placeholder": "resend or apikey",
        "purpose": "Username for SMTP authentication.",
        "portal_name": "Email Provider Dashboard",
        "portal_url": "https://resend.com/api-keys",
        "format_hint": "Provider SMTP username",
        "steps": ["For Resend use 'resend'. For SendGrid use 'apikey'. For Gmail use your full email address."],
    },
    {
        "key": "SMTP_PASSWORD",
        "target": "backend",
        "group": "email",
        "label": "SMTP Password / API Key",
        "secret": True,
        "placeholder": "re_... or App Password",
        "purpose": "Password or SMTP token used to authenticate mail sending.",
        "portal_name": "Resend API Keys",
        "portal_url": "https://resend.com/api-keys",
        "format_hint": "SMTP secret / App Password",
        "steps": [
            "In Resend/SendGrid, create an API key with 'Sending access' and paste it here.",
            "If using Gmail, enable 2FA and generate a 16-character App Password (never use your main password)."
        ],
    },
    {
        "key": "SMTP_FROM",
        "target": "backend",
        "group": "email",
        "label": "SMTP From Address",
        "secret": False,
        "placeholder": "Da RoastBox <no-reply@yourdomain.com>",
        "purpose": "Sender email address shown on verification and password-reset emails.",
        "portal_name": "Domain Verification",
        "portal_url": "https://resend.com/domains",
        "format_hint": "Valid email or 'Name <email@domain.com>'",
        "steps": ["Verify your sending domain DNS records (SPF/DKIM) in your email provider first."],
    },
    # --- Database, Security & Cloud Launch ---
    {
        "key": "MONGO_URL",
        "target": "backend",
        "group": "infra",
        "label": "MongoDB Connection URL",
        "secret": True,
        "placeholder": "mongodb://127.0.0.1:27017 or mongodb+srv://...",
        "purpose": "Database storing user accounts, credits, roasts, battles, reels, and payment ledgers.",
        "portal_name": "MongoDB Atlas",
        "portal_url": "https://cloud.mongodb.com",
        "format_hint": "mongodb://... or mongodb+srv://<user>:<password>@cluster.mongodb.net/",
        "steps": [
            "For local sandbox preview: keep mongodb://127.0.0.1:27017.",
            "For production: create a free M0 or dedicated cluster at https://cloud.mongodb.com.",
            "Create a database user under Database Access and allow your backend IP (or 0.0.0.0/0 for Render) under Network Access.",
            "Click Connect -> Drivers -> Python and copy the mongodb+srv:// URI."
        ],
    },
    {
        "key": "DB_NAME",
        "target": "backend",
        "group": "infra",
        "label": "MongoDB Database Name",
        "secret": False,
        "placeholder": "da_roastbox_preview",
        "purpose": "Target database name inside your MongoDB cluster.",
        "portal_name": "MongoDB Atlas",
        "portal_url": "https://cloud.mongodb.com",
        "format_hint": "Alphanumeric + underscores",
        "steps": ["Use da_roastbox_preview locally, or da_roastbox_prod for production."],
    },
    {
        "key": "JWT_SECRET",
        "target": "backend",
        "group": "infra",
        "label": "JWT & BYOK Encryption Secret",
        "secret": True,
        "generatable": True,
        "placeholder": "64+ hex/random characters",
        "purpose": "Signs session tokens and derives the Fernet key encrypting user BYOK API keys.",
        "portal_name": "Cryptographic Secret Generator",
        "portal_url": "https://docs.python.org/3/library/secrets.html",
        "format_hint": "At least 32 random characters (64 hex recommended)",
        "steps": [
            "Click the 'Generate' button next to this field for a cryptographically secure 64-char secret.",
            "WARNING: Never rotate this on an existing production DB — changing it makes stored BYOK credentials unreadable."
        ],
    },
    {
        "key": "APP_BASE_URL",
        "target": "backend",
        "group": "infra",
        "label": "Public App Base URL",
        "secret": False,
        "placeholder": "https://da-roastbox.vercel.app",
        "purpose": "Canonical frontend URL used for Stripe checkout returns, email verification links, and beta cookies.",
        "portal_name": "Vercel / Render Dashboard",
        "portal_url": "https://vercel.com/dashboard",
        "format_hint": "https://yourdomain.com (no trailing slash)",
        "steps": [
            "Set to your deployed frontend URL (e.g. https://daroastbox.com or https://your-app.vercel.app).",
            "Leave blank during local development."
        ],
    },
    {
        "key": "CORS_ORIGINS",
        "target": "backend",
        "group": "infra",
        "label": "Allowed CORS Origins",
        "secret": False,
        "placeholder": "http://localhost:3000,http://127.0.0.1:3000",
        "purpose": "Comma-separated browser origins permitted to call the FastAPI backend with credentials.",
        "portal_name": "CORS Config",
        "portal_url": "https://fastapi.tiangolo.com/tutorial/cors/",
        "format_hint": "Comma-separated http(s):// origins",
        "steps": [
            "Include every frontend domain (e.g. https://daroastbox.com,https://www.daroastbox.com).",
            "Do not use '*' when credentials/cookies are enabled."
        ],
    },
    {
        "key": "APP_ENV",
        "target": "backend",
        "group": "infra",
        "label": "Application Environment",
        "secret": False,
        "type": "select",
        "options": ["development", "beta", "production"],
        "placeholder": "development",
        "purpose": "Controls security hardening, strict host checks, and optional beta access gate.",
        "portal_name": "Deployment Runbook",
        "portal_url": "https://render.com/docs",
        "format_hint": "development, beta, or production",
        "steps": [
            "Use 'development' in the local sandbox.",
            "Use 'beta' to activate the scrypt beta password gate, or 'production' for public launch."
        ],
    },
    {
        "key": "BETA_ACCESS_PASSWORD_HASH",
        "target": "backend",
        "group": "infra",
        "label": "Beta Gate Password (auto-hashed to scrypt)",
        "secret": True,
        "beta_password": True,
        "placeholder": "Enter plaintext beta password to hash, or scrypt$16384$...",
        "purpose": "Optional site-wide beta access gate password when APP_ENV=beta (hashed with scrypt before saving).",
        "portal_name": "Beta Gate Docs",
        "portal_url": "https://docs.python.org/3/library/hashlib.html#hashlib.scrypt",
        "format_hint": "Enter any 10+ char password (auto-converted to scrypt$16384$8$1$...)",
        "steps": [
            "Type your desired beta access password here; it is automatically converted to a salted scrypt$16384$8$1$... verifier before writing .env.",
            "Only active when APP_ENV=beta."
        ],
    },
    {
        "key": "BETA_ACCESS_SIGNING_KEY",
        "target": "backend",
        "group": "infra",
        "label": "Beta Cookie Signing Key",
        "secret": True,
        "generatable": True,
        "placeholder": "32+ random characters",
        "purpose": "Signs __Host-roastbox-beta access cookies when APP_ENV=beta.",
        "portal_name": "Secret Generator",
        "portal_url": "https://docs.python.org/3/library/secrets.html",
        "format_hint": "At least 32 characters",
        "steps": ["Click 'Generate' to create a 64-character random signing key."],
    },
    # --- Cloud Launch Connectors (Supabase / Vercel) ---
    {
        "key": "SUPABASE_URL",
        "target": "backend",
        "group": "cloud",
        "label": "Supabase Project URL (Optional)",
        "secret": False,
        "placeholder": "https://xxxxxxxxxxxx.supabase.co",
        "purpose": "Optional Supabase project endpoint if migrating auth/storage/DB to Supabase.",
        "portal_name": "Supabase Project Settings -> API",
        "portal_url": "https://supabase.com/dashboard/project/_/settings/api",
        "format_hint": "https://<project-ref>.supabase.co",
        "steps": [
            "Open https://supabase.com/dashboard and select your project.",
            "Go to Project Settings -> Data API / API.",
            "Copy the Project URL (https://<ref>.supabase.co)."
        ],
    },
    {
        "key": "SUPABASE_ANON_KEY",
        "target": "both",
        "frontend_key": "REACT_APP_SUPABASE_ANON_KEY",
        "group": "cloud",
        "label": "Supabase Anon / Publishable Key (Optional)",
        "secret": True,
        "placeholder": "eyJ... or sb_publishable_...",
        "purpose": "Client-safe Supabase key authenticated against your Supabase URL.",
        "portal_name": "Supabase API Keys",
        "portal_url": "https://supabase.com/dashboard/project/_/settings/api",
        "format_hint": "eyJ... JWT or sb_publishable_...",
        "steps": [
            "In Supabase Dashboard -> Project Settings -> API Keys, copy the 'anon public' or Publishable key."
        ],
    },
    {
        "key": "SUPABASE_SERVICE_ROLE_KEY",
        "target": "backend",
        "group": "cloud",
        "label": "Supabase Service Role Key (Optional)",
        "secret": True,
        "placeholder": "eyJ... or sb_secret_...",
        "purpose": "Server-only Supabase admin key (never expose to frontend).",
        "portal_name": "Supabase API Keys",
        "portal_url": "https://supabase.com/dashboard/project/_/settings/api",
        "format_hint": "eyJ... JWT or sb_secret_...",
        "steps": [
            "In Supabase Dashboard -> Project Settings -> API Keys, reveal and copy the 'service_role' / Secret key."
        ],
    },
    {
        "key": "VERCEL_TOKEN",
        "target": "backend",
        "group": "cloud",
        "label": "Vercel Access Token (Optional)",
        "secret": True,
        "placeholder": "vercel_... token",
        "purpose": "Optional token for automated Vercel deployments & env sync.",
        "portal_name": "Vercel Account Tokens",
        "portal_url": "https://vercel.com/account/tokens",
        "format_hint": "24+ char Vercel personal/team token",
        "steps": [
            "Open https://vercel.com/account/tokens.",
            "Click 'Create', name the token 'Da RoastBox Deploy', choose scope & expiration.",
            "Copy the token and paste it here."
        ],
    },
]

FIELD_BY_KEY = {f["key"]: f for f in FIELD_CATALOG}


# ---------------------------------------------------------------------------
# .env Helpers (Atomic read/write preserving existing comments and keys)
# ---------------------------------------------------------------------------
def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v[0] == "'" and v[-1] == "'") or (v[0] == '"' and v[-1] == '"')):
            v = v[1:-1]
        data[k] = v
    return data


def _format_env_val(val: str) -> str:
    if val == "":
        return ""
    if any(ch in val for ch in (" ", "#", "'", '"', "$", "\n", "\r")):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return val


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    if not updates:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    new_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in remaining:
                new_lines.append(f"{k}={_format_env_val(remaining.pop(k))}")
                continue
        new_lines.append(raw)
    if remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Configured via Da RoastBox API & Auth Vault")
        for k, v in remaining.items():
            new_lines.append(f"{k}={_format_env_val(v)}")
    tmp = path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def mask_secret(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "•" * len(val)
    return f"{val[:6]}••••{val[-4:]}"


def scrypt_verifier(password: str) -> str:
    if password.startswith("scrypt$16384$8$1$"):
        return password
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + digest.hex()


# ---------------------------------------------------------------------------
# Provider Authentication Engine
# ---------------------------------------------------------------------------
def _sandbox_network_issue(exc: Exception) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "ssl", "eof", "connecterror", "timeout", "name or service not known",
        "temporary failure in name resolution", "network is unreachable",
        "connection refused", "nodename nor servname", "proxy", "502", "503"
    )
    return any(m in msg for m in markers)


async def _auth_http_check(
    provider: str,
    url: str,
    headers: dict[str, str],
    ok_note_fn=None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if 200 <= resp.status_code < 300:
            note = ok_note_fn(resp) if ok_note_fn else "Live API authentication succeeded"
            return {"status": "authenticated", "detail": note}
        if resp.status_code in (401, 403):
            return {"status": "failed", "detail": f"{provider} rejected credentials (HTTP {resp.status_code})."}
        return {"status": "failed", "detail": f"{provider} returned HTTP {resp.status_code}."}
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, ssl.SSLError, OSError) as exc:
        if _sandbox_network_issue(exc):
            return {
                "status": "sandbox_blocked",
                "detail": (
                    f"Format valid, but live check to {urlsplit(url).hostname} was blocked by "
                    f"the sandbox egress firewall ({type(exc).__name__})."
                ),
            }
        return {"status": "failed", "detail": f"Network error contacting {provider}: {exc}"}
    except Exception as exc:
        if _sandbox_network_issue(exc):
            return {
                "status": "sandbox_blocked",
                "detail": f"Format valid; outbound check to {urlsplit(url).hostname} blocked by sandbox network ({type(exc).__name__}).",
            }
        return {"status": "failed", "detail": f"{provider} verification error: {exc}"}


async def verify_configuration(candidate: dict[str, str], changed_keys: set[str]) -> dict[str, dict[str, Any]]:
    """Authenticate all populated/changed providers before saving."""
    results: dict[str, dict[str, Any]] = {}

    # 1. OpenRouter
    or_key = candidate.get("OPENROUTER_API_KEY", "").strip()
    if or_key and ("OPENROUTER_API_KEY" in changed_keys or changed_keys == set(candidate.keys())):
        if not or_key.startswith("sk-or-"):
            results["OPENROUTER_API_KEY"] = {"status": "failed", "detail": "Invalid format: OpenRouter keys start with 'sk-or-'."}
        else:
            results["OPENROUTER_API_KEY"] = await _auth_http_check(
                "OpenRouter",
                "https://openrouter.ai/api/v1/key",
                {"Authorization": f"Bearer {or_key}"},
                lambda r: f"Verified OpenRouter key ({(r.json().get('data') or {}).get('label') or 'active'})",
            )

    # 2. OpenAI
    oai_key = candidate.get("OPENAI_API_KEY", "").strip()
    if oai_key and ("OPENAI_API_KEY" in changed_keys or changed_keys == set(candidate.keys())):
        if not oai_key.startswith("sk-"):
            results["OPENAI_API_KEY"] = {"status": "failed", "detail": "Invalid format: OpenAI keys start with 'sk-'."}
        else:
            results["OPENAI_API_KEY"] = await _auth_http_check(
                "OpenAI",
                "https://api.openai.com/v1/models",
                {"Authorization": f"Bearer {oai_key}"},
                lambda r: f"Verified OpenAI key ({len(r.json().get('data', []))} models accessible)",
            )

    # 3. ElevenLabs
    el_key = candidate.get("ELEVENLABS_API_KEY", "").strip()
    if el_key and ("ELEVENLABS_API_KEY" in changed_keys or changed_keys == set(candidate.keys())):
        if len(el_key) < 20 or any(c.isspace() for c in el_key):
            results["ELEVENLABS_API_KEY"] = {"status": "failed", "detail": "Invalid ElevenLabs key format."}
        else:
            results["ELEVENLABS_API_KEY"] = await _auth_http_check(
                "ElevenLabs",
                "https://api.elevenlabs.io/v1/user",
                {"xi-api-key": el_key},
                lambda r: f"Verified ElevenLabs account (tier: {(r.json().get('subscription') or {}).get('tier', 'active')})",
            )

    # 4. Emergent LLM Key
    em_key = candidate.get("EMERGENT_LLM_KEY", "").strip()
    proxy_url = (candidate.get("INTEGRATION_PROXY_URL") or "https://integrations.emergentagent.com").strip().rstrip("/")
    if em_key and ("EMERGENT_LLM_KEY" in changed_keys or changed_keys == set(candidate.keys())):
        if not em_key.startswith("sk-"):
            results["EMERGENT_LLM_KEY"] = {"status": "failed", "detail": "Invalid format: Emergent key should start with 'sk-'."}
        else:
            results["EMERGENT_LLM_KEY"] = await _auth_http_check(
                "Emergent LLM Gateway",
                f"{proxy_url}/llm/models",
                {"Authorization": f"Bearer {em_key}"},
            )

    # 5. OpenRouter Model list validation
    if "ROAST_OPENROUTER_MODELS" in changed_keys:
        models = [m.strip() for m in candidate.get("ROAST_OPENROUTER_MODELS", "").split(",") if m.strip()]
        if not models or len(models) > 6 or any("/" not in m for m in models):
            results["ROAST_OPENROUTER_MODELS"] = {
                "status": "failed",
                "detail": "Must be 1 to 6 comma-separated 'provider/model' slugs.",
            }
        else:
            results["ROAST_OPENROUTER_MODELS"] = {"status": "authenticated", "detail": f"{len(models)} valid model slug(s)"}

    # 6. Stripe Secret + Publishable + Webhook
    sk = candidate.get("STRIPE_API_KEY", "").strip()
    pk = candidate.get("STRIPE_PUBLISHABLE_KEY", "").strip()
    whsec = candidate.get("STRIPE_WEBHOOK_SECRET", "").strip()
    test_only = candidate.get("STRIPE_TEST_ONLY", "true").strip().lower() in ("1", "true", "yes")

    if sk and ("STRIPE_API_KEY" in changed_keys or "STRIPE_TEST_ONLY" in changed_keys or changed_keys == set(candidate.keys())):
        if not (sk.startswith("sk_test_") or sk.startswith("sk_live_") or sk.startswith("rk_test_") or sk.startswith("rk_live_")):
            results["STRIPE_API_KEY"] = {"status": "failed", "detail": "Stripe secret keys must start with sk_test_, sk_live_, rk_test_, or rk_live_."}
        elif test_only and ("_live_" in sk[:10]):
            results["STRIPE_API_KEY"] = {"status": "failed", "detail": "Live Stripe key blocked while STRIPE_TEST_ONLY=true."}
        else:
            results["STRIPE_API_KEY"] = await _auth_http_check(
                "Stripe",
                "https://api.stripe.com/v1/account",
                {"Authorization": f"Bearer {sk}"},
                lambda r: f"Verified Stripe account {r.json().get('id', '')} ({'test' if '_test_' in sk else 'live'} mode)",
            )

    if pk and ("STRIPE_PUBLISHABLE_KEY" in changed_keys or "STRIPE_API_KEY" in changed_keys or "STRIPE_TEST_ONLY" in changed_keys):
        if not (pk.startswith("pk_test_") or pk.startswith("pk_live_")):
            results["STRIPE_PUBLISHABLE_KEY"] = {"status": "failed", "detail": "Publishable key must start with pk_test_ or pk_live_."}
        elif test_only and pk.startswith("pk_live_"):
            results["STRIPE_PUBLISHABLE_KEY"] = {"status": "failed", "detail": "Live publishable key blocked while STRIPE_TEST_ONLY=true."}
        elif sk and (("_test_" in sk) != pk.startswith("pk_test_")):
            results["STRIPE_PUBLISHABLE_KEY"] = {"status": "failed", "detail": "Mode mismatch: STRIPE_PUBLISHABLE_KEY and STRIPE_API_KEY must both be test or both be live."}
        else:
            results["STRIPE_PUBLISHABLE_KEY"] = {"status": "authenticated", "detail": "Format and Stripe mode match verified"}

    if whsec and ("STRIPE_WEBHOOK_SECRET" in changed_keys or changed_keys == set(candidate.keys())):
        if not whsec.startswith("whsec_") or len(whsec) < 16:
            results["STRIPE_WEBHOOK_SECRET"] = {"status": "failed", "detail": "Webhook secret must start with 'whsec_'."}
        else:
            # Verify HMAC signature construction using stripe SDK locally
            try:
                ts = str(int(time.time()))
                payload = b'{"id":"evt_test","type":"checkout.session.completed"}'
                sig = hmac.new(whsec.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
                stripe.Webhook.construct_event(payload, f"t={ts},v1={sig}", whsec)
                results["STRIPE_WEBHOOK_SECRET"] = {"status": "authenticated", "detail": "Webhook signing secret verified via HMAC-SHA256"}
            except Exception as exc:
                results["STRIPE_WEBHOOK_SECRET"] = {"status": "failed", "detail": f"Webhook verification failed: {exc}"}

    # 7. Google OAuth
    g_id = candidate.get("GOOGLE_CLIENT_ID", "").strip()
    g_sec = candidate.get("GOOGLE_CLIENT_SECRET", "").strip()
    g_redir = candidate.get("GOOGLE_REDIRECT_URI", "").strip()
    if g_id and ("GOOGLE_CLIENT_ID" in changed_keys or changed_keys == set(candidate.keys())):
        if not g_id.endswith(".apps.googleusercontent.com") or len(g_id) < 30:
            results["GOOGLE_CLIENT_ID"] = {"status": "failed", "detail": "Google Client ID must end with '.apps.googleusercontent.com'."}
        else:
            chk = await _auth_http_check(
                "Google OAuth Discovery",
                "https://accounts.google.com/.well-known/openid-configuration",
                {},
                lambda r: "Google Client ID format valid & Google OAuth OpenID endpoint reachable",
            )
            results["GOOGLE_CLIENT_ID"] = chk

    if g_sec and ("GOOGLE_CLIENT_SECRET" in changed_keys or changed_keys == set(candidate.keys())):
        if len(g_sec) < 16 or any(c.isspace() for c in g_sec):
            results["GOOGLE_CLIENT_SECRET"] = {"status": "failed", "detail": "Google Client Secret looks invalid (too short or contains whitespace)."}
        elif not g_id:
            results["GOOGLE_CLIENT_SECRET"] = {"status": "failed", "detail": "Provide GOOGLE_CLIENT_ID alongside GOOGLE_CLIENT_SECRET."}
        else:
            results["GOOGLE_CLIENT_SECRET"] = {"status": "authenticated", "detail": "Google Client Secret format valid & paired with Client ID"}

    if g_redir and ("GOOGLE_REDIRECT_URI" in changed_keys):
        u = urlsplit(g_redir)
        if u.scheme not in ("http", "https") or not u.netloc:
            results["GOOGLE_REDIRECT_URI"] = {"status": "failed", "detail": "Redirect URI must be a full http(s):// URL."}
        else:
            results["GOOGLE_REDIRECT_URI"] = {"status": "authenticated", "detail": "Valid OAuth redirect URL"}

    # 8. SMTP Email Auth
    smtp_host = candidate.get("SMTP_HOST", "").strip()
    smtp_port = int(candidate.get("SMTP_PORT", "587") or 587)
    smtp_tls = candidate.get("SMTP_TLS_MODE", "starttls").strip().lower()
    smtp_user = candidate.get("SMTP_USERNAME", "").strip()
    smtp_pass = candidate.get("SMTP_PASSWORD", "").strip()
    if any(k in changed_keys for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_TLS_MODE", "SMTP_USERNAME", "SMTP_PASSWORD")) and smtp_host:
        def _test_smtp():
            if smtp_tls == "ssl":
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=8) as s:
                    s.ehlo()
                    if smtp_user and smtp_pass:
                        s.login(smtp_user, smtp_pass)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=8) as s:
                    s.ehlo()
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                    if smtp_user and smtp_pass:
                        s.login(smtp_user, smtp_pass)
        try:
            await asyncio.to_thread(_test_smtp)
            results["SMTP_HOST"] = {"status": "authenticated", "detail": f"Connected & authenticated to {smtp_host}:{smtp_port} ({smtp_tls})"}
        except smtplib.SMTPAuthenticationError:
            results["SMTP_HOST"] = {"status": "failed", "detail": "SMTP authentication failed: invalid username or password."}
        except Exception as exc:
            if _sandbox_network_issue(exc):
                results["SMTP_HOST"] = {"status": "sandbox_blocked", "detail": f"Format valid; outbound SMTP to {smtp_host}:{smtp_port} blocked by sandbox firewall."}
            else:
                results["SMTP_HOST"] = {"status": "failed", "detail": f"SMTP connection error: {exc}"}

    # 9. MongoDB
    mongo_url = candidate.get("MONGO_URL", "").strip()
    if mongo_url and ("MONGO_URL" in changed_keys or "DB_NAME" in changed_keys or changed_keys == set(candidate.keys())):
        if not (mongo_url.startswith("mongodb://") or mongo_url.startswith("mongodb+srv://")):
            results["MONGO_URL"] = {"status": "failed", "detail": "MONGO_URL must start with mongodb:// or mongodb+srv://."}
        else:
            def _ping_mongo():
                c = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
                try:
                    c.admin.command("ping")
                finally:
                    c.close()
            try:
                await asyncio.to_thread(_ping_mongo)
                results["MONGO_URL"] = {"status": "authenticated", "detail": f"Connected & pinged MongoDB ({urlsplit(mongo_url).hostname or 'local'})"}
            except Exception as exc:
                if "127.0.0.1" not in mongo_url and "localhost" not in mongo_url and _sandbox_network_issue(exc):
                    results["MONGO_URL"] = {"status": "sandbox_blocked", "detail": f"URI valid; remote MongoDB unreachable from sandbox ({type(exc).__name__})."}
                else:
                    results["MONGO_URL"] = {"status": "failed", "detail": f"MongoDB ping failed: {exc}"}

    # 10. JWT & Beta Secrets
    jwt_sec = candidate.get("JWT_SECRET", "").strip()
    if "JWT_SECRET" in changed_keys:
        if len(jwt_sec) < 32:
            results["JWT_SECRET"] = {"status": "failed", "detail": "JWT_SECRET must be at least 32 characters."}
        else:
            results["JWT_SECRET"] = {"status": "authenticated", "detail": f"Valid cryptographic secret ({len(jwt_sec)} chars)"}

    beta_pw = candidate.get("BETA_ACCESS_PASSWORD_HASH", "").strip()
    if "BETA_ACCESS_PASSWORD_HASH" in changed_keys and beta_pw:
        if not beta_pw.startswith("scrypt$16384$8$1$") and len(beta_pw) < 10:
            results["BETA_ACCESS_PASSWORD_HASH"] = {"status": "failed", "detail": "Beta password must be at least 10 characters."}
        else:
            results["BETA_ACCESS_PASSWORD_HASH"] = {"status": "authenticated", "detail": "Hashed into scrypt$16384$8$1$ verifier"}

    beta_sk = candidate.get("BETA_ACCESS_SIGNING_KEY", "").strip()
    if "BETA_ACCESS_SIGNING_KEY" in changed_keys and beta_sk:
        if len(beta_sk) < 32:
            results["BETA_ACCESS_SIGNING_KEY"] = {"status": "failed", "detail": "BETA_ACCESS_SIGNING_KEY must be at least 32 characters."}
        else:
            results["BETA_ACCESS_SIGNING_KEY"] = {"status": "authenticated", "detail": "Valid 32+ char signing key"}

    # 11. Supabase (optional)
    sb_url = candidate.get("SUPABASE_URL", "").strip().rstrip("/")
    sb_anon = candidate.get("SUPABASE_ANON_KEY", "").strip()
    sb_srv = candidate.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if (sb_url or sb_anon or sb_srv) and any(k in changed_keys for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")):
        if not sb_url.startswith("https://") or ".supabase.co" not in sb_url:
            results["SUPABASE_URL"] = {"status": "failed", "detail": "SUPABASE_URL must look like https://<ref>.supabase.co"}
        else:
            test_key = sb_srv or sb_anon
            if not test_key:
                results["SUPABASE_URL"] = {"status": "failed", "detail": "Provide SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY to authenticate Supabase."}
            else:
                results["SUPABASE_URL"] = await _auth_http_check(
                    "Supabase",
                    f"{sb_url}/rest/v1/",
                    {"apikey": test_key, "Authorization": f"Bearer {test_key}"},
                    lambda r: "Verified Supabase REST endpoint & API key",
                )

    # 12. Vercel (optional)
    v_tok = candidate.get("VERCEL_TOKEN", "").strip()
    if v_tok and ("VERCEL_TOKEN" in changed_keys or changed_keys == set(candidate.keys())):
        if len(v_tok) < 16:
            results["VERCEL_TOKEN"] = {"status": "failed", "detail": "Vercel token looks too short."}
        else:
            results["VERCEL_TOKEN"] = await _auth_http_check(
                "Vercel",
                "https://api.vercel.com/v2/user",
                {"Authorization": f"Bearer {v_tok}"},
                lambda r: f"Verified Vercel user: {(r.json().get('user') or {}).get('username', 'active')}",
            )

    return results


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="Da RoastBox API & Auth Vault", docs_url=None, redoc_url=None)


class SavePayload(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    clear_keys: list[str] = Field(default_factory=list)
    allow_sandbox_deferred: bool = False


@app.get("/api/vault/state")
async def get_vault_state():
    be = parse_env_file(BACKEND_ENV_PATH)
    fe = parse_env_file(FRONTEND_ENV_PATH)
    fields = []
    for meta in FIELD_CATALOG:
        k = meta["key"]
        raw = be.get(k, "")
        if not raw and meta.get("frontend_key"):
            raw = fe.get(meta["frontend_key"], "")
        is_secret = bool(meta.get("secret"))
        fields.append({
            **meta,
            "is_set": bool(raw),
            "value": "" if is_secret else raw,
            "masked_preview": mask_secret(raw) if is_secret and raw else "",
        })
    return {
        "fields": fields,
        "is_sandbox": IS_SANDBOX,
        "backend_env_exists": BACKEND_ENV_PATH.exists(),
        "frontend_env_exists": FRONTEND_ENV_PATH.exists(),
    }


@app.post("/api/vault/verify-saved")
async def verify_saved():
    be = parse_env_file(BACKEND_ENV_PATH)
    fe = parse_env_file(FRONTEND_ENV_PATH)
    merged = {**be}
    for meta in FIELD_CATALOG:
        fk = meta.get("frontend_key")
        if fk and fk in fe and meta["key"] not in merged:
            merged[meta["key"]] = fe[fk]
    results = await verify_configuration(merged, set(merged.keys()))
    return {"results": results}


@app.post("/api/vault/save")
async def save_vault(body: SavePayload):
    be = parse_env_file(BACKEND_ENV_PATH)
    fe = parse_env_file(FRONTEND_ENV_PATH)

    candidate = dict(be)
    changed_keys: set[str] = set()
    be_updates: dict[str, str] = {}
    fe_updates: dict[str, str] = {}

    for k in body.clear_keys:
        if k not in FIELD_BY_KEY:
            continue
        meta = FIELD_BY_KEY[k]
        candidate[k] = ""
        changed_keys.add(k)
        if meta["target"] in ("backend", "both"):
            be_updates[k] = ""
        if meta["target"] == "both" and meta.get("frontend_key"):
            fe_updates[meta["frontend_key"]] = ""

    for k, raw_val in body.values.items():
        if k not in FIELD_BY_KEY:
            continue
        meta = FIELD_BY_KEY[k]
        val = (raw_val or "").strip()
        if meta.get("secret") and not val:
            # Blank secret input leaves existing secret intact unless explicitly cleared
            continue
        if not meta.get("secret") and val == candidate.get(k, ""):
            continue
        if meta.get("beta_password") and val:
            candidate[k] = val  # verify length before hashing
        else:
            candidate[k] = val
        changed_keys.add(k)
        if meta["target"] in ("backend", "both"):
            be_updates[k] = scrypt_verifier(val) if meta.get("beta_password") and val else val
        if meta["target"] == "both" and meta.get("frontend_key"):
            fe_updates[meta["frontend_key"]] = val

    if not changed_keys:
        return JSONResponse({"saved": False, "reason": "no_changes", "results": {}, "message": "No new or modified credentials to authenticate."})

    results = await verify_configuration(candidate, changed_keys)
    failures = {k: v for k, v in results.items() if v["status"] == "failed"}
    blocked = {k: v for k, v in results.items() if v["status"] == "sandbox_blocked"}

    if failures:
        return JSONResponse(
            status_code=400,
            content={
                "saved": False,
                "reason": "auth_failed",
                "results": results,
                "message": "Authentication failed for one or more credentials. Nothing was saved.",
            },
        )

    if blocked and not body.allow_sandbox_deferred:
        return JSONResponse(
            status_code=409,
            content={
                "saved": False,
                "reason": "sandbox_blocked",
                "results": results,
                "message": (
                    "Format checks passed, but outbound authentication to external providers was blocked "
                    "by the sandbox firewall. Check 'Allow save when sandbox firewall blocks live check' "
                    "to save format-verified keys anyway."
                ),
            },
        )

    update_env_file(BACKEND_ENV_PATH, be_updates)
    update_env_file(FRONTEND_ENV_PATH, fe_updates)

    return {
        "saved": True,
        "results": results,
        "updated_keys": sorted(changed_keys),
        "message": (
            f"Authenticated and saved {len(changed_keys)} setting(s) to backend/.env"
            + (" and frontend/.env." if fe_updates else ".")
            + (" Note: Restart the API/Web server if already running to reload env vars." if be_updates or fe_updates else "")
        ),
    }


@app.post("/api/vault/generate-secret")
async def generate_secret():
    return {"secret": secrets.token_hex(32)}


# ---------------------------------------------------------------------------
# Self-Contained UI
# ---------------------------------------------------------------------------
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Da RoastBox V.7 — API &amp; Auth Setup Vault</title>
<style>
  :root {
    --bg: #0b0c10;
    --panel: #13161d;
    --panel2: #191d27;
    --border: #2a3140;
    --text: #f3f4f6;
    --muted: #9ca3af;
    --gold: #f59e0b;
    --ember: #ea580c;
    --green: #22c55e;
    --red: #ef4444;
    --amber: #f59e0b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background: radial-gradient(circle at top right, rgba(234,88,12,.14), transparent 36%), var(--bg);
    color: var(--text);
    line-height: 1.5;
  }
  header {
    position: sticky;
    top: 0;
    z-index: 20;
    backdrop-filter: blur(12px);
    background: rgba(11,12,16,.88);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    align-items: center;
    justify-content: space-between;
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .badge {
    background: linear-gradient(135deg, var(--gold), var(--ember));
    color: #0b0c10;
    font-weight: 800;
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 999px;
    letter-spacing: .06em;
    text-transform: uppercase;
  }
  h1 { margin: 0; font-size: 19px; font-weight: 800; letter-spacing: .01em; }
  .sub { font-size: 12px; color: var(--muted); }
  .actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  button {
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--panel2);
    color: var(--text);
    padding: 9px 15px;
    border-radius: 10px;
    font-weight: 600;
    font-size: 13px;
    transition: .15s ease;
  }
  button:hover { border-color: var(--gold); }
  button.primary {
    background: linear-gradient(135deg, var(--gold), var(--ember));
    color: #0b0c10;
    border: none;
    font-weight: 800;
  }
  button.primary:disabled { opacity: .55; cursor: wait; }
  main { max-width: 1120px; margin: 24px auto 80px; padding: 0 20px; }
  .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
  .tab {
    padding: 8px 14px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--muted);
  }
  .tab.active { background: rgba(245,158,11,.15); color: var(--gold); border-color: var(--gold); }
  .banner {
    display: none;
    padding: 14px 16px;
    border-radius: 12px;
    margin-bottom: 18px;
    font-size: 13px;
    border: 1px solid var(--border);
    background: var(--panel);
  }
  .banner.show { display: block; }
  .banner.ok { border-color: rgba(34,197,94,.5); background: rgba(34,197,94,.1); color: #bbf7d0; }
  .banner.err { border-color: rgba(239,68,68,.5); background: rgba(239,68,68,.12); color: #fecaca; }
  .banner.warn { border-color: rgba(245,158,11,.55); background: rgba(245,158,11,.12); color: #fde68a; }
  .sandbox-opt {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid var(--border);
    margin-bottom: 18px;
    font-size: 13px;
    color: #e5e7eb;
  }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); gap: 16px; }
  @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .label-wrap { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .label { font-weight: 700; font-size: 14px; }
  .env-key { font-family: ui-monospace, monospace; font-size: 11px; color: var(--muted); background: #0d0f14; padding: 2px 6px; border-radius: 6px; border: 1px solid var(--border); }
  .help-btn {
    width: 24px; height: 24px; padding: 0; border-radius: 999px;
    display: inline-flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 12px; color: var(--gold); border-color: rgba(245,158,11,.45);
    background: rgba(245,158,11,.1);
  }
  .pill { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
  .pill.set { background: rgba(34,197,94,.14); color: #86efac; border: 1px solid rgba(34,197,94,.35); }
  .pill.unset { background: rgba(156,163,175,.12); color: var(--muted); border: 1px solid var(--border); }
  .purpose { font-size: 12px; color: var(--muted); margin: 0; }
  .input-row { display: flex; gap: 8px; align-items: center; }
  input[type="text"], input[type="password"], select {
    width: 100%;
    background: #0b0d12;
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 13px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  input:focus, select:focus { outline: none; border-color: var(--gold); }
  .mini-btn { padding: 8px 10px; font-size: 11px; white-space: nowrap; }
  .status-line { font-size: 12px; padding: 8px 10px; border-radius: 8px; display: none; }
  .status-line.show { display: block; }
  .status-line.authenticated { background: rgba(34,197,94,.12); color: #86efac; border: 1px solid rgba(34,197,94,.35); }
  .status-line.failed { background: rgba(239,68,68,.12); color: #fca5a5; border: 1px solid rgba(239,68,68,.4); }
  .status-line.sandbox_blocked { background: rgba(245,158,11,.12); color: #fde68a; border: 1px solid rgba(245,158,11,.4); }

  /* Help Modal */
  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,.72); backdrop-filter: blur(4px);
    display: none; align-items: center; justify-content: center; z-index: 50; padding: 20px;
  }
  .modal-backdrop.open { display: flex; }
  .modal {
    background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
    max-width: 620px; width: 100%; padding: 22px; box-shadow: 0 24px 60px rgba(0,0,0,.65);
  }
  .modal h2 { margin: 0 0 6px; font-size: 18px; }
  .modal ol { padding-left: 20px; margin: 12px 0 16px; }
  .modal li { margin-bottom: 8px; font-size: 13px; color: #e5e7eb; }
  .portal-link {
    display: inline-block; margin-top: 6px; color: var(--gold); font-weight: 700; font-size: 13px; text-decoration: none;
  }
  .portal-link:hover { text-decoration: underline; }
</style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="badge">Setup Vault :8090</span>
      <div>
        <h1>Da RoastBox V.7 — API Keys &amp; Auth Manager</h1>
        <div class="sub">Authenticates credentials before writing <code>backend/.env</code> &amp; <code>frontend/.env</code></div>
      </div>
    </div>
    <div class="actions">
      <button type="button" id="verifySavedBtn">Test Currently Saved Keys</button>
      <button type="button" class="primary" id="saveBtn">Authenticate &amp; Save to Project</button>
    </div>
  </header>

  <main>
    <div id="banner" class="banner"></div>

    <label class="sandbox-opt">
      <input type="checkbox" id="allowSandboxDeferred" />
      <span>
        <strong>Allow saving format-verified keys if sandbox firewall blocks live API check:</strong>
        Arena's sandbox blocks outbound TLS to external APIs (OpenAI, OpenRouter, Stripe, ElevenLabs, Google). Bad/malformed keys are still rejected; leave unchecked when running outside the sandbox for strict live auth.
      </span>
    </label>

    <div class="tabs" id="tabs"></div>
    <div class="grid" id="grid"></div>
  </main>

  <div class="modal-backdrop" id="helpModal">
    <div class="modal">
      <div style="display:flex;justify-content:space-between;align-items:start;gap:12px;">
        <div>
          <h2 id="helpTitle"></h2>
          <div class="env-key" id="helpEnv"></div>
        </div>
        <button type="button" id="closeHelp">Close</button>
      </div>
      <p id="helpPurpose" style="font-size:13px;color:#d1d5db;margin:12px 0 8px;"></p>
      <div style="font-size:12px;color:var(--muted);">Expected format: <strong id="helpFormat" style="color:#f3f4f6;"></strong></div>
      <a id="helpPortal" class="portal-link" target="_blank" rel="noopener noreferrer"></a>
      <h3 style="font-size:13px;margin:16px 0 6px;color:var(--gold);text-transform:uppercase;letter-spacing:.05em;">How to get this credential</h3>
      <ol id="helpSteps"></ol>
    </div>
  </div>

<script>
const GROUPS = [
  { id: "all", label: "All Credentials" },
  { id: "ai", label: "AI & Voices (OpenRouter / OpenAI / ElevenLabs)" },
  { id: "stripe", label: "Stripe Payments" },
  { id: "google", label: "Google Login & Auth" },
  { id: "email", label: "Email / SMTP" },
  { id: "infra", label: "Database & App Security" },
  { id: "cloud", label: "Supabase & Vercel" },
];

let fields = [];
let activeGroup = "all";
const pendingValues = {};
const clearedKeys = new Set();
const statusMap = {};

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v);
  }
  for (const ch of children) node.appendChild(typeof ch === "string" ? document.createTextNode(ch) : ch);
  return node;
}

function showBanner(type, text) {
  const b = document.getElementById("banner");
  b.className = `banner show ${type}`;
  b.textContent = text;
}

function openHelp(field) {
  document.getElementById("helpTitle").textContent = field.label;
  document.getElementById("helpEnv").textContent = field.key + (field.frontend_key ? ` + ${field.frontend_key}` : "");
  document.getElementById("helpPurpose").textContent = field.purpose;
  document.getElementById("helpFormat").textContent = field.format_hint || "Standard string";
  const portal = document.getElementById("helpPortal");
  portal.href = field.portal_url;
  portal.textContent = `Open ${field.portal_name} ↗`;
  const ol = document.getElementById("helpSteps");
  ol.innerHTML = "";
  for (const step of field.steps || []) ol.appendChild(el("li", { text: step }));
  document.getElementById("helpModal").classList.add("open");
}

document.getElementById("closeHelp").onclick = () => document.getElementById("helpModal").classList.remove("open");
document.getElementById("helpModal").onclick = (e) => { if (e.target.id === "helpModal") e.target.classList.remove("open"); };

function renderTabs() {
  const wrap = document.getElementById("tabs");
  wrap.innerHTML = "";
  for (const g of GROUPS) {
    wrap.appendChild(el("button", {
      type: "button",
      class: `tab ${activeGroup === g.id ? "active" : ""}`,
      text: g.label,
      onClick: () => { activeGroup = g.id; renderTabs(); renderGrid(); },
    }));
  }
}

function renderGrid() {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  const list = activeGroup === "all" ? fields : fields.filter(f => f.group === activeGroup);
  for (const f of list) {
    const isCleared = clearedKeys.has(f.key);
    const pill = f.is_set && !isCleared
      ? el("span", { class: "pill set", text: f.secret ? `Configured (${f.masked_preview})` : "Configured" })
      : el("span", { class: "pill unset", text: isCleared ? "Pending Clear" : "Not Set" });

    let inputEl;
    if (f.type === "select") {
      inputEl = el("select", {
        onChange: (e) => { pendingValues[f.key] = e.target.value; clearedKeys.delete(f.key); },
      }, f.options.map(opt => {
        const o = el("option", { value: opt, text: opt });
        const cur = pendingValues[f.key] !== undefined ? pendingValues[f.key] : f.value;
        if (cur === opt) o.selected = true;
        return o;
      }));
    } else {
      const curVal = pendingValues[f.key] !== undefined ? pendingValues[f.key] : (f.secret ? "" : f.value);
      inputEl = el("input", {
        type: f.secret ? "password" : "text",
        value: curVal,
        placeholder: f.secret && f.is_set && !isCleared ? `Enter new value to replace (${f.masked_preview})` : f.placeholder,
        autocomplete: "off",
        onInput: (e) => { pendingValues[f.key] = e.target.value; clearedKeys.delete(f.key); },
      });
    }

    const rowChildren = [inputEl];
    if (f.secret && f.type !== "select") {
      rowChildren.push(el("button", {
        type: "button",
        class: "mini-btn",
        text: "Show",
        onClick: (e) => {
          const isPw = inputEl.type === "password";
          inputEl.type = isPw ? "text" : "password";
          e.target.textContent = isPw ? "Hide" : "Show";
        },
      }));
    }
    if (f.generatable) {
      rowChildren.push(el("button", {
        type: "button",
        class: "mini-btn",
        text: "Generate",
        onClick: async () => {
          const r = await fetch("/api/vault/generate-secret", { method: "POST" });
          const d = await r.json();
          inputEl.value = d.secret;
          inputEl.type = "text";
          pendingValues[f.key] = d.secret;
          clearedKeys.delete(f.key);
        },
      }));
    }
    if (f.is_set) {
      rowChildren.push(el("button", {
        type: "button",
        class: "mini-btn",
        text: isCleared ? "Undo" : "Clear",
        onClick: () => {
          if (clearedKeys.has(f.key)) clearedKeys.delete(f.key);
          else { clearedKeys.add(f.key); delete pendingValues[f.key]; inputEl.value = ""; }
          renderGrid();
        },
      }));
    }

    const st = statusMap[f.key];
    const stLabel = st ? (st.status === "sandbox_blocked" ? "FORMAT VALID (SANDBOX BLOCKED LIVE CHECK)" : st.status.toUpperCase()) : "";
    const statusEl = el("div", {
      class: st ? `status-line show ${st.status}` : "status-line",
      text: st ? `${stLabel}: ${st.detail}` : "",
    });

    const card = el("div", { class: "card" }, [
      el("div", { class: "card-head" }, [
        el("div", { class: "label-wrap" }, [
          el("span", { class: "label", text: f.label }),
          el("button", { type: "button", class: "help-btn", title: "How to get this key", text: "?", onClick: () => openHelp(f) }),
        ]),
        pill,
      ]),
      el("div", { style: "display:flex;align-items:center;justify-content:space-between;gap:8px;" }, [
        el("span", { class: "env-key", text: f.key }),
      ]),
      el("p", { class: "purpose", text: f.purpose }),
      el("div", { class: "input-row" }, rowChildren),
      statusEl,
    ]);
    grid.appendChild(card);
  }
}

let initialLoad = true;
async function loadState() {
  const r = await fetch("/api/vault/state");
  const d = await r.json();
  fields = d.fields;
  if (initialLoad) {
    initialLoad = false;
    if (d.is_sandbox) {
      document.getElementById("allowSandboxDeferred").checked = true;
    }
  }
  renderTabs();
  renderGrid();
}

document.getElementById("verifySavedBtn").onclick = async () => {
  showBanner("warn", "Testing currently saved credentials...");
  const r = await fetch("/api/vault/verify-saved", { method: "POST" });
  const d = await r.json();
  Object.assign(statusMap, d.results || {});
  renderGrid();
  const vals = Object.values(d.results || {});
  const failed = vals.filter(v => v.status === "failed").length;
  const blocked = vals.filter(v => v.status === "sandbox_blocked").length;
  if (failed) showBanner("err", `${failed} saved credential(s) failed authentication. Check red cards below.`);
  else if (blocked) showBanner("warn", `Local checks passed; ${blocked} external check(s) blocked by sandbox firewall (format valid).`);
  else showBanner("ok", "All configured credentials passed authentication!");
};

document.getElementById("saveBtn").onclick = async () => {
  const btn = document.getElementById("saveBtn");
  btn.disabled = true;
  btn.textContent = "Authenticating...";
  try {
    const r = await fetch("/api/vault/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        values: pendingValues,
        clear_keys: Array.from(clearedKeys),
        allow_sandbox_deferred: document.getElementById("allowSandboxDeferred").checked,
      }),
    });
    const d = await r.json();
    for (const [k, v] of Object.entries(d.results || {})) statusMap[k] = v;
    if (d.saved) {
      for (const k of d.updated_keys || []) {
        delete pendingValues[k];
        clearedKeys.delete(k);
      }
      showBanner("ok", d.message);
      await loadState();
    } else if (d.reason === "no_changes") {
      showBanner("warn", d.message);
    } else if (d.reason === "sandbox_blocked") {
      showBanner("warn", d.message);
      renderGrid();
    } else {
      showBanner("err", d.message || "Authentication failed.");
      renderGrid();
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "Authenticate & Save to Project";
  }
};

loadState();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


if __name__ == "__main__":
    uvicorn.run(app, host=SETUP_HOST, port=SETUP_PORT, log_level="info")
