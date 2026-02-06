# Theo AI Voice Agent — Technical Review Personas

## Visão Geral

Quatro personas especializadas para revisão técnica profunda do sistema Theo. Cada persona traz experiência de big tech americana e foco em sistemas de voz conversacional realtime. Juntas, cobrem 100% do stack e identificam gaps críticos para transformar o Theo em uma experiência verdadeiramente humanizada.

---

## Persona 1: Maya Chen — Realtime Voice AI Architect

### Background

**Cargo anterior:** Staff Engineer — Google Duplex / Google Assistant (2017-2022), depois Principal Engineer na LiveKit (2022-presente)

**Especialidade:** Arquitetura de sistemas de voz realtime com latência sub-200ms end-to-end. Projetou o pipeline de turn-taking do Google Duplex que fez o mundo acreditar que uma IA estava ligando para marcar consulta. Na LiveKit, arquitetou o protocolo de media routing que alimenta centenas de milhares de sessões simultâneas de voz AI.

**Stack que domina:**
- WebRTC/SIP/RTP internals, SRTP, DTLS, ICE
- Jitter buffer design, packet loss concealment, codec selection (Opus, G.711, Lyra)
- PJSIP/PJSUA2, Opal, Sofia-SIP
- VAD (Voice Activity Detection): Silero, WebRTC VAD, custom energy-based
- Barge-in architectures, echo cancellation, AEC (Acoustic Echo Cancellation)
- Streaming STT (Whisper Streaming, Deepgram, AssemblyAI realtime)
- Streaming TTS (ElevenLabs WebSocket, Cartesia, XTTS streaming)
- Media servers: Janus, mediasoup, LiveKit, Asterisk/FreeSWITCH
- Python asyncio, Rust (tokio), Go para media pipelines
- OpenTelemetry para observabilidade de latência por segmento

### Como Maya Revisa o Theo

Maya olha o Theo e imediatamente abre o cronômetro mental. Para ela, **cada milissegundo entre o usuário parar de falar e ouvir a resposta é a diferença entre "uau, parece humano" e "isso é um robô"**. Ela mede tudo em P95 latency buckets.

### Gaps que Maya Identifica

#### GAP 1: Ausência de Streaming LLM → TTS (CRÍTICO)

**Problema:** O pipeline atual é sequencial — STT completa → LLM gera resposta inteira → TTS converte tudo → envia áudio. Isso é **batch processing disfarçado de realtime**.

**Impacto:** Latência estimada: STT ~500ms + LLM ~1.5s + TTS ~800ms = **~2.8s** de silêncio antes do caller ouvir qualquer coisa. Humanos percebem pausa > 600ms como "a pessoa não entendeu".

**Solução Maya propõe:**
```
STT finaliza → LLM começa a gerar tokens em streaming →
  Cada frase/chunk é enviada ao TTS em streaming →
    TTS gera áudio incrementalmente →
      Áudio é enviado ao caller enquanto LLM ainda gera
```

```python
# Pseudo-código do pipeline streaming que Maya desenharia
async def streaming_pipeline(transcript: str):
    sentence_buffer = ""
    async for token in llm.stream(transcript):
        sentence_buffer += token
        if is_sentence_boundary(sentence_buffer):
            # Envia frase ao TTS enquanto LLM continua gerando
            audio_chunks = tts.stream_synthesis(sentence_buffer)
            async for chunk in audio_chunks:
                await websocket.send(chunk)  # Caller já ouve
            sentence_buffer = ""
```

**Métrica alvo:** Time-to-First-Byte (TTFB) de áudio < 400ms após fim do utterance.

#### GAP 2: Barge-In Incompleto / Não-Graceful

**Problema:** O README menciona barge-in e VAD, mas não descreve o mecanismo de cancelamento de playback. Quando o caller interrompe a IA mid-sentence, o que acontece?

**Perguntas que Maya faz:**
- O TTS playback é cancelado imediatamente ou o buffer RTP continua drenando?
- O LLM recebe contexto de que foi interrompido? (Sabe que o caller não ouviu a frase completa?)
- O STT consegue processar a fala do caller enquanto o TTS ainda está tocando? (Full-duplex ou half-duplex?)
- Há echo cancellation para evitar que o STT transcreva o próprio TTS?

**Solução Maya propõe:**
```
Estado: AI_SPEAKING
  ├── VAD detecta voz do caller
  ├── IMEDIATAMENTE: para de enviar RTP do TTS (zera buffer)
  ├── Marca no contexto do LLM: "[resposta anterior interrompida em: '...transferir para o supo—']"
  ├── Transiciona para: LISTENING
  ├── STT começa a processar novo utterance
  └── Quando STT finaliza → LLM recebe contexto completo incluindo interrupção
```

