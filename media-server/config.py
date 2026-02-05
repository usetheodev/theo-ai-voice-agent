"""
Configuração do Media Server (SIP Bridge)

Todas as configurações são carregadas de variáveis de ambiente.
Veja .env.example para documentação detalhada de cada variável.
"""

import os
import sys
from dotenv import load_dotenv

# Adiciona shared ao path para imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from shared_config import parse_bool, parse_list

load_dotenv(override=False)  # Não sobrescreve variáveis de ambiente do Docker


# =============================================================================
# CONFIGURAÇÕES DO AI AGENT (WebSocket)
# =============================================================================

AI_AGENT_CONFIG = {
    # URL do servidor WebSocket do AI Agent
    "url": os.getenv("WEBSOCKET_URL", "ws://ai-agent:8765"),

    # Intervalo entre tentativas de reconexão (segundos)
    "reconnect_interval": int(os.getenv("WS_RECONNECT_INTERVAL", "5")),

    # Número máximo de tentativas de reconexão antes de desistir
    "max_reconnect_attempts": int(os.getenv("WS_MAX_RECONNECT_ATTEMPTS", "10")),

    # Intervalo de ping para manter conexão viva (segundos)
    "ping_interval": int(os.getenv("WS_PING_INTERVAL", "30")),

    # Timeout do ping WebSocket (segundos)
    "ping_timeout": int(os.getenv("WS_PING_TIMEOUT", "10")),

    # Timeout para fechar conexão WebSocket (segundos)
    "close_timeout": int(os.getenv("WS_CLOSE_TIMEOUT", "5")),

    # Timeout para iniciar sessão (segundos)
    "session_start_timeout": int(os.getenv("WS_SESSION_START_TIMEOUT", "10")),
}


# =============================================================================
# CONFIGURAÇÕES DO AUDIO SESSION PROTOCOL (ASP)
# =============================================================================

ASP_CONFIG = {
    # Timeout para receber capabilities do servidor (segundos)
    "caps_timeout": float(os.getenv("ASP_CAPS_TIMEOUT", "5.0")),

    # Timeout para aguardar session.started (segundos)
    "session_start_timeout": float(os.getenv("ASP_SESSION_START_TIMEOUT", "10.0")),
}


# =============================================================================
# CONFIGURAÇÕES DO ASTERISK/SIP
# =============================================================================

SIP_CONFIG = {
    # Domínio/IP do servidor SIP (Asterisk)
    "domain": os.getenv("SIP_DOMAIN", "127.0.0.1"),

    # Porta SIP do servidor
    "port": int(os.getenv("SIP_PORT", "5160")),

    # Protocolo de transporte (udp, tcp, tls)
    "transport": os.getenv("SIP_TRANSPORT", "udp"),

    # Nome de usuário/ramal SIP
    "username": os.getenv("SIP_USERNAME", "2000"),

    # Senha do ramal SIP
    "password": os.getenv("SIP_PASSWORD", "ramal2000"),

    # Nome de exibição (Caller ID)
    "display_name": os.getenv("SIP_DISPLAY_NAME", "Agente IA"),

    # Codecs de áudio permitidos (separados por vírgula)
    # Ordem define preferência. Opções: PCMU (G.711 µ-law), PCMA (G.711 A-law), G729, opus
    "codecs": parse_list(os.getenv("SIP_CODECS", ""), ["PCMU", "PCMA"]),

    # Range de portas RTP para mídia
    "rtp_port_start": int(os.getenv("RTP_PORT_START", "40000")),
    "rtp_port_end": int(os.getenv("RTP_PORT_END", "40100")),

    # User-Agent string para identificação SIP
    "user_agent": os.getenv("SIP_USER_AGENT", "PABX-AI-Agent/1.0"),
}


# =============================================================================
# CONFIGURAÇÕES DE ÁUDIO
# =============================================================================

