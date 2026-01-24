"""
VoiceParallel para execução paralela de runnables.

Permite executar múltiplos runnables em paralelo com a mesma entrada
e combinar seus resultados.
"""

import asyncio
from typing import Any, AsyncIterator, Optional, Union

from voice_pipeline.runnable.base import VoiceRunnable
from voice_pipeline.runnable.config import RunnableConfig, ensure_config


class VoiceParallel(VoiceRunnable[Any, dict[str, Any]]):
    """
    Executa múltiplos runnables em paralelo com a mesma entrada.

    Útil quando você precisa processar o mesmo input de diferentes
    formas simultaneamente.

    Examples:
        >>> # Executa ASR em dois modelos diferentes
        >>> parallel = VoiceParallel(
        ...     whisper=whisper_asr,
        ...     deepgram=deepgram_asr,
        ... )
        >>> results = await parallel.ainvoke(audio)
        >>> # results = {"whisper": ..., "deepgram": ...}

        >>> # Pode usar como parte de uma chain
        >>> chain = audio_processor | VoiceParallel(
        ...     transcription=asr,
        ...     sentiment=sentiment_analyzer,
        ... )
    """

    def __init__(
        self,
        steps: Optional[dict[str, VoiceRunnable]] = None,
        **kwargs: VoiceRunnable,
    ):
        """
        Inicializa com os runnables nomeados.

        Args:
            steps: Dicionário de nome -> runnable.
            **kwargs: Runnables adicionais como keyword arguments.
        """
        self.steps: dict[str, VoiceRunnable] = {}
        if steps:
            self.steps.update(steps)
        self.steps.update(kwargs)

        if not self.steps:
            raise ValueError("VoiceParallel precisa de pelo menos um step")

    @property
    def name(self) -> str:
        names = list(self.steps.keys())
        return f"Parallel({', '.join(names)})"

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> dict[str, Any]:
        """
        Executa todos os runnables em paralelo.

        Args:
            input: Entrada comum para todos os runnables.
            config: Configuração opcional.

        Returns:
            Dicionário com resultados de cada runnable.
        """
        config = ensure_config(config)

        # Cria tasks para todos os runnables
        tasks = {
            name: asyncio.create_task(step.ainvoke(input, config))
            for name, step in self.steps.items()
        }

        # Aguarda todos completarem
        results = {}
        for name, task in tasks.items():
            try:
                results[name] = await task
            except Exception as e:
                results[name] = e

        return results

    async def astream(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Executa em paralelo e emite resultados conforme chegam.

        Cada yield contém o estado atual dos resultados, com novos
        valores adicionados conforme os runnables completam.

        Args:
            input: Entrada comum.
            config: Configuração opcional.

        Yields:
            Dicionário parcial com resultados disponíveis.
        """
        config = ensure_config(config)

        # Cria tasks
        tasks = {
            name: asyncio.create_task(step.ainvoke(input, config))
            for name, step in self.steps.items()
        }

        results: dict[str, Any] = {}
        pending = set(tasks.values())

        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )

            for task in done:
                # Encontra o nome correspondente
                for name, t in tasks.items():
                    if t is task:
                        try:
                            results[name] = task.result()
                        except Exception as e:
                            results[name] = e
                        break

            yield results.copy()

    def __getitem__(self, key: str) -> VoiceRunnable:
        """Acessa um runnable específico pelo nome."""
        return self.steps[key]

    def __contains__(self, key: str) -> bool:
        """Verifica se um nome está nos steps."""
        return key in self.steps

    @property
    def input_schema(self) -> type:
        """
        Schema de entrada é a união dos schemas de todos os steps.
        Por simplicidade, retorna Any.
        """
        return Any

    @property
    def output_schema(self) -> type:
        """Schema de saída é um dict."""
        return dict[str, Any]

    def __repr__(self) -> str:
        steps_repr = ", ".join(f"{k}={repr(v)}" for k, v in self.steps.items())
        return f"VoiceParallel({steps_repr})"


class VoiceRaceParallel(VoiceRunnable[Any, Any]):
    """
    Executa runnables em paralelo e retorna o primeiro que completar.

    Útil para implementar fallbacks ou competir entre provedores.

    Examples:
        >>> # Usa o ASR mais rápido
        >>> fastest = VoiceRaceParallel(
        ...     whisper=whisper_asr,
        ...     deepgram=deepgram_asr,
        ... )
        >>> result = await fastest.ainvoke(audio)
        >>> # result contém a transcrição do mais rápido
    """

    def __init__(
        self,
        steps: Optional[dict[str, VoiceRunnable]] = None,
        return_winner_name: bool = False,
        **kwargs: VoiceRunnable,
    ):
        """
        Inicializa com os runnables competidores.

        Args:
            steps: Dicionário de nome -> runnable.
            return_winner_name: Se True, retorna tuple (name, result).
            **kwargs: Runnables adicionais.
        """
        self.steps: dict[str, VoiceRunnable] = {}
        if steps:
            self.steps.update(steps)
        self.steps.update(kwargs)
        self.return_winner_name = return_winner_name

        if not self.steps:
            raise ValueError("VoiceRaceParallel precisa de pelo menos um step")

    @property
    def name(self) -> str:
        names = list(self.steps.keys())
        return f"Race({', '.join(names)})"

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> Union[Any, tuple[str, Any]]:
        """
        Executa todos e retorna o primeiro resultado.

        Args:
            input: Entrada comum.
            config: Configuração opcional.

        Returns:
            Resultado do primeiro runnable a completar.
            Se return_winner_name=True, retorna (nome, resultado).
        """
        config = ensure_config(config)

        # Cria tasks nomeadas
        async def run_named(name: str, step: VoiceRunnable):
            result = await step.ainvoke(input, config)
            return name, result

        tasks = [
            asyncio.create_task(run_named(name, step))
            for name, step in self.steps.items()
        ]

        # Aguarda o primeiro completar
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )

        # Cancela os outros
        for task in pending:
            task.cancel()

        # Retorna o resultado do vencedor
        winner_task = done.pop()
        winner_name, result = winner_task.result()

        if self.return_winner_name:
            return winner_name, result
        return result

    async def astream(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Any]:
        """
        Streaming do primeiro runnable a completar.

        Inicia streaming de todos e continua apenas com o primeiro
        que produzir output.
        """
        config = ensure_config(config)

        # Cria iteradores de streaming para todos
        streams = {
            name: step.astream(input, config)
            for name, step in self.steps.items()
        }

        # Função para obter primeiro chunk de um stream
        async def get_first(name: str, stream: AsyncIterator):
            async for chunk in stream:
                return name, chunk, stream
            return name, None, None

        tasks = [
            asyncio.create_task(get_first(name, stream))
            for name, stream in streams.items()
        ]

        # Aguarda o primeiro chunk
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )

        # Cancela os outros
        for task in pending:
            task.cancel()

        # Continua com o vencedor
        winner_task = done.pop()
        winner_name, first_chunk, winner_stream = winner_task.result()

        if first_chunk is not None:
            yield first_chunk
            if winner_stream:
                async for chunk in winner_stream:
                    yield chunk

    def __repr__(self) -> str:
        steps_repr = ", ".join(f"{k}={repr(v)}" for k, v in self.steps.items())
        return f"VoiceRaceParallel({steps_repr})"
