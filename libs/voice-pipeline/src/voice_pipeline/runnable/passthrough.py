"""
VoicePassthrough e utilitários para manipulação de dados no pipeline.

Estes runnables permitem transformar, filtrar e rotear dados
sem processamento complexo.
"""

from typing import Any, AsyncIterator, Callable, Optional, TypeVar, Union

from voice_pipeline.runnable.base import VoiceRunnable
from voice_pipeline.runnable.config import RunnableConfig, ensure_config

T = TypeVar("T")


class VoicePassthrough(VoiceRunnable[T, T]):
    """
    Passa a entrada diretamente para a saída sem modificação.

    Útil para debugging, composição e para representar valores literais.

    Examples:
        >>> # Simplesmente passa o valor
        >>> passthrough = VoicePassthrough()
        >>> result = await passthrough.ainvoke({"key": "value"})
        >>> # result = {"key": "value"}

        >>> # Com valor fixo
        >>> fixed = VoicePassthrough(value={"config": True})
        >>> result = await fixed.ainvoke(anything)
        >>> # result = {"config": True}
    """

    def __init__(self, value: Optional[T] = None):
        """
        Inicializa o passthrough.

        Args:
            value: Valor fixo a retornar (se None, passa a entrada).
        """
        self.value = value

    @property
    def name(self) -> str:
        if self.value is not None:
            return f"Passthrough({self.value})"
        return "Passthrough"

    async def ainvoke(
        self, input: T, config: Optional[RunnableConfig] = None
    ) -> T:
        """Retorna o valor fixo ou a entrada."""
        if self.value is not None:
            return self.value
        return input

    async def astream(
        self, input: T, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[T]:
        """Yield do valor uma vez."""
        yield await self.ainvoke(input, config)


class VoiceLambda(VoiceRunnable[Any, Any]):
    """
    Aplica uma função lambda/callable à entrada.

    Permite transformações simples inline no pipeline.

    Examples:
        >>> # Extrai campo de um dict
        >>> extract_text = VoiceLambda(lambda x: x["text"])
        >>> chain = asr | extract_text | llm

        >>> # Transformação assíncrona
        >>> async def process(x):
        ...     await asyncio.sleep(0.1)
        ...     return x.upper()
        >>> upper = VoiceLambda(process)
    """

    def __init__(
        self,
        func: Callable[[Any], Any],
        afunc: Optional[Callable[[Any], Any]] = None,
        name: Optional[str] = None,
    ):
        """
        Inicializa com a função a aplicar.

        Args:
            func: Função síncrona.
            afunc: Função assíncrona (opcional, usa func se não fornecido).
            name: Nome para identificação.
        """
        self.func = func
        self.afunc = afunc
        self._name = name or func.__name__ if hasattr(func, "__name__") else "Lambda"

    @property
    def name(self) -> str:
        return self._name

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> Any:
        """Aplica a função à entrada."""
        import asyncio
        import inspect

        if self.afunc:
            return await self.afunc(input)

        if asyncio.iscoroutinefunction(self.func):
            return await self.func(input)

        return self.func(input)


class VoiceRouter(VoiceRunnable[Any, Any]):
    """
    Roteia a entrada para diferentes runnables baseado em uma condição.

    Examples:
        >>> # Roteia baseado no idioma detectado
        >>> router = VoiceRouter(
        ...     condition=lambda x: x.get("language", "en"),
        ...     routes={
        ...         "pt": portuguese_handler,
        ...         "en": english_handler,
        ...     },
        ...     default=english_handler,
        ... )
    """

    def __init__(
        self,
        condition: Callable[[Any], str],
        routes: dict[str, VoiceRunnable],
        default: Optional[VoiceRunnable] = None,
    ):
        """
        Inicializa o router.

        Args:
            condition: Função que retorna a chave da rota.
            routes: Dicionário de chave -> runnable.
            default: Runnable padrão se chave não encontrada.
        """
        self.condition = condition
        self.routes = routes
        self.default = default

    @property
    def name(self) -> str:
        routes = ", ".join(self.routes.keys())
        return f"Router({routes})"

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> Any:
        """Roteia e executa o runnable apropriado."""
        import asyncio

        config = ensure_config(config)

        # Determina a rota
        if asyncio.iscoroutinefunction(self.condition):
            key = await self.condition(input)
        else:
            key = self.condition(input)

        # Encontra o runnable
        runnable = self.routes.get(key, self.default)
        if runnable is None:
            raise ValueError(f"Rota não encontrada para chave: {key}")

        return await runnable.ainvoke(input, config)

    async def astream(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Any]:
        """Roteia e faz streaming do runnable apropriado."""
        import asyncio

        config = ensure_config(config)

        if asyncio.iscoroutinefunction(self.condition):
            key = await self.condition(input)
        else:
            key = self.condition(input)

        runnable = self.routes.get(key, self.default)
        if runnable is None:
            raise ValueError(f"Rota não encontrada para chave: {key}")

        async for chunk in runnable.astream(input, config):
            yield chunk


class VoiceFilter(VoiceRunnable[T, Optional[T]]):
    """
    Filtra entradas baseado em uma condição.

    Se a condição for False, retorna None.

    Examples:
        >>> # Filtra transcrições muito curtas
        >>> filter_short = VoiceFilter(
        ...     condition=lambda x: len(x.text) > 5
        ... )
    """

    def __init__(self, condition: Callable[[T], bool]):
        """
        Inicializa com a condição de filtro.

        Args:
            condition: Função que retorna True para manter o valor.
        """
        self.condition = condition

    @property
    def name(self) -> str:
        return "Filter"

    async def ainvoke(
        self, input: T, config: Optional[RunnableConfig] = None
    ) -> Optional[T]:
        """Retorna input se condição é True, None caso contrário."""
        import asyncio

        if asyncio.iscoroutinefunction(self.condition):
            keep = await self.condition(input)
        else:
            keep = self.condition(input)

        return input if keep else None


class VoiceRetry(VoiceRunnable[Any, Any]):
    """
    Wrapper que adiciona retry automático a um runnable.

    Examples:
        >>> # Retry com backoff exponencial
        >>> reliable_asr = VoiceRetry(
        ...     runnable=asr,
        ...     max_retries=3,
        ...     backoff=2.0,
        ... )
    """

    def __init__(
        self,
        runnable: VoiceRunnable,
        max_retries: int = 3,
        backoff: float = 1.0,
        exceptions: tuple = (Exception,),
    ):
        """
        Inicializa com configuração de retry.

        Args:
            runnable: Runnable a executar.
            max_retries: Número máximo de tentativas.
            backoff: Fator de backoff entre tentativas.
            exceptions: Tupla de exceções que disparam retry.
        """
        self.runnable = runnable
        self.max_retries = max_retries
        self.backoff = backoff
        self.exceptions = exceptions

    @property
    def name(self) -> str:
        return f"Retry({self.runnable.name})"

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> Any:
        """Executa com retry automático."""
        import asyncio

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return await self.runnable.ainvoke(input, config)
            except self.exceptions as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.backoff * (2**attempt))

        raise last_exception

    async def astream(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Any]:
        """Streaming com retry (retry em falha inicial)."""
        import asyncio

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                async for chunk in self.runnable.astream(input, config):
                    yield chunk
                return
            except self.exceptions as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.backoff * (2**attempt))

        raise last_exception


