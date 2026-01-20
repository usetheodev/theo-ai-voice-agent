# AI Voice2Voice Module

**Responsabilidade:** Pipeline de IA conversacional (VAD → ASR → LLM → TTS)

---

## 🎯 O Que Este Módulo Faz

O módulo AI Voice2Voice é responsável por:

1. ✅ VAD (Voice Activity Detection) - Detectar quando usuário está falando
2. ✅ ASR (Automatic Speech Recognition) - Converter fala → texto (Whisper)
3. ✅ LLM (Large Language Model) - Gerar resposta inteligente (Qwen2.5)
4. ✅ TTS (Text-to-Speech) - Converter texto → fala (Kokoro)
5. ✅ Gerenciar estado de conversa (histórico, contexto)

---

## 📦 Arquivos

```
ai/
├── README.md           # Este arquivo
├── __init__.py         # Exports públicos
├── pipeline.py         # Voice2VoicePipeline orchestrator (main)
├── vad.py              # Voice Activity Detection
├── asr.py              # ASR (Whisper)
├── llm.py              # LLM (Qwen2.5)
├── tts.py              # TTS (Kokoro)
├── conversation.py     # Conversation state manager
└── prompts.py          # LLM prompts/templates
```

---

## 🔌 Interface Pública

### Voice2VoicePipeline

```python
from src.ai import Voice2VoicePipeline
from src.rtp.stream import AudioStream

# Criar pipeline
pipeline = Voice2VoicePipeline(
    asr_model='openai/whisper-large-v3',
    llm_model='Qwen/Qwen2.5-7B',
    tts_model='kokoro-tts',
    vad_threshold=0.5
)

# Processar chamada (loop infinito até stream fechar)
await pipeline.process_call(stream: AudioStream)

# Fluxo interno:
# 1. Recebe áudio do stream
# 2. VAD detecta fala
# 3. Quando usuário para de falar → ASR
# 4. Texto → LLM
# 5. Resposta → TTS
# 6. Áudio → stream
# 7. Volta para 1
```

---

## 🎤 VAD (Voice Activity Detection)

Detecta quando há voz no áudio (vs silêncio/ruído).

```python
# src/ai/vad.py

class VADDetector:
    """
    Voice Activity Detection usando energia + zero-crossing rate
    """

    def __init__(self, threshold: float = 0.5):
        """
        Args:
            threshold: 0.0 (muito sensível) a 1.0 (pouco sensível)
        """
        self.threshold = threshold
        self.buffer = []

    def is_speech(self, audio_chunk: bytes) -> bool:
        """
        Detecta se chunk contém fala

        Args:
            audio_chunk: PCM 16-bit, 8kHz (160 bytes = 20ms)

        Returns:
            True se detectou fala, False caso contrário
        """
        # Converter bytes → numpy array
        pcm = np.frombuffer(audio_chunk, dtype=np.int16)

        # Calcular energia
        energy = np.sqrt(np.mean(pcm ** 2))

        # Threshold adaptativo
        return energy > self.threshold * 1000  # Ajustar baseado em testes

    def get_speech_segments(
        self,
        audio_chunks: List[bytes],
        min_speech_duration_ms: int = 300
    ) -> List[bytes]:
        """
        Retorna segmentos de áudio que contêm fala

        Args:
            audio_chunks: Lista de chunks (cada 20ms)
            min_speech_duration_ms: Duração mínima de fala

        Returns:
            Lista de segmentos concatenados
        """
        pass
```

**Uso:**

```python
vad = VADDetector(threshold=0.5)

audio_buffer = []
async for chunk in stream.receive():
    if vad.is_speech(chunk):
        audio_buffer.append(chunk)
    else:
        # Silêncio detectado
        if len(audio_buffer) > 0:
            # Usuário parou de falar → processar
            full_audio = b''.join(audio_buffer)
            text = await asr.transcribe(full_audio)
            audio_buffer = []
```

---

## 🗣️ ASR (Automatic Speech Recognition)

Converte fala em texto usando Whisper.

