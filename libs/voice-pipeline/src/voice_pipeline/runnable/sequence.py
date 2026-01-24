"""
VoiceSequence para composição sequencial de runnables.

Permite criar pipelines usando o operador | ou o método pipe().
"""

from typing import Any, AsyncIterator, Optional

from voice_pipeline.runnable.base import VoiceRunnable
from voice_pipeline.runnable.config import RunnableConfig, ensure_config


class VoiceSequence(VoiceRunnable[Any, Any]):
    """
    Executa uma sequência de runnables onde a saída de um é a entrada do próximo.

    Esta classe é criada automaticamente ao usar o operador |:

    Examples:
        >>> chain = asr | llm | tts
        >>> # É equivalente a:
        >>> chain = VoiceSequence(steps=[asr, llm, tts])

        >>> # Execução
        >>> result = await chain.ainvoke(audio_bytes)
        >>> # Internamente: tts(llm(asr(audio_bytes)))

        >>> # Streaming (propaga através da chain)
        >>> async for chunk in chain.astream(audio_bytes):
        ...     play(chunk)
    """

    def __init__(self, steps: list[VoiceRunnable]):
        """
        Inicializa a sequência com os passos.

        Args:
            steps: Lista ordenada de runnables a executar.
        """
        if not steps:
            raise ValueError("VoiceSequence precisa de pelo menos um step")
        self.steps = steps

    @property
    def name(self) -> str:
        """Nome da sequência baseado nos componentes."""
        names = [step.name for step in self.steps]
        return " | ".join(names)

    @property
    def first(self) -> VoiceRunnable:
        """Retorna o primeiro runnable da sequência."""
        return self.steps[0]

    @property
    def middle(self) -> list[VoiceRunnable]:
        """Retorna os runnables do meio (sem primeiro e último)."""
        return self.steps[1:-1] if len(self.steps) > 2 else []

    @property
    def last(self) -> VoiceRunnable:
        """Retorna o último runnable da sequência."""
        return self.steps[-1]

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> Any:
        """
        Executa toda a sequência de forma assíncrona.

        Args:
            input: Entrada inicial para o primeiro runnable.
            config: Configuração opcional.

        Returns:
            Saída do último runnable.
        """
        config = ensure_config(config)
        current = input

        for step in self.steps:
            current = await step.ainvoke(current, config)

        return current

    async def astream(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Any]:
        """
        Executa a sequência com streaming.

        Todos os passos exceto o último são executados com ainvoke().
        O último passo é executado com astream() para propagar o streaming.

        Para streaming completo end-to-end onde cada componente
        produz output assim que possível, use VoiceStreamingSequence.

        Args:
            input: Entrada inicial.
            config: Configuração opcional.

        Yields:
            Chunks do último runnable.
        """
        config = ensure_config(config)

        # Executa todos exceto o último normalmente
        current = input
        for step in self.steps[:-1]:
            current = await step.ainvoke(current, config)

        # Último passo em streaming
        async for chunk in self.last.astream(current, config):
            yield chunk

    def __len__(self) -> int:
        """Retorna o número de passos na sequência."""
        return len(self.steps)

    def __getitem__(self, index: int) -> VoiceRunnable:
        """Acessa um passo específico da sequência."""
        return self.steps[index]

    def __iter__(self):
        """Permite iterar sobre os passos."""
        return iter(self.steps)

    @property
    def input_schema(self) -> type:
        """O schema de entrada é o do primeiro runnable."""
        return self.first.input_schema

    @property
    def output_schema(self) -> type:
        """O schema de saída é o do último runnable."""
        return self.last.output_schema

    def __repr__(self) -> str:
        steps_repr = " | ".join(repr(step) for step in self.steps)
        return f"VoiceSequence({steps_repr})"


