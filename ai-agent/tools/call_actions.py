"""
Tools de controle de chamada para o LLM.

Estas tools permitem ao agente de voz controlar chamadas
durante a conversa (transferir, encerrar).
"""

import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("ai-agent.tools")

# Mapeamento de departamentos para ramais
# Configuravel via env DEPARTMENT_MAP (formato: "suporte:1001,vendas:1002")
def _load_department_map() -> Dict[str, str]:
    default = {
        "suporte": "1001",
        "vendas": "1002",
        "financeiro": "1003",
    }
    env_map = os.environ.get("DEPARTMENT_MAP", "")
    if not env_map:
        return default
    result = {}
    for pair in env_map.split(","):
        if ":" in pair:
            dept, ramal = pair.strip().split(":", 1)
            result[dept.strip()] = ramal.strip()
    return result if result else default

DEPARTMENT_MAP = _load_department_map()

# Tool definitions no formato OpenAI API (compativel com llama.cpp, vLLM, Ollama)
CALL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "transfer_call",
            "description": (
                "Transfere a chamada atual para outro ramal ou departamento. "
                "Use quando o cliente precisa ser atendido por outra pessoa ou setor. "
                "IMPORTANTE: Antes de transferir, SEMPRE avise o cliente na sua resposta de texto. "
                f"Departamentos disponiveis: {', '.join(f'{k} (ramal {v})' for k, v in DEPARTMENT_MAP.items())}. "
                "Voce tambem pode transferir para um ramal especifico (ex: '1001')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Ramal destino (ex: '1001') ou nome do departamento (ex: 'suporte')"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Motivo da transferencia para log/auditoria"
                    }
                },
                "required": ["target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": (
                "Encerra a chamada atual de forma educada. "
                "Use quando a conversa chegou ao fim natural e o cliente nao precisa de mais nada. "
                "IMPORTANTE: Antes de encerrar, SEMPRE se despeca na sua resposta de texto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Motivo do encerramento para log/auditoria"
                    }
                }
            }
        }
    }
]

def resolve_target(target: str) -> str:
    """Resolve nome de departamento para ramal numerico."""
    target_lower = target.lower().strip()
    if target_lower in DEPARTMENT_MAP:
        resolved = DEPARTMENT_MAP[target_lower]
        logger.info(f"Departamento '{target}' resolvido para ramal {resolved}")
        return resolved
    return target