**Arquitetura de barge-in que Maya propõe:**
```
                    ┌──────────────────────────────────────┐
                    │          Full-Duplex Handler          │
                    │                                      │
  Caller Audio ───► │  ┌─────────┐    ┌──────────────┐    │
  (RTP inbound)     │  │  AEC    │───►│  VAD Engine   │    │
                    │  │ (Echo   │    │  (Silero +    │    │
  TTS Audio ──────► │  │ Cancel) │    │  Energy Gate) │    │
  (reference)       │  └─────────┘    └──────┬───────┘    │
                    │                        │             │
                    │              ┌─────────▼─────────┐   │
                    │              │  Barge-In Control  │   │
                    │              │  ┌───────────────┐ │   │
                    │              │  │ Cancel TTS    │ │   │
                    │              │  │ Flush RTP buf │ │   │
                    │              │  │ Update LLM ctx│ │   │
                    │              │  │ Notify STT    │ │   │
                    │              │  └───────────────┘ │   │
                    │              └────────────────────┘   │
                    └──────────────────────────────────────┘
```

#### GAP 3: Ausência de Comfort Noise / Filler Words

**Problema:** Durante o processamento (STT → LLM → TTS), o caller ouve **silêncio absoluto**. Isso é antinatural — humanos produzem "uhm", "hmm", respiração, enquanto pensam.

**Solução Maya propõe:**
- **Fase 1:** Comfort noise generation (CN) — ruído de fundo leve indicando que a "linha está viva"
- **Fase 2:** Filler words dinâmicos — pré-renderizar áudios de "uhm", "hmm", "deixa eu ver" e injetar quando latência > 500ms
- **Fase 3:** Backchanneling — durante falas longas do caller, inserir "uhum", "entendi" em pausas naturais sem interromper o STT

```python
# Filler injection baseada em latência
async def play_filler_if_slow(processing_start: float):
    await asyncio.sleep(0.5)  # 500ms threshold
    if still_processing:
        filler = random.choice(["uhm.wav", "hmm.wav", "deixa_ver.wav"])
        await play_audio(filler)
```

#### GAP 4: Jitter Buffer e Packet Loss no Leg SIP→Media Server

**Problema:** A comunicação SIP/RTP entre Asterisk e Media Server assume rede perfeita (localhost Docker). Em produção com SBC externo, haverá jitter e packet loss.

**O que falta:**
- Jitter buffer adaptativo no Media Server (PJSUA2 tem, mas precisa tuning)
- PLC (Packet Loss Concealment) para manter qualidade de áudio
- Métricas de QoS: MOS (Mean Opinion Score), jitter, packet loss rate
- RTCP feedback loop para ajustar bitrate

#### GAP 5: Codec Mismatch e Transcoding Desnecessário

**Problema:** O pipeline Asterisk → Media Server → AI Agent pode ter transcoding desnecessário. Se Asterisk negocia G.711 com o caller e o Media Server precisa de PCM 16kHz para Whisper, há uma conversão. Se o TTS gera 24kHz e precisa ir para G.711, há outra.

**Solução:** Negociar Opus end-to-end quando possível (WebRTC já usa). Para SIP trunks G.711, fazer uma única conversão no ponto mais próximo do AI Agent e cachear parâmetros de codec.

### Métricas que Maya Exige

| Métrica | Alvo | Onde Medir |
|---------|------|------------|
| TTFB (Time to First Byte de áudio) | < 400ms | AI Agent → Media Server |
| E2E Latency (fim da fala → início da resposta) | < 800ms | Caller → Caller |
| Barge-in reaction time | < 100ms | VAD trigger → TTS stop |
| STT accuracy (WER) | < 10% | AI Agent metrics |
| Jitter | < 30ms | RTP stream metrics |
| Packet loss | < 1% | RTCP reports |

---

## Persona 2: Marcus Thompson — Telephony & VoIP Systems Engineer

### Background

**Cargo anterior:** Senior Staff Engineer — Twilio Voice (2015-2021), Tech Lead na Vonage/TokBox (2021-2023), agora Staff Engineer na Bandwidth Inc.

**Especialidade:** Infraestrutura de telefonia em escala. Projetou o media pipeline do Twilio que processa bilhões de minutos de voz por mês. Expertise profunda em Asterisk internals, FreeSWITCH, Opal, Opal. Na Vonage, redesenhou o sistema de SBC federation que conecta 1500+ carriers globais. Entende SIP como quem entende HTTP — cada header, cada timer, cada edge case de NAT traversal.

**Stack que domina:**
- Asterisk (source level: `chan_pjsip`, `res_ari`, `res_pjsip`, `app_dial`, `app_queue`)
- FreeSWITCH (`mod_sofia`, ESL, `mod_conference`)
- OPAL, Opal, Opal.io — SIP stacks
- AMI, ARI, AGI — interfaces de controle Asterisk
- SIP RFC 3261, SDP RFC 4566, RTP/RTCP RFC 3550/3551
- SBC: Opal.io, SIPxpress, Opal
- SRTP/ZRTP/DTLS-SRTP
- Opal.io, Opal — OPAL
- Opal: pjsip, opal, opal.io, opal, opal
- Kamailio/OpenSIPS para routing e load balancing SIP
- Homer/HEPv3 para captura e análise de SIP traces
- OPAL, Media Gateway Control Protocol
- Docker networking para VoIP (host network, macvlan, SIP ALG issues)

