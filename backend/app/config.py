from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    openai_api_key: str = ''
    llm_provider: Literal['openai', 'mock'] = 'openai'
    stt_provider: Literal['openai', 'none'] = 'openai'
    tts_provider: Literal['openai', 'none'] = 'openai'
    llm_model: str = 'gpt-4o-mini'
    stt_model: str = 'gpt-transcribe'
    tts_model: str = 'gpt-4o-mini-tts'
    tts_voice: str = 'marin'
    mock_mode: bool = False
    request_timeout: float = 35
    data_dir: Path = ROOT / 'case' / 'voice_router_dataset'
    session_archive_dir: Path = ROOT / 'runtime' / 'sessions'
    allowed_origins: str = 'http://localhost:3000,http://localhost:4173,http://127.0.0.1:4173,http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000'

    @property
    def provider(self):
        return 'mock' if self.mock_mode or self.llm_provider == 'mock' else 'openai'

    @property
    def key(self):
        return self.openai_api_key

    @property
    def model(self):
        return self.llm_model


settings = Settings()
