from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    groq_api_key: str = ''
    openai_api_key: str = ''
    llm_provider: Literal['auto','groq','openai'] = 'auto'
    llm_model: str = ''
    mock_mode: bool = False
    tts_provider: Literal['edge','none'] = 'edge'
    request_timeout: float = 35
    data_dir: Path = ROOT / 'case' / 'voice_router_dataset'
    allowed_origins: str = 'http://localhost:3000,http://localhost:4173,http://127.0.0.1:4173,http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000'

    @property
    def provider(self):
        if self.mock_mode:
            return 'mock'
        if self.llm_provider != 'auto':
            key = self.groq_api_key if self.llm_provider == 'groq' else self.openai_api_key
            return self.llm_provider if key else 'mock'
        return 'groq' if self.groq_api_key else 'openai' if self.openai_api_key else 'mock'

    @property
    def key(self):
        return self.groq_api_key if self.provider == 'groq' else self.openai_api_key

    @property
    def model(self):
        return self.llm_model or ('llama-3.3-70b-versatile' if self.provider == 'groq' else 'gpt-4o-mini')

    @property
    def api_base(self):
        return 'https://api.groq.com/openai/v1' if self.provider == 'groq' else 'https://api.openai.com/v1'

settings = Settings()
