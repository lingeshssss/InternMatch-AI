from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    # Real environment variables take precedence over the ignored repository .env.
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    app_env: str = 'development'
    database_url: str = 'postgresql+psycopg://internmatch@127.0.0.1:55432/internmatch'
    # Exact public origins (scheme://host[:port]) the browser uses. Same-origin deployments list one URL.
    # FRONTEND_ORIGIN is accepted for compatibility with earlier configuration.
    app_origins: str = ''
    frontend_origin: str = ''
    data_encryption_key: str = ''

    # AI provider selection. 'disabled' never fabricates output; postings remain Unverified.
    ai_provider: str = 'disabled'            # disabled | ollama | openai
    ai_fallback_provider: str = ''           # '' | openai; used only when AI_ALLOW_HOSTED_FALLBACK=true
    ai_allow_hosted_fallback: bool = False
    ai_timeout_seconds: float = 180
    ai_max_concurrency: int = 1
    # Local runtime. HTTP is allowed only for loopback or hosts explicitly listed in OLLAMA_ALLOWED_HTTP_HOSTS.
    ollama_base_url: str = 'http://127.0.0.1:11434'
    ollama_allowed_http_hosts: str = ''
    ollama_model: str = 'qwen3.5:9b'
    ollama_embedding_model: str = 'qwen3-embedding:0.6b'
    ollama_num_ctx: int = 16384
    ollama_keep_alive: str = '10m'
    # Hosted OpenAI-compatible provider: HTTPS and an API key are mandatory.
    ai_api_key: str = ''
    ai_base_url: str = 'https://api.openai.com/v1'
    ai_model: str = 'gpt-4.1-mini'
    embedding_model: str = 'text-embedding-3-small'

    greenhouse_boards: str = ''
    lever_sites: str = ''
    discovery_interval_seconds: int = 21600
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_username: str = ''
    smtp_password: str = ''
    email_from: str = ''

    @model_validator(mode='after')
    def normalize(self):
        if self.ai_provider not in ('disabled', 'ollama', 'openai'): raise ValueError('AI_PROVIDER must be disabled, ollama or openai')
        if self.ai_fallback_provider not in ('', 'openai'): raise ValueError('AI_FALLBACK_PROVIDER must be empty or openai')
        if self.ai_max_concurrency < 1: raise ValueError('AI_MAX_CONCURRENCY must be at least 1')
        # Managed hosts provide postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg 3 driver name.
        for prefix in ('postgres://', 'postgresql://'):
            if self.database_url.startswith(prefix): self.database_url = 'postgresql+psycopg://' + self.database_url[len(prefix):]
        return self

    @property
    def origins(self) -> list[str]:
        raw = self.app_origins or self.frontend_origin
        if not raw: raw = 'http://localhost:8080,http://127.0.0.1:8080' if self.app_env != 'production' else ''
        # Tolerate quotes and whitespace pasted into hosting dashboards.
        return [x.strip().strip('"\'').strip().rstrip('/') for x in raw.split(',') if x.strip().strip('"\'').strip()]

    @property
    def production(self) -> bool: return self.app_env == 'production'

settings = Settings()
