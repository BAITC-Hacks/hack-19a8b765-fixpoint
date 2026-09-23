from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator
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
    request_timeout: float = Field(default=35, gt=0, le=120)
    max_text_chars: int = Field(default=4000, ge=1, le=10000)
    max_audio_bytes: int = Field(default=12 * 1024 * 1024, ge=1, le=16 * 1024 * 1024)
    max_recording_seconds: float = Field(default=60, gt=0, le=300)
    session_ttl_seconds: float = Field(default=1800, gt=0)
    max_sessions: int = Field(default=100, ge=1)
    max_session_turns: int = Field(default=1000, ge=1)
    max_ws_message_bytes: int = Field(default=16_777_216, ge=1024, le=16_777_216)
    data_dir: Path = ROOT / 'case' / 'voice_router_dataset'
    session_archive_dir: Path = ROOT / 'runtime' / 'sessions'
    allowed_origins: str = 'http://localhost:3000,http://localhost:4173,http://127.0.0.1:4173,http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000'

    @field_validator('llm_provider', mode='before')
    @classmethod
    def migrate_legacy_provider(cls, value):
        # Older local .env files may still name Groq; the current implementation
        # only supports OpenAI and mock mode.
        return 'openai' if value == 'groq' else value

    @field_validator('tts_provider', mode='before')
    @classmethod
    def migrate_legacy_tts(cls, value):
        return 'openai' if value == 'edge' else value

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
