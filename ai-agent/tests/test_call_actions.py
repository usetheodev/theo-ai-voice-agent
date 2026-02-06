"""
Testes unitarios para tools/call_actions.py

Cobertura:
- _load_department_map: defaults e env var
- resolve_target: departamento e ramal direto
- CALL_TOOLS: estrutura das tool definitions
"""

import os
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# Add ai-agent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# TESTES DE _load_department_map
# =============================================================================

class TestLoadDepartmentMap:
    """Testes para _load_department_map."""

    def test_default_map_when_env_empty(self):
        """Sem DEPARTMENT_MAP env, retorna defaults."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove env var se existir
            os.environ.pop("DEPARTMENT_MAP", None)

            from tools.call_actions import _load_department_map
            result = _load_department_map()

            assert result["suporte"] == "1001"
            assert result["vendas"] == "1002"
            assert result["financeiro"] == "1003"

    def test_custom_map_from_env(self):
        """DEPARTMENT_MAP env customizado."""
        with patch.dict(os.environ, {"DEPARTMENT_MAP": "ti:2001,rh:2002"}):
            from tools.call_actions import _load_department_map
            result = _load_department_map()

            assert result["ti"] == "2001"
            assert result["rh"] == "2002"
            assert "suporte" not in result

    def test_env_with_spaces(self):
        """Env com espacos extras nos pares."""
        with patch.dict(os.environ, {"DEPARTMENT_MAP": " suporte : 3001 , vendas : 3002 "}):
            from tools.call_actions import _load_department_map
            result = _load_department_map()

            assert result["suporte"] == "3001"
            assert result["vendas"] == "3002"

    def test_env_with_invalid_pairs_ignored(self):
        """Pares sem ':' sao ignorados."""
        with patch.dict(os.environ, {"DEPARTMENT_MAP": "suporte:1001,invalido,vendas:1002"}):
            from tools.call_actions import _load_department_map
            result = _load_department_map()

            assert result["suporte"] == "1001"
            assert result["vendas"] == "1002"
            assert "invalido" not in result

    def test_env_all_invalid_returns_default(self):
        """Se todos os pares forem invalidos, retorna default."""
        with patch.dict(os.environ, {"DEPARTMENT_MAP": "invalido1,invalido2"}):
            from tools.call_actions import _load_department_map
            result = _load_department_map()

            # Retorna default quando result esta vazio
            assert "suporte" in result
            assert "vendas" in result

    def test_single_department(self):
        """Um unico departamento."""
        with patch.dict(os.environ, {"DEPARTMENT_MAP": "helpdesk:5000"}):
            from tools.call_actions import _load_department_map
            result = _load_department_map()

            assert result == {"helpdesk": "5000"}


# =============================================================================
# TESTES DE resolve_target
# =============================================================================

class TestResolveTarget:
    """Testes para resolve_target."""

    def test_resolve_department_name(self):
        """Nome de departamento deve resolver para ramal."""
        from tools.call_actions import resolve_target, DEPARTMENT_MAP

        # Testa com os departamentos que estiverem carregados
        for dept, ramal in DEPARTMENT_MAP.items():
            assert resolve_target(dept) == ramal

    def test_resolve_case_insensitive(self):
        """Resolucao deve ser case-insensitive."""
        from tools.call_actions import resolve_target, DEPARTMENT_MAP

        if "suporte" in DEPARTMENT_MAP:
            assert resolve_target("SUPORTE") == DEPARTMENT_MAP["suporte"]
            assert resolve_target("Suporte") == DEPARTMENT_MAP["suporte"]

    def test_resolve_with_whitespace(self):
        """Resolucao deve ignorar whitespace."""
        from tools.call_actions import resolve_target, DEPARTMENT_MAP

        if "suporte" in DEPARTMENT_MAP:
            assert resolve_target("  suporte  ") == DEPARTMENT_MAP["suporte"]

    def test_numeric_target_passthrough(self):
        """Ramal numerico deve ser retornado diretamente."""
        from tools.call_actions import resolve_target

        assert resolve_target("1001") == "1001"
        assert resolve_target("9999") == "9999"

    def test_unknown_department_passthrough(self):
        """Departamento desconhecido deve ser retornado como esta."""
        from tools.call_actions import resolve_target

        assert resolve_target("departamento_inexistente") == "departamento_inexistente"

    def test_empty_string(self):
        """String vazia deve retornar vazia."""
        from tools.call_actions import resolve_target

        assert resolve_target("") == ""


# =============================================================================
# TESTES DE CALL_TOOLS
# =============================================================================

class TestCallTools:
    """Testes para CALL_TOOLS (definicoes de tool formato OpenAI API)."""

    def _get_tool_by_name(self, name: str):
        """Helper: busca tool pelo nome no formato OpenAI."""
        from tools.call_actions import CALL_TOOLS
        return next(t for t in CALL_TOOLS if t["function"]["name"] == name)

    def test_has_two_tools(self):
        """Deve haver exatamente 2 tools."""
        from tools.call_actions import CALL_TOOLS
        assert len(CALL_TOOLS) == 2

    def test_openai_format(self):
        """Tools devem estar no formato OpenAI (type=function + function dict)."""
        from tools.call_actions import CALL_TOOLS
        for tool in CALL_TOOLS:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]

    def test_transfer_call_structure(self):
        """Verifica estrutura do transfer_call tool."""
        transfer = self._get_tool_by_name("transfer_call")
        fn = transfer["function"]
        assert "description" in fn
        assert "parameters" in fn

        schema = fn["parameters"]
        assert schema["type"] == "object"
        assert "target" in schema["properties"]
        assert "reason" in schema["properties"]
        assert "target" in schema["required"]

    def test_end_call_structure(self):
        """Verifica estrutura do end_call tool."""
        end_call = self._get_tool_by_name("end_call")
        fn = end_call["function"]
        assert "description" in fn
        assert "parameters" in fn

        schema = fn["parameters"]
        assert schema["type"] == "object"
        assert "reason" in schema["properties"]

    def test_transfer_target_is_required(self):
        """Campo 'target' deve ser required em transfer_call."""
        transfer = self._get_tool_by_name("transfer_call")
        assert "target" in transfer["function"]["parameters"]["required"]

    def test_end_call_reason_is_optional(self):
        """Campo 'reason' nao deve ser required em end_call."""
        end_call = self._get_tool_by_name("end_call")
        required = end_call["function"]["parameters"].get("required", [])
        assert "reason" not in required

    def test_tool_descriptions_not_empty(self):
        """Todas as tools devem ter descricao nao vazia."""
        from tools.call_actions import CALL_TOOLS
        for tool in CALL_TOOLS:
            assert len(tool["function"]["description"]) > 0

    def test_transfer_description_mentions_departments(self):
        """Descricao de transfer_call deve mencionar departamentos disponiveis."""
        from tools.call_actions import CALL_TOOLS, DEPARTMENT_MAP

        transfer = self._get_tool_by_name("transfer_call")
        desc = transfer["function"]["description"]

        for dept in DEPARTMENT_MAP:
            assert dept in desc, f"Departamento '{dept}' nao encontrado na descricao"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