### Como Marcus Revisa o Theo

Marcus começa ligando o `sngrep` para capturar SIP traces e verificar se o fluxo de sinalização está limpo. Depois analisa o dialplan do Asterisk, as configurações pjsip e verifica race conditions no AMI. Para ele, **a telefonia é o alicerce — se a fundação está errada, nenhum AI do mundo salva a experiência**.

### Gaps que Marcus Identifica

#### GAP 6: Race Condition no AMI Redirect Durante Playback (CRÍTICO)

**Problema:** O fluxo de transferência diz "Media Server aguarda playback terminar → AMI Redirect". Mas como o Media Server sabe que o playback terminou? O AMI Redirect é assíncrono — se o timing estiver errado, o caller ouve a frase cortada no meio.

**Code Smell:**
```python
# PERIGOSO: assumir que send() significa "caller ouviu"
await websocket.send(last_audio_chunk)
await asyncio.sleep(0.1)  # "Espera um pouquinho" ← NÃO É CONFIÁVEL
ami.redirect(channel, context, exten, priority)
```

**Solução Marcus propõe:**
```python
# CORRETO: usar sinalização explícita de fim de playback
class PlaybackTracker:
    def __init__(self):
        self.playback_complete = asyncio.Event()
        self.rtp_drain_complete = asyncio.Event()
    
    async def on_last_rtp_sent(self):
        """Chamado quando o último pacote RTP foi efetivamente enviado ao socket"""
        # Aguarda o playout delay (tempo para o último pacote chegar ao caller)
        jitter_buffer_ms = 60  # Típico para G.711
        await asyncio.sleep(jitter_buffer_ms / 1000)
        self.rtp_drain_complete.set()
    
    async def wait_for_safe_redirect(self):
        await self.rtp_drain_complete.wait()
        # Agora é seguro fazer AMI Redirect
```

#### GAP 7: Caller Channel Discovery Frágil

**Problema:** Para o AMI Redirect funcionar, o Media Server precisa saber o `channel name` do caller no Asterisk (ex: `PJSIP/1004-00000012`). Como ele descobre isso?

**Cenários problemáticos:**
- Se usa `CHANNEL(name)` via variável — funciona, mas e se o channel foi masqueraded (transferência)?
- Se usa `AMI Action: Status` — race condition se outra chamada chega simultaneamente
- Se o channel name muda durante a chamada (Local channels, parking, etc.)

**Solução Marcus propõe:**
```
1. No dialplan, antes de conectar ao Media Server, setar:
   same => n,Set(CHANNEL(THEO_SESSION_ID)=${UNIQUEID})
   
2. Passar UNIQUEID como metadado no SIP INVITE para o Media Server
   (via X-Theo-Session header ou SDP attribute)

3. Media Server armazena mapping: session_id → channel_name

4. Antes de AMI Redirect, fazer AMI Action: Status
   com filter por THEO_SESSION_ID para obter channel name atual
   (resiliente a masquerade)
```

#### GAP 8: Sem SIP Session Timers / Keep-Alive

**Problema:** Chamadas longas com AI podem durar indefinidamente. Sem Session Timers (RFC 4028), o dialog SIP pode ficar "zombie" — o Asterisk acha que a chamada existe mas o Media Server já crashou, ou vice-versa.

**O que falta:**
- `timer=yes` no pjsip.conf para session refresh
- SIP OPTIONS keep-alive entre Asterisk e Media Server
- Watchdog no AI Agent para detectar sessões órfãs (WebSocket aberto sem audio frames por > 30s)

```ini
; pjsip.conf - Adicionar
[media-server]
type=endpoint
timers=yes
timers_min_se=90
timers_sess_expires=1800
```

#### GAP 9: Opal de Call Forking / Opal Channels

**Problema:** O sistema usa Media Fork Manager para copiar áudio. Isso cria um fork de mídia no Asterisk (`MixMonitor` ou `ChanSpy`). Mas:
- O fork é half-duplex ou full-duplex?
- O áudio do fork tem o mesmo sampling rate que o áudio original?
- Se o fork falha (Media Server indisponível), a chamada principal é afetada?

**Design Principle de Marcus:** "A chamada principal NUNCA deve ser afetada por falha no media fork. O fork é observador, não participante. Se o Media Server crashar, o caller deve ouvir MOH e ser redirecionado, não dead air."

#### GAP 10: Docker Networking para VoIP é um Campo Minado

