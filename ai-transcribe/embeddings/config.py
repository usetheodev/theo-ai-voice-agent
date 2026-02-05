"""
Configuracoes do Embedding Provider
"""

import os
import sys

# Adiciona shared ao path para imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from shared_config import parse_bool


# Modelo padrao: intfloat/multilingual-e5-small
# - Licenca MIT
# - 384 dimensoes
# - ~130MB
# - Excelente em portugues
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_DIMS = 384


EMBEDDING_CONFIG = {
    "enabled": parse_bool(os.getenv("EMBEDDING_ENABLED", "true"), True),
    "model": os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL),
    "device": os.getenv("EMBEDDING_DEVICE", "cpu"),
    "batch_size": int(os.getenv("EMBEDDING_BATCH_SIZE", "8")),
    "executor_workers": int(os.getenv("EMBEDDING_EXECUTOR_WORKERS", "2")),
    "normalize": parse_bool(os.getenv("EMBEDDING_NORMALIZE", "true"), True),
}


ENRICHMENT_CONFIG = {
    "enabled": parse_bool(os.getenv("ENRICHMENT_ENABLED", "false"), False),
    "sentiment_enabled": parse_bool(os.getenv("SENTIMENT_ENABLED", "true"), True),
    "topics_enabled": parse_bool(os.getenv("TOPICS_ENABLED", "false"), False),
    "intent_enabled": parse_bool(os.getenv("INTENT_ENABLED", "false"), False),
}
