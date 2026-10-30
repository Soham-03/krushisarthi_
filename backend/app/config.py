"""All settings come from environment variables (or a .env file)."""
import base64
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _e(key: str, default: str = "") -> str:
    val = os.environ.get(key, default)
    # allow "KEY=value   # comment" style lines
    return val.split(" #")[0].strip() if val else ""


def _clerk_domain(pk: str) -> str:
    """A Clerk publishable key is 'pk_test_' + base64('<frontend-api-domain>$')."""
    try:
        body = pk.split("_", 2)[2]
        body += "=" * (-len(body) % 4)
        return base64.b64decode(body).decode().rstrip("$")
    except Exception:
        return ""


class Settings:
    app_env = _e("APP_ENV", "development")
    data_dir = Path(_e("DATA_DIR", str(BASE_DIR / "data")))
    static_dir = BASE_DIR / "static"

    clerk_publishable_key = _e("CLERK_PUBLISHABLE_KEY")
    clerk_domain = _clerk_domain(clerk_publishable_key) if clerk_publishable_key else ""
    clerk_jwks_url = _e("CLERK_JWKS_URL") or (f"https://{clerk_domain}/.well-known/jwks.json" if clerk_domain else "")
    clerk_issuer = f"https://{clerk_domain}" if clerk_domain else ""
    clerk_enabled = bool(clerk_publishable_key and clerk_jwks_url)

    anthropic_api_key = _e("ANTHROPIC_API_KEY")
    chat_model = _e("CLAUDE_CHAT_MODEL", "claude-sonnet-5-5")
    vision_model = _e("CLAUDE_VISION_MODEL", "claude-sonnet-5-5")
    triage_model = _e("CLAUDE_TRIAGE_MODEL", "claude-haiku-5-5")

    ee_project = _e("EE_PROJECT")
    ee_service_account = _e("EE_SERVICE_ACCOUNT")
    ee_key_file = _e("EE_KEY_FILE")
    ee_enabled = bool(ee_project)

    vapid_public = _e("VAPID_PUBLIC_KEY")
    vapid_private = _e("VAPID_PRIVATE_KEY")
    vapid_subject = _e("VAPID_SUBJECT", "mailto:admin@example.com")
    push_enabled = bool(vapid_public and vapid_private)

    cron_secret = _e("CRON_SECRET")

    # ---- AI assistant (LLM provider) ---------------------------------------
    # anthropic        -> Claude through the Anthropic API (uses ANTHROPIC_API_KEY)
    # openai_compat    -> any OpenAI-style /chat/completions API (OpenAI, Gemini, Groq, Ollama, ...)
    llm_provider = _e("LLM_PROVIDER", "anthropic").lower()
    llm_model = _e("LLM_MODEL") or chat_model
    llm_base_url = _e("LLM_BASE_URL").rstrip("/")
    llm_api_key = _e("LLM_API_KEY")
    llm_timeout = float(_e("LLM_TIMEOUT_SECONDS", "60") or 60)
    llm_max_tokens = int(_e("LLM_MAX_TOKENS", "900") or 900)
    agent_max_rounds = int(_e("AGENT_MAX_TOOL_ROUNDS", "5") or 5)
    chat_rate_per_minute = int(_e("CHAT_RATE_PER_MINUTE", "20") or 20)

    # ---- Knowledge base (RAG) ----------------------------------------------
    kb_top_k = int(_e("KB_TOP_K", "5") or 5)
    kb_min_cosine = float(_e("KB_MIN_COSINE", "0.35") or 0.35)
    # Optional semantic search. Any OpenAI-compatible /embeddings endpoint (OpenAI, Voyage, Ollama, ...).
    embedding_base_url = _e("EMBEDDING_BASE_URL").rstrip("/")
    embedding_api_key = _e("EMBEDDING_API_KEY")
    embedding_model = _e("EMBEDDING_MODEL")
    embeddings_enabled = bool(embedding_base_url and embedding_model)

    # Photo features (leaf scan, weekly checkup photos, soil report) follow the same provider as the chat.
    llm_vision_model = _e("LLM_VISION_MODEL")
    llm_triage_model = _e("LLM_TRIAGE_MODEL")

    @property
    def ai_enabled(self) -> bool:
        return self.assistant_enabled

    @property
    def vision_model_name(self) -> str:
        return (self.vision_model if self.llm_provider == "anthropic" else (self.llm_vision_model or self.llm_model))

    @property
    def triage_model_name(self) -> str:
        return (self.triage_model if self.llm_provider == "anthropic" else (self.llm_triage_model or self.llm_vision_model or self.llm_model))

    @property
    def assistant_enabled(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai_compat":
            return bool(self.llm_base_url and self.llm_model)
        return False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cropmonitor.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