**Problema:** RTP em Docker com bridge networking é problemático:
- Portas RTP (40000-40100) precisam de port mapping 1:1
- SIP ALG em alguns Docker hosts pode reescrever SDP incorretamente
- NAT entre containers pode quebrar RTP se os IPs no SDP não batem

**Recomendação Marcus:**
```yaml
# docker-compose.yml
media-server:
  network_mode: host  # Para produção VoIP
  # OU
  networks:
    voip:
      ipv4_address: 172.20.0.10  # IP fixo, sem NAT
```

#### GAP 11: Sem Opal de Alta Disponibilidade para Asterisk

**Problema:** Single point of failure. Se o Asterisk cai, todas as chamadas caem. Em produção:
- Dois Asterisk em cluster (com Opal/Opal para replicação de estado)
- Ou Kamailio na frente para SIP failover
- Ou usar SIP DNS SRV records para balanceamento

**Mínimo viável Marcus exige:** Health check do Asterisk via AMI ping, com alerta se > 2s sem resposta.

### Métricas que Marcus Exige

| Métrica | Alvo | Onde Medir |
|---------|------|------------|
| SIP INVITE → 200 OK | < 3s | SIP trace (Homer) |
| RTP setup time | < 100ms | Primeiro pacote RTP após SDP answer |
| AMI Redirect execution | < 500ms | AMI response time |
| Opal calls / zombie sessions | 0 | Watchdog periódico |
| Opal fork failure rate | < 0.1% | Asterisk logs |

---

## Persona 3: Dr. Priya Sharma — Conversational AI & NLU Specialist

### Background

**Cargo anterior:** Research Scientist — Amazon Alexa (2016-2020), Senior Applied Scientist — OpenAI Realtime API team (2020-2023), agora Head of Voice AI na Retell.ai

**Especialidade:** Modelos de conversação humana aplicados a sistemas de voz. Na Alexa, trabalhou no turn-taking model que decide quando o usuário terminou de falar (vs. uma pausa natural). Na OpenAI, ajudou a projetar o Realtime API que faz streaming bidirecional de áudio com GPT-4o. Na Retell.ai, construiu a plataforma de voice agents que elimina a sensação de "robô" com técnicas de humanização.

**Stack que domina:**
- LLM prompting para conversação natural (system prompts, few-shot, chain-of-thought)
- Tool Calling / Function Calling em contexto de voz (latência, prioridade, paralelismo)
- Turn-taking models (endpointing, pause detection, interruption handling)
- Streaming STT: Whisper streaming, Deepgram Nova, AssemblyAI Realtime
- Streaming TTS: ElevenLabs, PlayHT, Cartesia Sonic
- Prosody control: SSML, expressividade, ritmo de fala
- Conversation state management (multi-turn, context window, summarization)
- Intent detection e entity extraction em tempo real
- Avaliação de qualidade: CSAT, task completion rate, naturalness MOS
- Python, TypeScript, prompt engineering avançado

### Como Priya Revisa o Theo

Priya não olha código primeiro — ela **liga para o agente** 50 vezes com cenários diferentes e anota cada momento que "quebra a ilusão". Cada pausa longa, cada resposta que ignora o que ela acabou de dizer, cada transferência que não explica o porquê. Para ela, **a tecnologia é meio — o fim é o caller achar que está falando com uma pessoa competente e empática**.

### Gaps que Priya Identifica

#### GAP 12: System Prompt Sem Personalidade Conversacional (CRÍTICO)

**Problema:** O README não menciona o system prompt do LLM. Este é o componente mais importante para humanização. Sem um prompt cuidadosamente desenhado, o LLM vai responder como um chatbot, não como um atendente humano.

**O que falta no prompt:**
```
1. PERSONA: Nome, personalidade, tom de voz
2. CONTEXTO DE VOZ: "Você está em uma ligação telefônica, não um chat"
3. REGRAS DE BREVIDADE: "Respostas curtas, 1-2 frases. Nunca listas ou bullets"
4. RITMO: "Fale como humano — use 'olha', 'então', 'veja bem'"
5. TRATAMENTO DE INTERRUPÇÃO: "Se foi interrompido, reconheça e adapte"
6. ESCALONAMENTO: "Quando transferir vs. quando resolver sozinho"
7. FALLBACK GRACEFUL: "Se não entendeu, não diga 'não entendi' — 
   diga 'me desculpa, a ligação tá ruim, pode repetir?'"
```

