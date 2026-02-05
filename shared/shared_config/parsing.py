"""Utilitarios de parsing de configuracao compartilhados."""
from typing import List


def parse_bool(value: str, default: bool = False) -> bool:
    """Parse boolean de string.

    Args:
        value: String a ser convertida (true, 1, yes, on)
        default: Valor padrao se value for vazio

    Returns:
        True se value for um dos valores truthy, False caso contrario
    """
    if not value:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def parse_list(value: str, default: List[str]) -> List[str]:
    """Parse lista separada por virgula.

    Args:
        value: String com itens separados por virgula
        default: Lista padrao se value for vazio

    Returns:
        Lista de strings com itens trimados
    """
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]
