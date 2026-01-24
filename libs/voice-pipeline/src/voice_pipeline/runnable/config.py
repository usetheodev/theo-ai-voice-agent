"""
Configuração para VoiceRunnable.

Este módulo define RunnableConfig que permite passar callbacks,
metadata e outras configurações para os componentes do pipeline.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from voice_pipeline.callbacks.base import VoiceCallbackHandler


@dataclass
class RunnableConfig:
    """
    Configuração passada para métodos de VoiceRunnable.

    Attributes:
        callbacks: Lista de handlers de callback para observabilidade.
        metadata: Metadata arbitrária associada à execução.
        tags: Tags para categorização e filtragem.
        run_id: ID único para esta execução (para tracing).
        run_name: Nome legível para esta execução.
        max_concurrency: Limite de concorrência para operações em batch.
        configurable: Configurações extras específicas do provider.
    """

    callbacks: list["VoiceCallbackHandler"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    run_id: Optional[str] = None
    run_name: Optional[str] = None
    max_concurrency: Optional[int] = None
    configurable: dict[str, Any] = field(default_factory=dict)

    def merge(self, other: Optional["RunnableConfig"]) -> "RunnableConfig":
        """
        Mescla esta config com outra, priorizando valores da outra.

        Args:
            other: Outra configuração para mesclar.

        Returns:
            Nova RunnableConfig com valores mesclados.
        """
        if other is None:
            return self

        return RunnableConfig(
            callbacks=self.callbacks + other.callbacks,
            metadata={**self.metadata, **other.metadata},
            tags=list(set(self.tags + other.tags)),
            run_id=other.run_id or self.run_id,
            run_name=other.run_name or self.run_name,
            max_concurrency=other.max_concurrency or self.max_concurrency,
            configurable={**self.configurable, **other.configurable},
        )

    def with_callbacks(
        self, callbacks: list["VoiceCallbackHandler"]
    ) -> "RunnableConfig":
        """
        Retorna nova config com callbacks adicionais.

        Args:
            callbacks: Callbacks a adicionar.

        Returns:
            Nova RunnableConfig com callbacks adicionados.
        """
        return RunnableConfig(
            callbacks=self.callbacks + callbacks,
            metadata=self.metadata.copy(),
            tags=self.tags.copy(),
            run_id=self.run_id,
            run_name=self.run_name,
            max_concurrency=self.max_concurrency,
            configurable=self.configurable.copy(),
        )

    def with_metadata(self, **metadata: Any) -> "RunnableConfig":
        """
        Retorna nova config com metadata adicional.

        Args:
            **metadata: Metadata a adicionar.

        Returns:
            Nova RunnableConfig com metadata adicionada.
        """
        return RunnableConfig(
            callbacks=self.callbacks.copy(),
            metadata={**self.metadata, **metadata},
            tags=self.tags.copy(),
            run_id=self.run_id,
            run_name=self.run_name,
            max_concurrency=self.max_concurrency,
            configurable=self.configurable.copy(),
        )

    def with_tags(self, tags: list[str]) -> "RunnableConfig":
        """
        Retorna nova config com tags adicionais.

        Args:
            tags: Tags a adicionar.

        Returns:
            Nova RunnableConfig com tags adicionadas.
        """
        return RunnableConfig(
            callbacks=self.callbacks.copy(),
            metadata=self.metadata.copy(),
            tags=list(set(self.tags + tags)),
            run_id=self.run_id,
            run_name=self.run_name,
            max_concurrency=self.max_concurrency,
            configurable=self.configurable.copy(),
        )


def ensure_config(config: Optional[RunnableConfig] = None) -> RunnableConfig:
    """
    Garante que sempre temos uma RunnableConfig válida.

    Args:
        config: Configuração opcional.

    Returns:
        A configuração fornecida ou uma nova vazia.
    """
    return config if config is not None else RunnableConfig()


def get_callback_manager(
    config: Optional[RunnableConfig] = None,
) -> list["VoiceCallbackHandler"]:
    """
    Extrai callbacks de uma configuração.

    Args:
        config: Configuração opcional.

    Returns:
        Lista de callbacks (vazia se não houver config).
    """
    if config is None:
        return []
    return config.callbacks
