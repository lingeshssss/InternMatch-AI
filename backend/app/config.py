from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='../.env', extra='ignore')
    app_env: str = 'development'
    database_url: str = 'postgresql+psycopg://internmatch:internmatch@localhost:5432/internmatch'
    redis_url: str = 'redis://localhost:6379/0'
    frontend_origin: str = 'http://localhost:3000'
    data_encryption_key: str = ''
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

settings = Settings()