**System prompt que Priya propõe:**
```python
SYSTEM_PROMPT = """
Você é a Theo, atendente virtual da [empresa]. Está em uma LIGAÇÃO TELEFÔNICA.

REGRAS ABSOLUTAS DE VOZ:
- Respostas CURTAS: máximo 2 frases por turno. O caller está no telefone, não lendo.
- NUNCA liste opções numeradas. Diga: "posso te ajudar com X, ou se preferir, Y"
- Use linguagem ORAL: "olha", "então", "veja bem", "tá bom"
- Se não entendeu: "desculpa, não peguei bem, pode repetir?"
- Se precisa pensar: "um momento só..." (buying time naturalmente)
- NUNCA diga: "como um assistente de IA" ou "como modelo de linguagem"
- Chame o cliente pelo nome quando souber
- Use contrações: "tá" não "está", "pra" não "para", "né" não "não é"

FLUXO DE CONVERSA:
1. Saudação breve e acolhedora
2. Entender a necessidade (máx 2 perguntas de clarificação)
3. Resolver OU transferir com contexto
4. Despedida natural

TRANSFERÊNCIA:
- Só transfira se REALMENTE não puder resolver
- SEMPRE explique pra onde e por quê antes de transferir
- "Vou te passar pro suporte técnico que vai resolver isso rapidinho, tá?"
- NUNCA transfira sem avisar

INTERRUPÇÃO:
- Se o caller te interromper, PARE imediatamente
- Reconheça: "sim, diz" ou "fala" 
- Adapte sua resposta ao que ele disse, não continue o que ia dizer
"""
```

#### GAP 13: Endpointing Frágil (Quando o Caller Parou de Falar?)

**Problema:** O VAD (Voice Activity Detection) detecta silêncio, mas silêncio ≠ fim de turno. Exemplos:

| Situação | Silêncio | Turno acabou? |
|----------|----------|---------------|
| "Eu quero..." (pensando) | 800ms | NÃO |
| "...transferir para o suporte." | 600ms | SIM |
| "Meu CPF é 123..." (ditando) | 1200ms | NÃO |
| "É isso." | 400ms | SIM |

**Solução Priya propõe — Endpointing Inteligente:**
```python
class SmartEndpointer:
    """
    Combina VAD com análise linguística para decidir
    quando o caller realmente terminou de falar.
    """
    
    def __init__(self):
        self.base_silence_threshold = 0.6  # 600ms base
        self.extended_threshold = 1.5       # 1500ms para ditado
        self.min_threshold = 0.3            # 300ms mínimo
    
    async def should_finalize(self, 
                               transcript: str, 
                               silence_duration: float,
                               is_mid_dictation: bool) -> bool:
        
        # Regra 1: Se está ditando números/dados, espera mais
        if is_mid_dictation or self._looks_like_dictation(transcript):
            return silence_duration > self.extended_threshold
        
        # Regra 2: Se frase parece completa sintaticamente
        if self._is_syntactically_complete(transcript):
            return silence_duration > self.min_threshold
        
        # Regra 3: Se termina com marcador de turno
        turn_markers = ["né", "tá", "entende", "sabe", "é isso"]
        if any(transcript.strip().lower().endswith(m) for m in turn_markers):
            return silence_duration > self.min_threshold
        
        # Default
        return silence_duration > self.base_silence_threshold
    
    def _looks_like_dictation(self, text: str) -> bool:
        """Detecta se o caller está ditando CPF, telefone, etc."""
        import re
        # Muitos números seguidos ou parciais
        numbers = re.findall(r'\d+', text)
        return len(numbers) >= 2
    
    def _is_syntactically_complete(self, text: str) -> bool:
        """Heurística simples de completude sintática"""
        complete_endings = ['.', '!', '?', 'obrigado', 'obrigada', 
                           'valeu', 'tchau', 'é isso', 'só isso']
        return any(text.strip().lower().endswith(e) for e in complete_endings)
```

#### GAP 14: Sem Contexto de Conversa entre Turnos

**Problema:** Se o caller diz "quero falar sobre minha fatura" e depois "a de janeiro", o LLM precisa conectar os dois turnos. Mas como o contexto é gerenciado?

**O que falta:**
- Conversation history management (sliding window? summarization?)
- Entity persistence (o caller disse o nome uma vez — lembrar para sempre na sessão)
- Pós-transferência: se o caller volta do fallback, o que o agente lembra?

**Solução Priya propõe:**
```python
class ConversationMemory:
    def __init__(self, max_turns: int = 20):
        self.turns: list[dict] = []
        self.entities: dict = {}  # nome, cpf, protocolo, etc.
        self.summary: str = ""
        self.interrupted_at: str | None = None
    
    def add_turn(self, role: str, content: str, was_interrupted: bool = False):
        self.turns.append({
            "role": role,
            "content": content,
            "was_interrupted": was_interrupted,
            "timestamp": time.time()
        })
        self._extract_entities(content)
        
        # Summarize older turns para não estourar context window
        if len(self.turns) > self.max_turns:
            self._summarize_oldest()
    
    def get_llm_messages(self) -> list[dict]:
        messages = []
        if self.summary:
            messages.append({
                "role": "system", 
                "content": f"Resumo da conversa até agora: {self.summary}"
            })
        if self.entities:
            messages.append({
                "role": "system",
                "content": f"Dados do cliente: {json.dumps(self.entities, ensure_ascii=False)}"
            })
        for turn in self.turns:
            content = turn["content"]
            if turn.get("was_interrupted"):
                content += " [resposta interrompida pelo cliente]"
            messages.append({"role": turn["role"], "content": content})
        return messages
```

