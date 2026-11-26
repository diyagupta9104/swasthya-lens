"""Server-only configuration. Never return keys from a public endpoint."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
load_dotenv(ROOT.parent / '.env', override=False)


def api_key() -> str:
    return (os.getenv('OPENAI_API_KEY') or os.getenv('Open_ai_api_key') or '').strip()


MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
EMBEDDING_MODEL = os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
SEMANTIC = os.getenv('SEMANTIC_RETRIEVAL', 'true').lower() == 'true'