AUDIO_CONFIG = {
    # Taxa de amostragem para telefonia (Hz)
    # 8000 = padrão telefonia, 16000 = wideband
    "sample_rate": int(os.getenv("AUDIO_SAMPLE_RATE", "8000")),

    # Número de canais de áudio (1 = mono, 2 = stereo)
    "channels": int(os.getenv("AUDIO_CHANNELS", "1")),

    # Largura da amostra em bytes (2 = 16-bit PCM)
    "sample_width": int(os.getenv("AUDIO_SAMPLE_WIDTH", "2")),

    # Duração de cada frame RTP em milissegundos
    # 20ms é o padrão para VoIP (160 samples @ 8kHz)
    "frame_duration_ms": int(os.getenv("AUDIO_FRAME_DURATION_MS", "20")),

    # Threshold de silêncio em ms para detectar fim de fala
    # Pausas naturais na fala são 300-500ms. Valores menores = mais responsivo, mais cortes
    "silence_threshold_ms": int(os.getenv("SILENCE_THRESHOLD_MS", "500")),

    # Agressividade do VAD (0-3). 0 = permissivo, 3 = agressivo
    # Valores maiores filtram mais ruído mas podem cortar fala suave
    "vad_aggressiveness": int(os.getenv("VAD_AGGRESSIVENESS", "2")),

    # Duração mínima de fala em ms para ser considerada válida
    # Permite palavras curtas como "sim", "não", "ok" (~200-300ms)
    "min_speech_ms": int(os.getenv("VAD_MIN_SPEECH_MS", "250")),

    # Threshold de energia RMS para fallback VAD (quando webrtcvad não disponível)
    # Valores típicos: 300-800. Ajuste baseado no nível de ruído do ambiente
    "energy_threshold": int(os.getenv("VAD_ENERGY_THRESHOLD", "500")),

    # Tamanho máximo do buffer de envio em bytes
    # 1600 bytes = 100ms de áudio @ 8kHz, 16-bit mono
    "send_buffer_max": int(os.getenv("AUDIO_SEND_BUFFER_MAX", "1600")),

    # Tamanho do ring buffer do VAD em frames
    # Usado para suavização da detecção de fala
    "vad_ring_buffer_size": int(os.getenv("VAD_RING_BUFFER_SIZE", "5")),

    # Taxa mínima de frames com fala para considerar que há fala (0.0 - 1.0)
    # 0.4 = 40% dos frames no ring buffer devem ter fala
    "vad_speech_ratio_threshold": float(os.getenv("VAD_SPEECH_RATIO_THRESHOLD", "0.4")),
}


# =============================================================================
# CONFIGURAÇÕES DE CHAMADA
# =============================================================================

CALL_CONFIG = {
    # Habilitar barge-in (permitir usuário interromper resposta da IA)
    "barge_in_enabled": parse_bool(os.getenv("BARGE_IN_ENABLED", "true"), True),

    # Timeout para aguardar greeting do AI Agent (segundos)
    "greeting_timeout": int(os.getenv("CALL_GREETING_TIMEOUT", "30")),

    # Timeout para aguardar início de sessão de áudio (segundos)
    "session_start_timeout": int(os.getenv("CALL_SESSION_START_TIMEOUT", "60")),

    # Timeout máximo para aguardar playback esvaziar (segundos)
    "playback_drain_timeout": int(os.getenv("CALL_PLAYBACK_DRAIN_TIMEOUT", "10")),

    # Intervalo de verificação do buffer de playback (segundos)
    "playback_check_interval": float(os.getenv("CALL_PLAYBACK_CHECK_INTERVAL", "0.05")),

    # Delay inicial após conexão de mídia antes de iniciar conversação (segundos)
    "media_ready_delay": float(os.getenv("CALL_MEDIA_READY_DELAY", "0.1")),

    # Intervalo do loop de conversação (segundos)
    "conversation_loop_interval": float(os.getenv("CALL_CONVERSATION_LOOP_INTERVAL", "0.05")),
}


# =============================================================================
# CONFIGURAÇÕES PJSIP (Interno)
# =============================================================================

PJSIP_CONFIG = {
    # Clock rate interno do PJSUA2 (Hz)
    # 16000 é o padrão do PJSUA2 para processamento interno
    "internal_clock_rate": int(os.getenv("PJSIP_INTERNAL_CLOCK_RATE", "16000")),

    # Bits por sample para processamento interno
    "internal_bits_per_sample": int(os.getenv("PJSIP_INTERNAL_BITS_PER_SAMPLE", "16")),
}


# =============================================================================
# CONFIGURAÇÕES DE QUALIDADE RTP
# =============================================================================

RTP_QUALITY_CONFIG = {
    # Intervalo esperado entre frames RTP (ms)
    # Deve corresponder ao frame_duration_ms
    "expected_interval_ms": float(os.getenv("RTP_EXPECTED_INTERVAL_MS", "20.0")),

    # Fator multiplicador para detectar gaps (possível packet loss)
    # Gap > intervalo_esperado * fator = possível perda
    "gap_threshold_factor": float(os.getenv("RTP_GAP_THRESHOLD_FACTOR", "1.5")),
}


# =============================================================================
# CONFIGURAÇÕES DE LOG
# =============================================================================

LOG_CONFIG = {
    # Nível de log da aplicação (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    "level": os.getenv("LOG_LEVEL", "INFO"),

    # Nível de log do PJSIP (0-5). 0 = desabilitado, 5 = muito verboso
    "pjsip_log_level": int(os.getenv("PJSIP_LOG_LEVEL", "3")),
}


# =============================================================================
# CONFIGURAÇÕES DE MÉTRICAS
# =============================================================================

METRICS_CONFIG = {
    # Porta do servidor HTTP para métricas Prometheus
    "port": int(os.getenv("METRICS_PORT", "9091")),

    # Habilitar servidor de métricas
    "enabled": parse_bool(os.getenv("METRICS_ENABLED", "true"), True),
}


# =============================================================================
# CONFIGURAÇÕES DO SBC (Session Border Controller)
# =============================================================================

