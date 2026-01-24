"""
Interface base VoiceRunnable para componentes do Voice Pipeline.

Esta é a interface fundamental que todos os componentes (ASR, LLM, TTS, VAD)
devem implementar. Segue o padrão LCEL do LangChain adaptado para Voice AI.
"""

from abc import ABC, abstractmethod
from typing import (
    Any,
    AsyncIterator,
    Generic,
    Iterator,
    Optional,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from voice_pipeline.runnable.config import RunnableConfig, ensure_config

# Type variables para input e output
Input = TypeVar("Input")
Output = TypeVar("Output")


class VoiceRunnable(ABC, Generic[Input, Output]):
    """
    Interface base para todos os componentes do Voice Pipeline.

    Cada componente (ASR, LLM, TTS, VAD) herda desta classe e implementa
    os métodos necessários. A interface suporta:

    - Execução síncrona: invoke, batch
    - Execução assíncrona: ainvoke, abatch (primário para Voice)
    - Streaming: stream, astream (essencial para baixa latência)
    - Composição: operador | para criar pipelines

    Examples:
        >>> # Composição simples
        >>> chain = asr | llm | tts
        >>> result = await chain.ainvoke(audio_bytes)

        >>> # Streaming
        >>> async for chunk in chain.astream(audio_bytes):
        ...     play(chunk)
    """

    # Nome do componente para logging/tracing
    name: str = "VoiceRunnable"

    # ==================== Métodos Síncronos ====================

    def invoke(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> Output:
        """
        Executa o componente de forma síncrona.

        Na maioria dos casos de Voice AI, você deve preferir ainvoke().

        Args:
            input: Dados de entrada.
            config: Configuração opcional com callbacks e metadata.

        Returns:
            Resultado processado.
        """
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self.ainvoke(input, config)
        )

    def batch(
        self,
        inputs: list[Input],
        config: Optional[RunnableConfig] = None,
        *,
        return_exceptions: bool = False,
    ) -> list[Output]:
        """
        Processa múltiplas entradas de forma síncrona.

        Args:
            inputs: Lista de entradas para processar.
            config: Configuração opcional.
            return_exceptions: Se True, retorna exceções em vez de propagar.

        Returns:
            Lista de resultados na mesma ordem das entradas.
        """
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self.abatch(inputs, config, return_exceptions=return_exceptions)
        )

    def stream(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> Iterator[Output]:
        """
        Gera resultados em streaming de forma síncrona.

        Para Voice AI, prefira astream().

        Args:
            input: Dados de entrada.
            config: Configuração opcional.

        Yields:
            Chunks de resultado.
        """
        import asyncio

        async def collect():
            chunks = []
            async for chunk in self.astream(input, config):
                chunks.append(chunk)
            return chunks

        for chunk in asyncio.get_event_loop().run_until_complete(collect()):
            yield chunk

    # ==================== Métodos Assíncronos (Primários) ====================

    @abstractmethod
    async def ainvoke(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> Output:
        """
        Executa o componente de forma assíncrona.

        Este é o método principal para execução em pipelines de voz.

        Args:
            input: Dados de entrada.
            config: Configuração opcional com callbacks e metadata.

        Returns:
            Resultado processado.
        """
        ...

    async def abatch(
        self,
        inputs: list[Input],
        config: Optional[RunnableConfig] = None,
        *,
        return_exceptions: bool = False,
        max_concurrency: Optional[int] = None,
    ) -> list[Output]:
        """
        Processa múltiplas entradas de forma assíncrona e paralela.

        Args:
            inputs: Lista de entradas para processar.
            config: Configuração opcional.
            return_exceptions: Se True, retorna exceções em vez de propagar.
            max_concurrency: Limite de execuções paralelas.

        Returns:
            Lista de resultados na mesma ordem das entradas.
        """
        import asyncio

        config = ensure_config(config)
        concurrency = max_concurrency or config.max_concurrency

        if concurrency is None:
            # Sem limite de concorrência
            tasks = [self.ainvoke(input, config) for input in inputs]
            if return_exceptions:
                return await asyncio.gather(*tasks, return_exceptions=True)
            return await asyncio.gather(*tasks)

        # Com limite de concorrência usando semáforo
        semaphore = asyncio.Semaphore(concurrency)

        async def run_with_semaphore(input: Input) -> Output:
            async with semaphore:
                return await self.ainvoke(input, config)

        tasks = [run_with_semaphore(input) for input in inputs]
        if return_exceptions:
            return await asyncio.gather(*tasks, return_exceptions=True)
        return await asyncio.gather(*tasks)

    async def astream(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Output]:
        """
        Gera resultados em streaming de forma assíncrona.

        Este método é essencial para pipelines de voz com baixa latência.
        A implementação padrão apenas retorna o resultado de ainvoke(),
        mas subclasses devem sobrescrever para streaming real.

        Args:
            input: Dados de entrada.
            config: Configuração opcional.

        Yields:
            Chunks de resultado.
        """
        yield await self.ainvoke(input, config)

    # ==================== Composição (LCEL) ====================

    def __or__(self, other: "VoiceRunnable") -> "VoiceSequence":
        """
        Compõe este runnable com outro usando operador |.

        Examples:
            >>> chain = asr | llm | tts
            >>> result = await chain.ainvoke(audio)
        """
        from voice_pipeline.runnable.sequence import VoiceSequence

        # Se self já é uma sequence, adiciona ao final
        if isinstance(self, VoiceSequence):
            return VoiceSequence(steps=self.steps + [other])
        # Se other é uma sequence, adiciona no início
        if isinstance(other, VoiceSequence):
            return VoiceSequence(steps=[self] + other.steps)
        # Cria nova sequence
        return VoiceSequence(steps=[self, other])

    def __ror__(self, other: Any) -> "VoiceSequence":
        """
        Suporta composição reversa (valor | runnable).

        Examples:
            >>> result = await ({"text": "hello"} | llm | tts).ainvoke({})
        """
        from voice_pipeline.runnable.passthrough import VoicePassthrough
        from voice_pipeline.runnable.sequence import VoiceSequence

        # Envolve o valor em um passthrough que retorna ele
        wrapped = VoicePassthrough(value=other)
        return VoiceSequence(steps=[wrapped, self])

    def pipe(self, *others: "VoiceRunnable") -> "VoiceSequence":
        """
        Método alternativo para composição de múltiplos runnables.

        Examples:
            >>> chain = asr.pipe(llm, tts)
            >>> result = await chain.ainvoke(audio)
        """
        from voice_pipeline.runnable.sequence import VoiceSequence

        if isinstance(self, VoiceSequence):
            return VoiceSequence(steps=self.steps + list(others))
        return VoiceSequence(steps=[self] + list(others))

    # ==================== Schema ====================

    @property
    def input_schema(self) -> type:
        """
        Retorna o tipo de entrada esperado.

        Extrai da anotação Generic se possível.
        """
        # Tenta extrair do Generic
        for base in type(self).__orig_bases__:
            origin = get_origin(base)
            if origin is VoiceRunnable:
                args = get_args(base)
                if args:
                    return args[0]
        return Any

    @property
    def output_schema(self) -> type:
        """
        Retorna o tipo de saída produzido.

        Extrai da anotação Generic se possível.
        """
        # Tenta extrair do Generic
        for base in type(self).__orig_bases__:
            origin = get_origin(base)
            if origin is VoiceRunnable:
                args = get_args(base)
                if len(args) > 1:
                    return args[1]
        return Any

    # ==================== Utilitários ====================

    def with_config(
        self, config: Optional[RunnableConfig] = None, **kwargs: Any
    ) -> "VoiceRunnableWithConfig":
        """
        Retorna uma versão deste runnable com configuração pré-definida.

        Args:
            config: Configuração base.
            **kwargs: Valores adicionais para a configuração.

        Returns:
            Runnable com configuração embutida.
        """
        return VoiceRunnableWithConfig(
            runnable=self, config=ensure_config(config), **kwargs
        )

    def bind(self, **kwargs: Any) -> "VoiceRunnableBound":
        """
        Retorna uma versão deste runnable com argumentos pré-definidos.

        Args:
            **kwargs: Argumentos a serem passados em cada invocação.

        Returns:
            Runnable com argumentos embutidos.
        """
        return VoiceRunnableBound(runnable=self, kwargs=kwargs)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class VoiceRunnableWithConfig(VoiceRunnable[Input, Output]):
    """Runnable com configuração embutida."""

    def __init__(
        self,
        runnable: VoiceRunnable[Input, Output],
        config: RunnableConfig,
        **kwargs: Any,
    ):
        self.runnable = runnable
        self.base_config = config
        self.extra_config = kwargs

    @property
    def name(self) -> str:
        return self.runnable.name

    async def ainvoke(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> Output:
        merged_config = self.base_config.merge(config)
        # Aplica kwargs extras à config
        for key, value in self.extra_config.items():
            if hasattr(merged_config, key):
                setattr(merged_config, key, value)
        return await self.runnable.ainvoke(input, merged_config)

    async def astream(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Output]:
        merged_config = self.base_config.merge(config)
        for key, value in self.extra_config.items():
            if hasattr(merged_config, key):
                setattr(merged_config, key, value)
        async for chunk in self.runnable.astream(input, merged_config):
            yield chunk

    @property
    def input_schema(self) -> type:
        return self.runnable.input_schema

    @property
    def output_schema(self) -> type:
        return self.runnable.output_schema


class VoiceRunnableBound(VoiceRunnable[Input, Output]):
    """Runnable com argumentos pré-definidos."""

    def __init__(
        self, runnable: VoiceRunnable[Input, Output], kwargs: dict[str, Any]
    ):
        self.runnable = runnable
        self.bound_kwargs = kwargs

    @property
    def name(self) -> str:
        return self.runnable.name

    async def ainvoke(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> Output:
        # Para runnables que aceitam kwargs adicionais no input
        if isinstance(input, dict):
            merged_input = {**input, **self.bound_kwargs}
            return await self.runnable.ainvoke(merged_input, config)
        return await self.runnable.ainvoke(input, config)

    async def astream(
        self, input: Input, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Output]:
        if isinstance(input, dict):
            merged_input = {**input, **self.bound_kwargs}
            async for chunk in self.runnable.astream(merged_input, config):
                yield chunk
        else:
            async for chunk in self.runnable.astream(input, config):
                yield chunk

    @property
    def input_schema(self) -> type:
        return self.runnable.input_schema

    @property
    def output_schema(self) -> type:
        return self.runnable.output_schema