#### GAP 15: Tool Calling Sem Priorização de Latência

**Problema:** Quando o LLM decide usar `transfer_call`, ele precisa primeiro gerar a frase de despedida ("vou te transferir...") E a tool call. Em APIs como Claude/GPT, o tool call vem DEPOIS do texto. Isso significa que o TTS precisa esperar o LLM terminar TODO o output para saber se há uma ação.

**Solução Priya propõe — Parallel Tool Detection:**
```python
async def process_llm_response(stream):
    text_buffer = ""
    tool_call_detected = False
    tool_call_data = None
    
    async for chunk in stream:
        if chunk.type == "text":
            text_buffer += chunk.text
            # Envia texto para TTS em streaming (não espera tool call)
            if is_sentence_boundary(text_buffer):
                await tts.synthesize_streaming(text_buffer)
                text_buffer = ""
        
        elif chunk.type == "tool_use":
            tool_call_detected = True
            tool_call_data = chunk
            # NÃO executa a tool agora — espera o TTS terminar
    
    if tool_call_detected:
        # Agenda execução da tool APÓS último áudio ser entregue
        await playback_tracker.wait_for_safe_action()
        await execute_tool(tool_call_data)
```

#### GAP 16: Sem Métricas de Qualidade Conversacional

**Problema:** O sistema tem métricas de infra (latência STT/LLM/TTS) mas não de qualidade de conversa.

**Métricas que Priya exige:**

| Métrica | O que mede | Como coletar |
|---------|-----------|--------------|
| Task Completion Rate | % de chamadas resolvidas sem transfer | Log de tool calls |
| Avg Turns to Resolution | Quantos turnos até resolver | Conversation history |
| Barge-in Rate | % de respostas interrompidas | VAD events |
| Repeat Rate | Quantas vezes o caller repetiu | STT similarity detection |
| Silence > 2s Rate | % de turnos com pausa longa | Timestamp analysis |
| Transfer Reason Distribution | Por que transferiu | LLM reasoning log |
| Caller Sentiment Trajectory | Sentimento muda ao longo da conversa? | LLM classification por turno |

---

## Persona 4: James Okafor — Distributed Systems & Platform Engineer

### Background

**Cargo anterior:** Staff SRE — Netflix (2014-2019), Principal Engineer — Datadog (2019-2022), agora VP of Engineering na Assembly AI

**Especialidade:** Sistemas distribuídos em escala, observabilidade profunda, e resiliência. Na Netflix, projetou o sistema de chaos engineering para media streaming. Na Datadog, arquitetou o pipeline de ingestão que processa trilhões de eventos por dia. Na AssemblyAI, está escalando a infra de STT realtime para milhões de streams concorrentes.

**Stack que domina:**
- Kubernetes, Docker, containerd — orquestração e runtime
- Prometheus, Grafana, OpenTelemetry — observabilidade completa
- Elasticsearch, Kibana — log aggregation e search
- gRPC, Protocol Buffers, WebSocket — comunicação entre serviços
- Python asyncio, Go — serviços de alta performance
- Redis, NATS, Kafka — message brokers e pub/sub
- PostgreSQL, ClickHouse — storage e analytics
- Circuit breakers, bulkheads, retry policies — resiliência
- Distributed tracing (Jaeger, Zipkin, Tempo)
- Load testing (k6, Locust, Gatling)
- CI/CD (GitHub Actions, ArgoCD)

### Como James Revisa o Theo

James olha o `docker-compose.yml` e o diagrama de componentes e pergunta: "o que acontece quando cada um desses boxes falha?". Depois olha o Prometheus config e pergunta: "essas métricas me acordariam às 3 da manhã antes do sistema cair?". Para ele, **um sistema que não foi projetado para falhar vai falhar da pior forma possível**.

### Gaps que James Identifica

#### GAP 17: Zero Distributed Tracing (CRÍTICO)

**Problema:** O sistema tem Prometheus para métricas, mas **não tem tracing**. Quando uma chamada tem qualidade ruim, como descobrir onde está o gargalo?

**O caminho de uma requisição:**
```
Caller → Asterisk → Media Server → [WebSocket] → AI Agent → STT → LLM → TTS → [WebSocket] → Media Server → Asterisk → Caller
```

Sem tracing, é impossível correlacionar um aumento de latência no LLM com uma degradação na experiência do caller.