```python
# src/ai/asr.py

class WhisperASR:
    """
    ASR usando OpenAI Whisper
    """

    def __init__(self, model_name: str = 'openai/whisper-large-v3'):
        """
        Args:
            model_name: Modelo do HuggingFace
                - whisper-tiny: Rápido, menos preciso
                - whisper-base: Balanceado
                - whisper-large-v3: Melhor precisão, mais lento
        """
        from transformers import pipeline
        self.model = pipeline('automatic-speech-recognition', model=model_name)

    async def transcribe(self, audio: bytes) -> str:
        """
        Transcreve áudio em texto

        Args:
            audio: PCM 16-bit, 8kHz ou 16kHz

        Returns:
            str: Texto transcrito (vazio se não detectou fala)

        Example:
            asr = WhisperASR()
            text = await asr.transcribe(audio_bytes)
            print(f"User said: {text}")
        """
        # Converter PCM → formato esperado pelo Whisper
        # Whisper espera 16kHz, então resample se necessário
        audio_16khz = self._resample_to_16khz(audio)

        # Transcribe (run in thread pool para não bloquear)
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self.model,
            audio_16khz
        )

        return result['text'].strip()

    def _resample_to_16khz(self, audio: bytes) -> np.ndarray:
        """Resample de 8kHz → 16kHz (Whisper requirement)"""
        pass
```

---

## 🤖 LLM (Large Language Model)

Gera respostas usando Qwen2.5.

```python
# src/ai/llm.py

class Qwen25LLM:
    """
    LLM usando Qwen2.5-7B
    """

    def __init__(self, model_name: str = 'Qwen/Qwen2.5-7B'):
        """
        Args:
            model_name: Modelo do HuggingFace ou local
        """
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            device_map='auto',  # Auto GPU allocation
            torch_dtype='auto'
        )

    async def generate(
        self,
        user_message: str,
        conversation_history: List[dict],
        system_prompt: str = None
    ) -> str:
        """
        Gera resposta do assistente

        Args:
            user_message: Mensagem do usuário
            conversation_history: Histórico de conversa
                [
                    {'role': 'user', 'content': 'Oi'},
                    {'role': 'assistant', 'content': 'Olá! Como posso ajudar?'}
                ]
            system_prompt: Prompt de sistema (opcional)

        Returns:
            str: Resposta do assistente

        Example:
            llm = Qwen25LLM()
            response = await llm.generate(
                user_message='Qual a previsão do tempo hoje?',
                conversation_history=[],
                system_prompt='Você é um assistente prestativo.'
            )
        """
        # Construir prompt
        messages = []

        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})

        messages.extend(conversation_history)
        messages.append({'role': 'user', 'content': user_message})

        # Aplicar template de chat
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        # Generate (run in thread pool)
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            self._generate_sync,
            prompt
        )

        return response

    def _generate_sync(self, prompt: str) -> str:
        """Synchronous generation"""
        inputs = self.tokenizer(prompt, return_tensors='pt').to(self.model.device)

        outputs = self.model.generate(
            **inputs,
            max_new_tokens=256,
            temperature=0.7,
            top_p=0.9,
            do_sample=True
        )

        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Extrair apenas resposta do assistant (remover prompt)
        # ...

        return response
```

---

## 🔊 TTS (Text-to-Speech)

Converte texto em áudio usando Kokoro.

```python
# src/ai/tts.py

class KokoroTTS:
    """
    TTS usando Kokoro
    """

    def __init__(self, model_name: str = 'kokoro-tts', voice: str = 'af_bella'):
        """
        Args:
            model_name: Nome do modelo Kokoro
            voice: Voice ID (af_bella, af_sarah, am_adam, etc.)
        """
        # Carregar modelo Kokoro
        # ...
        self.voice = voice

    async def synthesize(self, text: str) -> bytes:
        """
        Sintetiza texto em áudio

        Args:
            text: Texto para sintetizar

        Returns:
            bytes: PCM 16-bit, 8kHz, mono

        Example:
            tts = KokoroTTS(voice='af_bella')
            audio = await tts.synthesize('Olá, como posso ajudar?')
            await stream.send(audio)
        """
        # Synthesize (run in thread pool)
        import asyncio
        loop = asyncio.get_event_loop()
        audio = await loop.run_in_executor(
            None,
            self._synthesize_sync,
            text
        )

        # Resample para 8kHz se necessário (RTP usa 8kHz)
        audio_8khz = self._resample_to_8khz(audio)

        return audio_8khz

    def _synthesize_sync(self, text: str) -> bytes:
        """Synchronous synthesis"""
        # Kokoro synthesis
        # ...
        pass

    def _resample_to_8khz(self, audio: bytes) -> bytes:
        """Resample para 8kHz (telefonia)"""
        pass
```

---

## 💬 Conversation State Manager

Gerencia histórico e contexto da conversa.

