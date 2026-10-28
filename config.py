"""Configuration is loaded once; credentials are never returned to clients."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env(path=ROOT / '.env'):
    """Small .env reader. Existing environment variables take precedence."""
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


@dataclass(frozen=True)
class Settings:
    backend: str = 'openai'
    model: str = ''
    model_url: str = 'https://api.modelarts-maas.com/openai/v1'
    api_key: str = ''
    retrieval_url: str = ''
    retrieval_key: str = ''
    knowledge_path: Path = ROOT / 'data' / 'knowledge.jsonl'
    rules_path: Path = ROOT / 'data' / 'red_flags.json'
    max_calls: int = 16
    max_rounds: int = 2
    max_agents: int = 3
    deadline_seconds: float = 90
    request_timeout: float = 25
    top_k: int = 4
    enable_triage_output: bool = False
    api_token: str = ''
    routing_strategy: str = 'adaptive'
    json_mode: str = 'auto'

    @classmethod
    def from_env(cls):
        load_env()
        settings = cls(
            backend=os.getenv('MODEL_BACKEND', 'openai'),
            model=os.getenv('MODEL_NAME', ''),
            model_url=os.getenv('MODEL_URL', cls.model_url).rstrip('/'),
            api_key=os.getenv('MODEL_API_KEY', ''),
            retrieval_url=os.getenv('RETRIEVAL_URL', ''),
            retrieval_key=os.getenv('RETRIEVAL_API_KEY', ''),
            knowledge_path=Path(os.getenv('KNOWLEDGE_PATH', str(cls.knowledge_path))),
            rules_path=Path(os.getenv('RULES_PATH', str(cls.rules_path))),
            max_calls=int(os.getenv('MAX_MODEL_CALLS', '16')),
            max_rounds=int(os.getenv('MAX_DISCUSSION_ROUNDS', '2')),
            max_agents=int(os.getenv('MAX_SPECIALISTS', '3')),
            deadline_seconds=float(os.getenv('REQUEST_DEADLINE_SECONDS', '90')),
            request_timeout=float(os.getenv('MODEL_TIMEOUT_SECONDS', '25')),
            top_k=int(os.getenv('RETRIEVAL_TOP_K', '4')),
            enable_triage_output=os.getenv('ENABLE_TRIAGE_OUTPUT', 'false').lower() == 'true',
            api_token=os.getenv('LOCAL_API_TOKEN', ''),
            routing_strategy=os.getenv('ROUTING_STRATEGY', 'adaptive'),
            json_mode=os.getenv('MODEL_JSON_MODE', 'auto').lower(),
        )
        if settings.backend not in ('demo', 'openai'):
            raise ValueError('MODEL_BACKEND must be demo or openai')
        if not (1 <= settings.max_calls <= 40 and 1 <= settings.max_rounds <= 3
                and 2 <= settings.max_agents <= 3 and 1 <= settings.top_k <= 10):
            raise ValueError('Invalid call, discussion, specialist or retrieval limits')
        if settings.deadline_seconds <= 0 or settings.request_timeout <= 0:
            raise ValueError('Timeouts must be positive')
        if settings.routing_strategy not in ('adaptive', 'single', 'fixed_multi'):
            raise ValueError('Invalid ROUTING_STRATEGY')
        if settings.json_mode not in ('auto', 'true', 'false'):
            raise ValueError('MODEL_JSON_MODE must be auto, true or false')
        return settings