**Solução James propõe:**
```python
# Trace ID propagado em TODOS os hops
from opentelemetry import trace
from opentelemetry.context import propagation

tracer = trace.get_tracer("theo-ai-agent")

async def handle_session(websocket, session_data):
    # Extrair trace context do header do WebSocket
    ctx = propagation.extract(session_data.get("headers", {}))
    
    with tracer.start_as_current_span(
        "voice_session",
        context=ctx,
        attributes={
            "session.id": session_data["session_id"],
            "caller.extension": session_data["caller"],
            "agent.type": "ai-voice"
        }
    ) as session_span:
        
        async for audio_frame in websocket:
            with tracer.start_as_current_span("stt.transcribe") as stt_span:
                transcript = await stt.transcribe(audio_frame)
                stt_span.set_attribute("stt.transcript", transcript)
                stt_span.set_attribute("stt.confidence", confidence)
            
            with tracer.start_as_current_span("llm.generate") as llm_span:
                response = await llm.generate(transcript)
                llm_span.set_attribute("llm.tokens", token_count)
                llm_span.set_attribute("llm.tool_calls", has_tools)
            
            with tracer.start_as_current_span("tts.synthesize") as tts_span:
                audio = await tts.synthesize(response)
                tts_span.set_attribute("tts.duration_ms", audio_duration)
```

**Resultado:** Um trace completo no Grafana Tempo/Jaeger mostrando:
```
[voice_session] 12.3s
  ├── [stt.transcribe] 340ms
  ├── [llm.generate] 1.2s
  │     ├── [llm.streaming_first_token] 180ms
  │     └── [llm.tool_call.transfer] 50ms
  ├── [tts.synthesize] 280ms
  │     ├── [tts.first_chunk] 120ms
  │     └── [tts.stream_complete] 280ms
  └── [call.transfer.ami_redirect] 150ms
```

#### GAP 18: Sem Health Checks Adequados

**Problema:** O `docker-compose.yml` provavelmente não tem health checks que reflitam a saúde REAL dos serviços.

**Health checks que James exige:**

```yaml
# docker-compose.yml
ai-agent:
  healthcheck:
    test: ["CMD", "python", "-c", "
      import asyncio, websockets
      async def check():
        async with websockets.connect('ws://localhost:8765') as ws:
          await ws.send('{\"type\":\"health\"}')
          resp = await asyncio.wait_for(ws.recv(), timeout=2)
          assert '\"ok\"' in resp
      asyncio.run(check())
    "]
    interval: 10s
    timeout: 5s
    retries: 3
    start_period: 30s

media-server:
  healthcheck:
    test: ["CMD", "python", "-c", "
      # Verifica: PJSUA2 registrado + AMI conectado + WS disponível
      import requests
      r = requests.get('http://localhost:8080/health')
      data = r.json()
      assert data['pjsua_registered'] == True
      assert data['ami_connected'] == True
      assert data['ws_connected'] == True
    "]
    interval: 10s
    timeout: 5s
    retries: 3

asterisk:
  healthcheck:
    test: ["CMD", "asterisk", "-rx", "core show channels count"]
    interval: 15s
    timeout: 5s
    retries: 3
```

#### GAP 19: Sem Circuit Breaker nos Providers

**Problema:** Se a API do Anthropic/OpenAI ficar lenta ou cair, o que acontece? O AI Agent fica esperando indefinidamente? A chamada fica em silêncio?

**Solução James propõe:**
```python
from circuitbreaker import circuit

class ResilientLLMProvider:
    def __init__(self):
        self.primary = AnthropicProvider()
        self.fallback = LocalLLMProvider()  # Docker Model Runner
        self.emergency_responses = [
            "Estou com uma dificuldade técnica. Posso te transferir para um atendente?",
            "Me desculpa, estou com um problema no sistema. Vou te passar para alguém que pode te ajudar."
        ]
    
    @circuit(failure_threshold=3, recovery_timeout=30)
    async def generate(self, messages: list, tools: list = None) -> str:
        try:
            return await asyncio.wait_for(
                self.primary.generate(messages, tools),
                timeout=5.0  # Hard timeout de 5s
            )
        except (asyncio.TimeoutError, APIError):
            raise  # Circuit breaker registra a falha
    
    async def generate_with_fallback(self, messages, tools=None):
        try:
            return await self.generate(messages, tools)
        except CircuitBreakerError:
            # Primary está em circuit open — usa fallback
            try:
                return await self.fallback.generate(messages, tools)
            except Exception:
                # Tudo falhou — resposta de emergência
                return random.choice(self.emergency_responses)
```

#### GAP 20: Elasticsearch Sem Lifecycle Management

**Problema:** As transcrições vão para o Elasticsearch sem ILM (Index Lifecycle Management). Em produção:
- Índices crescem indefinidamente
- Sem rollover automático
- Sem política de retenção
- Sem snapshot/backup
- Sem autenticação (curl direto na 9200)

**Solução James propõe:**
```json
// ILM Policy
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_size": "10gb",
            "max_age": "7d"
          }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": { "delete": {} }
      }
    }
  }
}
```

#### GAP 21: Sem Load Testing / Capacity Planning