```python
# src/ai/conversation.py

from dataclasses import dataclass
from typing import List
from datetime import datetime

@dataclass
class Message:
    """Mensagem na conversa"""
    role: str  # 'user' | 'assistant'
    content: str
    timestamp: datetime

class ConversationManager:
    """
    Gerencia estado de conversa
    """

    def __init__(self, max_history: int = 10):
        """
        Args:
            max_history: Máximo de mensagens no histórico
        """
        self.history: List[Message] = []
        self.max_history = max_history

    def add_user_message(self, text: str):
        """Adiciona mensagem do usuário"""
        self.history.append(Message(
            role='user',
            content=text,
            timestamp=datetime.now()
        ))
        self._trim_history()

    def add_assistant_message(self, text: str):
        """Adiciona resposta do assistente"""
        self.history.append(Message(
            role='assistant',
            content=text,
            timestamp=datetime.now()
        ))
        self._trim_history()

    def get_history(self) -> List[dict]:
        """
        Retorna histórico no formato do LLM

        Returns:
            [
                {'role': 'user', 'content': 'Oi'},
                {'role': 'assistant', 'content': 'Olá!'}
            ]
        """
        return [
            {'role': msg.role, 'content': msg.content}
            for msg in self.history
        ]

    def _trim_history(self):
        """Mantém apenas últimas N mensagens"""
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def clear(self):
        """Limpa histórico (novo call)"""
        self.history = []
```

---

## 🎭 Pipeline Orchestrator

Conecta todos os componentes.

```python
# src/ai/pipeline.py

class Voice2VoicePipeline:
    """
    Orquestrador do pipeline VAD → ASR → LLM → TTS
    """

    def __init__(
        self,
        asr_model: str,
        llm_model: str,
        tts_model: str,
        vad_threshold: float = 0.5,
        system_prompt: str = None
    ):
        self.vad = VADDetector(threshold=vad_threshold)
        self.asr = WhisperASR(model_name=asr_model)
        self.llm = Qwen25LLM(model_name=llm_model)
        self.tts = KokoroTTS(model_name=tts_model)
        self.conversation = ConversationManager()

        self.system_prompt = system_prompt or self._default_prompt()

    def _default_prompt(self) -> str:
        """Prompt padrão do sistema"""
        return """Você é um assistente de voz prestativo e amigável.
Responda de forma concisa e natural, como em uma conversa telefônica.
Mantenha respostas curtas (1-3 frases)."""

    async def process_call(self, stream: AudioStream):
        """
        Main loop: processa chamada até stream fechar

        Workflow:
        1. Recebe áudio → VAD
        2. Quando detecta fala → acumula chunks
        3. Quando detecta silêncio → ASR
        4. Texto → LLM
        5. Resposta → TTS
        6. Áudio → envia para stream
        7. Volta para 1
        """
        from src.common.logging import get_logger
        from src.common.metrics import asr_latency, llm_latency, tts_latency

        logger = get_logger('ai.pipeline')

        audio_buffer = []
        is_speaking = False

        logger.info('Pipeline started')

        try:
            while stream.is_active:
                # 1. Receber chunk de áudio (20ms)
                chunk = await stream.receive()

                # 2. VAD
                has_speech = self.vad.is_speech(chunk)

                if has_speech:
                    # Usuário está falando
                    audio_buffer.append(chunk)
                    is_speaking = True

                elif is_speaking and len(audio_buffer) > 0:
                    # Silêncio após fala → processar
                    logger.info('Speech segment detected', chunks=len(audio_buffer))

                    # Concatenar chunks
                    full_audio = b''.join(audio_buffer)
                    audio_buffer = []
                    is_speaking = False

                    # 3. ASR
                    with asr_latency.time():
                        text = await self.asr.transcribe(full_audio)

                    if not text:
                        logger.debug('No speech detected by ASR')
                        continue

                    logger.info('User said', text=text)
                    self.conversation.add_user_message(text)

                    # 4. LLM
                    with llm_latency.time():
                        response = await self.llm.generate(
                            user_message=text,
                            conversation_history=self.conversation.get_history()[:-1],
                            system_prompt=self.system_prompt
                        )

                    logger.info('Assistant response', text=response)
                    self.conversation.add_assistant_message(response)

                    # 5. TTS
                    with tts_latency.time():
                        audio_response = await self.tts.synthesize(response)

                    # 6. Enviar áudio
                    # Quebrar em chunks de 20ms para enviar
                    chunk_size = 160  # 20ms @ 8kHz
                    for i in range(0, len(audio_response), chunk_size):
                        chunk = audio_response[i:i+chunk_size]
                        await stream.send(chunk)

                    logger.info('Response audio sent', duration_ms=len(audio_response)//16)

        except Exception as e:
            logger.error('Pipeline error', error=str(e))
            raise
        finally:
            logger.info('Pipeline stopped')
            self.conversation.clear()
```