SBC_CONFIG = {
    # Habilitar modo SBC (conexão via SBC externo em vez de Asterisk direto)
    "enabled": parse_bool(os.getenv("SBC_ENABLED", "false"), False),

    # Hostname/IP do SBC
    "host": os.getenv("SBC_HOST", ""),

    # Porta do SBC
    "port": int(os.getenv("SBC_PORT", "5060")),

    # Protocolo de transporte para o SBC (udp, tcp, tls)
    "transport": os.getenv("SBC_TRANSPORT", "udp").lower(),

    # Outbound proxy (opcional, auto-configurado se não definido)
    "outbound_proxy": os.getenv("SBC_OUTBOUND_PROXY", ""),

    # Realm para autenticação SIP (* = qualquer)
    "realm": os.getenv("SBC_REALM", "*"),

    # Habilitar registro SIP no SBC
    "register": parse_bool(os.getenv("SBC_REGISTER", "true"), True),

    # IP público para NAT traversal (opcional)
    "public_ip": os.getenv("SBC_PUBLIC_IP", ""),

    # Intervalo de keep-alive UDP (segundos, 0 = desabilitado)
    "keep_alive_interval": int(os.getenv("SBC_KEEP_ALIVE", "30")),

    # Timeout de registro SIP (segundos)
    "register_timeout": int(os.getenv("SBC_REGISTER_TIMEOUT", "300")),
}


# =============================================================================
# CONFIGURAÇÕES DO AI TRANSCRIBE
# =============================================================================

TRANSCRIBE_CONFIG = {
    # Habilitar envio de audio para transcricao
    "enabled": parse_bool(os.getenv("TRANSCRIBE_ENABLED", "false"), False),

    # URL do servidor WebSocket do AI Transcribe
    "url": os.getenv("TRANSCRIBE_URL", "ws://ai-transcribe:8766"),

    # Intervalo entre tentativas de reconexao (segundos)
    "reconnect_interval": int(os.getenv("TRANSCRIBE_RECONNECT_INTERVAL", "5")),

    # Numero maximo de tentativas de reconexao
    "max_reconnect_attempts": int(os.getenv("TRANSCRIBE_MAX_RECONNECT_ATTEMPTS", "10")),

    # Intervalo de ping para manter conexao viva (segundos)
    "ping_interval": int(os.getenv("TRANSCRIBE_PING_INTERVAL", "30")),

    # Timeout do ping WebSocket (segundos)
    "ping_timeout": int(os.getenv("TRANSCRIBE_PING_TIMEOUT", "10")),

    # Timeout para receber capabilities (segundos)
    "caps_timeout": float(os.getenv("TRANSCRIBE_CAPS_TIMEOUT", "5.0")),
}


# =============================================================================
# CONFIGURAÇÕES DO MEDIA FORK
# =============================================================================

MEDIA_FORK_CONFIG = {
    # Habilitar media forking (isolamento do path de IA)
    # Quando habilitado, o RTP callback nunca bloqueia aguardando IA
    "enabled": parse_bool(os.getenv("MEDIA_FORK_ENABLED", "true"), True),

    # Capacidade do ring buffer em milissegundos de áudio
    # Valores maiores = mais tolerância a latência, mais memória
    # Valores menores = menos latência, mais descarte
    # Recomendado: 500ms (prod), 1000ms (debug), 1500ms (stress test)
    "buffer_ms": int(os.getenv("MEDIA_FORK_BUFFER_MS", "500")),

    # Política de descarte quando buffer cheio
    # "drop_oldest" = descarta frames antigos (recomendado para voz)
    # "drop_newest" = descarta frames novos (não recomendado)
    "drop_policy": os.getenv("MEDIA_FORK_DROP_POLICY", "drop_oldest"),

    # Intervalo de polling do consumer em milissegundos
    # Menor = mais responsivo, mais CPU
    # Maior = menos CPU, mais latência
    "consumer_poll_ms": int(os.getenv("MEDIA_FORK_CONSUMER_POLL_MS", "10")),

    # Backoff exponencial para reconexão do consumer
    # Valores em segundos: inicial, máximo
    "reconnect_initial_s": float(os.getenv("MEDIA_FORK_RECONNECT_INITIAL", "0.1")),
    "reconnect_max_s": float(os.getenv("MEDIA_FORK_RECONNECT_MAX", "5.0")),
    "reconnect_multiplier": float(os.getenv("MEDIA_FORK_RECONNECT_MULTIPLIER", "2.0")),

    # Threshold de lag para alertar (ms)
    # Se consumer_lag > threshold, loga warning
    "lag_warning_threshold_ms": int(os.getenv("MEDIA_FORK_LAG_WARNING_MS", "100")),

    # Habilitar fallback mode quando AI Agent indisponível
    "fallback_enabled": parse_bool(os.getenv("MEDIA_FORK_FALLBACK_ENABLED", "true"), True),

    # Mensagem de fallback (arquivo de áudio ou texto para TTS local)
    "fallback_message": os.getenv(
        "MEDIA_FORK_FALLBACK_MESSAGE",
        "Aguarde um momento, estamos conectando você."
    ),
}