**Problema:** Quantas chamadas simultâneas o sistema aguenta? Ninguém sabe. Sem load testing, a primeira vez que descobre é em produção.

**O que James exige:**
```python
# load_test.py — Simula N chamadas simultâneas
import asyncio
import websockets
import time

async def simulate_call(call_id: int, duration_s: int = 30):
    """Simula uma chamada: envia áudio, recebe respostas"""
    async with websockets.connect("ws://localhost:8765") as ws:
        # Session start
        await ws.send(json.dumps({
            "type": "session.start",
            "session_id": f"load-test-{call_id}",
            "caller": f"load-{call_id}"
        }))
        
        start = time.time()
        while time.time() - start < duration_s:
            # Enviar audio frame simulado (16kHz PCM silence + speech)
            await ws.send(generate_test_audio_frame())
            await asyncio.sleep(0.02)  # 20ms frames
            
            # Coletar métricas de resposta
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=0.1)
                record_metric("response_time", time.time() - start)
            except asyncio.TimeoutError:
                pass

async def load_test(concurrent_calls: int):
    tasks = [simulate_call(i) for i in range(concurrent_calls)]
    await asyncio.gather(*tasks)
    print_metrics_report()

# Rodar: 10, 25, 50, 100 chamadas simultâneas
# Identificar: ponto de degradação, bottleneck, OOM
```

#### GAP 22: Configuração de Segurança

**Problema:** Múltiplas questões de segurança para produção:

| Issue | Risco | Fix |
|-------|-------|-----|
| Senha do ramal no README | Credential leak | `.env` + secrets manager |
| Elasticsearch sem auth | Data exposure | xpack.security + TLS |
| AMI sem TLS | Credential sniffing | stunnel ou AMI over TLS |
| WebSocket sem auth | Unauthorized sessions | Token-based auth no WS handshake |
| API keys no .env | Leak via git | Vault/KMS + runtime injection |
| Sem rate limiting | DoS via chamadas | Max concurrent sessions per source |

---

## Matriz de Priorização

Consolidação dos 22 gaps identificados pelas 4 personas, priorizados por impacto na humanização e esforço de implementação:

### P0 — Sem isso, não é realtime (Sprint 1-2)

| # | Gap | Persona | Esforço |
|---|-----|---------|---------|
| 1 | Streaming LLM → TTS pipeline | Maya | Alto |
| 2 | Barge-in graceful com cancelamento | Maya | Alto |
| 12 | System prompt conversacional | Priya | Baixo |
| 13 | Smart endpointing | Priya | Médio |

### P1 — Diferencia de brinquedo vs. produção (Sprint 3-5)

| # | Gap | Persona | Esforço |
|---|-----|---------|---------|
| 3 | Comfort noise / filler words | Maya | Médio |
| 6 | Race condition AMI redirect | Marcus | Médio |
| 7 | Caller channel discovery robusto | Marcus | Baixo |
| 14 | Contexto de conversa entre turnos | Priya | Médio |
| 15 | Tool calling com priorização | Priya | Médio |
| 17 | Distributed tracing | James | Alto |
| 19 | Circuit breaker nos providers | James | Médio |

### P2 — Profissionaliza para produção (Sprint 6-8)

| # | Gap | Persona | Esforço |
|---|-----|---------|---------|
| 4 | Jitter buffer tuning | Maya | Médio |
| 5 | Codec optimization | Maya | Baixo |
| 8 | SIP session timers | Marcus | Baixo |
| 9 | Media fork failure isolation | Marcus | Médio |
| 10 | Docker networking VoIP | Marcus | Médio |
| 16 | Métricas de qualidade conversacional | Priya | Alto |
| 18 | Health checks adequados | James | Baixo |
| 20 | Elasticsearch ILM | James | Baixo |
| 21 | Load testing framework | James | Médio |
| 22 | Segurança para produção | James | Alto |

### P3 — Escala enterprise (Backlog)

| # | Gap | Persona | Esforço |
|---|-----|---------|---------|
| 11 | Alta disponibilidade Asterisk | Marcus | Alto |

---

## Comandos de Ativação das Personas

Para usar as personas em futuras revisões de código ou decisões arquiteturais:

```
"Maya, revisa o pipeline de áudio deste PR"
→ Foco: latência, streaming, barge-in, codec, jitter

"Marcus, analisa essa mudança no dialplan"
→ Foco: SIP, AMI, race conditions, call flow, networking

"Priya, avalia a experiência conversacional deste agente"
→ Foco: naturalidade, prompt, endpointing, contexto, métricas UX

"James, revisa a infra e resiliência deste deploy"
→ Foco: observability, circuit breakers, health checks, scaling, security
```

---

*Documento gerado para revisão técnica do projeto Theo AI Voice Agent.*
*Personas baseadas em experiência real de big tech americana aplicada ao stack SIP/Asterisk + AI.*