---

## 🧪 Testes

### Teste com Mock AudioStream

```python
# tests/unit/test_ai_pipeline.py
import pytest
from src.ai import Voice2VoicePipeline
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_pipeline_detects_silence():
    """Test: Pipeline não processa silêncio"""

    mock_stream = AsyncMock()
    mock_stream.is_active = True
    mock_stream.receive = AsyncMock(return_value=b'\x00' * 160)  # Silêncio

    pipeline = Voice2VoicePipeline(
        asr_model='mock',
        llm_model='mock',
        tts_model='mock'
    )

    # Process por 1 segundo (50 chunks de 20ms)
    import asyncio
    async def stop_after_1s():
        await asyncio.sleep(1)
        mock_stream.is_active = False

    asyncio.create_task(stop_after_1s())
    await pipeline.process_call(mock_stream)

    # Assert: send não foi chamado (sem fala detectada)
    assert mock_stream.send.call_count == 0
```

---

## 📊 Métricas

```python
# Latências
asr_latency_seconds{quantile="0.5"} 1.2
asr_latency_seconds{quantile="0.95"} 2.5

llm_latency_seconds{quantile="0.5"} 3.8
llm_latency_seconds{quantile="0.95"} 7.2

tts_latency_seconds{quantile="0.5"} 1.5
tts_latency_seconds{quantile="0.95"} 3.0

# Total pipeline latency
voice_pipeline_latency_seconds{quantile="0.5"} 6.5  # ASR+LLM+TTS
voice_pipeline_latency_seconds{quantile="0.95"} 12.7

# VAD
vad_speech_segments_total 123
vad_false_positives_total 5  # Detectou fala mas ASR não retornou nada
```

---

## ⚙️ Configuração

```yaml
ai:
  # ASR
  asr_model: openai/whisper-large-v3  # ou whisper-base (mais rápido)
  asr_language: pt  # Forçar português

  # LLM
  llm_model: Qwen/Qwen2.5-7B
  llm_max_tokens: 256
  llm_temperature: 0.7

  # TTS
  tts_model: kokoro-tts
  tts_voice: af_bella  # af_sarah, am_adam, etc.
  tts_speed: 1.0  # 0.5-2.0

  # VAD
  vad_threshold: 0.5  # 0.0-1.0
  vad_min_speech_duration_ms: 300  # Mínimo 300ms para considerar fala

  # System prompt
  system_prompt: |
    Você é um assistente de voz prestativo.
    Responda de forma concisa (1-3 frases).
```

---

## 🔧 Troubleshooting

### Problema: ASR não detecta fala

**Debug:**
```python
# Salvar áudio para análise manual
with open('debug_audio.pcm', 'wb') as f:
    f.write(full_audio)

# Reproduzir com ffplay
ffplay -f s16le -ar 8000 -ac 1 debug_audio.pcm
```

**Solução:**
- Ajustar VAD threshold (aumentar se muito sensível)
- Verificar se áudio está em formato correto (16-bit PCM)

---

### Problema: LLM muito lento

**Debug:**
```bash
# Verificar métricas
curl http://localhost:8000/metrics | grep llm_latency
```

**Solução:**
- Usar modelo menor (Qwen2.5-3B em vez de 7B)
- Habilitar quantização (4-bit, 8-bit)
- Usar GPU se disponível

```python
# Quantização 4-bit
from transformers import BitsAndBytesConfig

quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16
)

model = AutoModelForCausalLM.from_pretrained(
    model_name,
    quantization_config=quantization_config
)
```

---

## ✅ Checklist de Implementação

- [ ] `pipeline.py` - Voice2VoicePipeline
- [ ] `vad.py` - VAD detector
- [ ] `asr.py` - Whisper ASR
- [ ] `llm.py` - Qwen2.5 LLM
- [ ] `tts.py` - Kokoro TTS
- [ ] `conversation.py` - Conversation manager
- [ ] `prompts.py` - Prompt templates
- [ ] Testes unitários (>80% coverage)
- [ ] Otimização de performance (quantização)
- [ ] Métricas de latência

---

**Status:** 🚧 Em implementação
**Owner:** Time de AI/ML