class VoiceStreamingSequence(VoiceRunnable[Any, Any]):
    """
    Sequência otimizada para streaming end-to-end.

    Diferente de VoiceSequence, esta classe tenta manter o streaming
    através de toda a chain, passando chunks entre os componentes
    assim que eles estão disponíveis.

    Útil para pipelines como ASR -> LLM -> TTS onde queremos
    começar a sintetizar fala assim que tokens do LLM chegam.

    Examples:
        >>> chain = VoiceStreamingSequence([asr, llm, tts])
        >>> async for audio in chain.astream(input_audio):
        ...     # Recebe áudio assim que possível
        ...     play(audio)
    """

    def __init__(
        self,
        steps: list[VoiceRunnable],
        buffer_size: int = 1,
    ):
        """
        Inicializa a sequência de streaming.

        Args:
            steps: Lista de runnables a executar.
            buffer_size: Tamanho do buffer entre passos.
        """
        if not steps:
            raise ValueError("VoiceStreamingSequence precisa de pelo menos um step")
        self.steps = steps
        self.buffer_size = buffer_size

    @property
    def name(self) -> str:
        names = [step.name for step in self.steps]
        return " |> ".join(names)

    async def ainvoke(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> Any:
        """Executa coletando todo o streaming."""
        result = None
        async for chunk in self.astream(input, config):
            result = chunk
        return result

    async def astream(
        self, input: Any, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[Any]:
        """
        Streaming através de toda a chain.

        Para chains com mais de 2 elementos, usa um pipeline
        de produtores/consumidores conectados por queues.
        """
        import asyncio

        config = ensure_config(config)

        if len(self.steps) == 1:
            # Caso trivial: apenas um step
            async for chunk in self.steps[0].astream(input, config):
                yield chunk
            return

        if len(self.steps) == 2:
            # Caso simples: dois steps
            first, second = self.steps
            async for output in self._stream_two(first, second, input, config):
                yield output
            return

        # Caso geral: múltiplos steps conectados por queues
        async for output in self._stream_chain(input, config):
            yield output

    async def _stream_two(
        self,
        first: VoiceRunnable,
        second: VoiceRunnable,
        input: Any,
        config: RunnableConfig,
    ) -> AsyncIterator[Any]:
        """Streaming para exatamente dois steps."""
        import asyncio

        queue: asyncio.Queue = asyncio.Queue(maxsize=self.buffer_size)
        done = asyncio.Event()

        async def producer():
            try:
                async for chunk in first.astream(input, config):
                    await queue.put(chunk)
            finally:
                done.set()

        async def consumer():
            while True:
                try:
                    # Tenta pegar item da queue com timeout
                    chunk = await asyncio.wait_for(queue.get(), timeout=0.1)
                    async for output in second.astream(chunk, config):
                        yield output
                except asyncio.TimeoutError:
                    if done.is_set() and queue.empty():
                        break

        # Inicia produtor em background
        producer_task = asyncio.create_task(producer())

        try:
            async for output in consumer():
                yield output
        finally:
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass

    async def _stream_chain(
        self, input: Any, config: RunnableConfig
    ) -> AsyncIterator[Any]:
        """Streaming para múltiplos steps usando pipeline de queues."""
        import asyncio

        # Cria queues entre cada par de steps
        queues = [
            asyncio.Queue(maxsize=self.buffer_size)
            for _ in range(len(self.steps) - 1)
        ]
        done_events = [asyncio.Event() for _ in range(len(self.steps) - 1)]

        async def stage_runner(
            stage_index: int,
            step: VoiceRunnable,
            input_queue: Optional[asyncio.Queue],
            output_queue: Optional[asyncio.Queue],
            done_event: Optional[asyncio.Event],
            prev_done_event: Optional[asyncio.Event],
        ):
            """Executa um estágio do pipeline."""
            if stage_index == 0:
                # Primeiro estágio: usa input direto
                try:
                    async for chunk in step.astream(input, config):
                        if output_queue:
                            await output_queue.put(chunk)
                finally:
                    if done_event:
                        done_event.set()
            else:
                # Estágios intermediários: lê da queue anterior
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            input_queue.get(), timeout=0.1
                        )
                        async for output in step.astream(chunk, config):
                            if output_queue:
                                await output_queue.put(output)
                    except asyncio.TimeoutError:
                        if prev_done_event and prev_done_event.is_set():
                            if input_queue.empty():
                                break
                if done_event:
                    done_event.set()

        # Cria tasks para todos os estágios exceto o último
        tasks = []
        for i, step in enumerate(self.steps[:-1]):
            input_q = queues[i - 1] if i > 0 else None
            output_q = queues[i]
            done_ev = done_events[i]
            prev_done_ev = done_events[i - 1] if i > 0 else None

            task = asyncio.create_task(
                stage_runner(i, step, input_q, output_q, done_ev, prev_done_ev)
            )
            tasks.append(task)

        # Último estágio: produz output final
        last_step = self.steps[-1]
        last_queue = queues[-1]
        last_done_event = done_events[-1]

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(last_queue.get(), timeout=0.1)
                    async for output in last_step.astream(chunk, config):
                        yield output
                except asyncio.TimeoutError:
                    if last_done_event.is_set() and last_queue.empty():
                        break
        finally:
            # Cancela todas as tasks
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def input_schema(self) -> type:
        return self.steps[0].input_schema

    @property
    def output_schema(self) -> type:
        return self.steps[-1].output_schema

    def __repr__(self) -> str:
        steps_repr = " |> ".join(repr(step) for step in self.steps)
        return f"VoiceStreamingSequence({steps_repr})"