class VoiceFallback(VoiceRunnable[Any, Any]):
    """
    Tenta múltiplos runnables em sequência até um funcionar.

    Examples:
        >>> # Fallback entre ASR providers
        >>> robust_asr = VoiceFallback(
        ...     primary=whisper_asr,
        ...     fallbacks=[deepgram_asr, google_asr],
        ... )
    """

    def __init__(
        self,
        primary: VoiceRunnable,
        fallbacks: list[VoiceRunnable],
        exceptions: tuple = (Exception,),
    ):
        """
        Inicializa com primary e fallbacks.

        Args:
            primary: Runnable principal a tentar primeiro.
            fallbacks: Lista de fallbacks em ordem de preferência.
            exceptions: Exceções que disparam fallback.
        """
        self.primary = primary
        self.fallbacks = fallbacks
        self.exceptions = exceptions

    @property
    def name(self) -> str:
        names = [self.primary.name] + [f.name for f in self.fallbacks]
        return f"Fallback({' -> '.join(names)})"

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> Any:
        """Tenta primary, depois fallbacks em ordem."""
        all_runnables = [self.primary] + self.fallbacks
        last_exception = None

        for runnable in all_runnables:
            try:
                return await runnable.ainvoke(input, config)
            except self.exceptions as e:
                last_exception = e
                continue

        raise last_exception

    async def astream(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Any]:
        """Streaming com fallback."""
        all_runnables = [self.primary] + self.fallbacks
        last_exception = None

        for runnable in all_runnables:
            try:
                async for chunk in runnable.astream(input, config):
                    yield chunk
                return
            except self.exceptions as e:
                last_exception = e
                continue

        raise last_exception
