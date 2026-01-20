# AI Voice Agent - Modular SIP System

**Versão:** 1.0.0
**Python:** 3.10+
**Arquitetura:** Modular + Event-Driven

---

## 🎯 Visão Geral

Sistema modular de voice agent que conecta telefonia tradicional (SIP) com IA conversacional.

**✅ Status Atual:**
- [x] Asterisk configurado com WebRTC (Browser-Phone)
- [x] Softphone support (PJSIP UDP)
- [x] SSL Certificates autoassinados
- [x] Dialplan com extensões de teste (100-103, 1000-1002)
- [ ] SIP Server (Python) - TODO
- [ ] RTP Server (Python) - TODO
- [ ] AI Pipeline (VAD, ASR, LLM, TTS) - TODO

### Componentes Principais

```
┌─────────────────┐
│  SIP SERVER     │ → Aceita chamadas SIP, autentica, negocia codecs
└────────┬────────┘
         │ Event: call_established
         ↓
┌─────────────────┐
│  RTP SERVER     │ → Processa streams de áudio (RTP/RTCP)
└────────┬────────┘
         │ Interface: AudioStream
         ↓
┌─────────────────┐
│  AI VOICE2VOICE │ → VAD → ASR → LLM → TTS
└─────────────────┘
```

---

## 📁 Estrutura do Projeto

```
ai-voice-agent/
├── src/
│   ├── sip/          # Módulo: SIP Server (signaling)
│   ├── rtp/          # Módulo: RTP Server (media)
│   ├── ai/           # Módulo: AI Pipeline (voice2voice)
│   ├── orchestrator/ # Orquestração entre módulos
│   └── common/       # Utilitários compartilhados
├── tests/
│   ├── unit/         # Testes unitários por módulo
│   ├── integration/  # Testes de integração
│   └── fixtures/     # Dados de teste
├── config/           # Arquivos de configuração YAML
└── docs/             # Documentação adicional
```

---

## 🚀 Quick Start

### Opção 1: Browser-Phone (WebRTC) - Recomendado para testes

```bash
# Start Asterisk com Browser-Phone integrado
./scripts/start_browser_phone.sh

# Instalar CA certificate no navegador:
#   asterisk/certs/ca.crt

# Acessar Browser-Phone:
https://localhost:8089/

# Credenciais WebRTC (Extension 100):
#   Username: webuser
#   Password: webpass
#   WebSocket: wss://localhost:8089/ws
```

📖 **Documentação completa:** [BROWSER_PHONE_SETUP.md](BROWSER_PHONE_SETUP.md)

---

### Opção 2: Softphone Tradicional (UDP)

```bash
# Start Asterisk
docker-compose up -d asterisk

# Configurar softphone (Zoiper/Linphone):
#   Server: <YOUR_IP>:5060
#   Username: testuser
#   Password: test123
```

📖 **Documentação completa:** [SOFTPHONE_SETUP.md](SOFTPHONE_SETUP.md)

---

### Extensões de Teste

| Extensão | Descrição |
|----------|-----------|
| `100` | Chama AI Voice Agent (teste principal) |
| `101` | Echo test (valida áudio bidirecional) |
| `102` | Playback test (valida Asterisk → Cliente) |
| `103` | Milliwatt test (tom 1000Hz) |

---

### Configuração do AI Agent (TODO - Não implementado)

```bash
# Copiar configuração exemplo
cp config/default.yaml config/local.yaml

# Editar configuração
vim config/local.yaml
```

### Executar

```bash
# Modo desenvolvimento
python src/main.py --config config/local.yaml

# Com Docker
docker-compose up
```

---

## 📚 Documentação dos Módulos

Cada módulo possui documentação detalhada em seu próprio README:

- **[SIP Server](src/sip/README.md)** - Servidor SIP (signaling)
- **[RTP Server](src/rtp/README.md)** - Servidor RTP (media streams)
- **[AI Pipeline](src/ai/README.md)** - Pipeline de IA (VAD/ASR/LLM/TTS)
- **[Orchestrator](src/orchestrator/README.md)** - Orquestração de módulos
- **[Common](src/common/README.md)** - Utilitários compartilhados

---

## 🧪 Testes

```bash
# Todos os testes
pytest

# Testes unitários apenas
pytest tests/unit/

# Testes de integração
pytest tests/integration/

# Com coverage
pytest --cov=src --cov-report=html
```

---

## 🏗️ Arquitetura

### Princípios de Design

1. **Modularidade**: Cada módulo é independente e testável
2. **Event-Driven**: Comunicação desacoplada via EventBus
3. **Interface-Based**: Contratos claros entre módulos
4. **Single Responsibility**: Cada módulo tem uma responsabilidade única
5. **Observability**: Logging estruturado + métricas Prometheus

### Fluxo de Chamada

```
1. User disca → SIP INVITE
2. SIP Server autentica e aceita
3. SIP Server extrai SDP (IP:Port do user)
4. RTP Server cria AudioStream bidirecional
5. AI Pipeline processa áudio em loop:
   - Recebe RTP → decode → VAD
   - Se voz detectada → ASR (Whisper)
   - Texto → LLM (Qwen2.5)
   - Resposta → TTS (Kokoro)
   - Áudio → encode → envia RTP
6. Loop continua até BYE
```

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para detalhes completos.

---

## 🔧 Configuração

### config/default.yaml

```yaml
sip:
  host: 0.0.0.0
  port: 5060
  realm: voiceagent
  max_concurrent_calls: 100

rtp:
  port_range_start: 10000
  port_range_end: 20000
  codec_priority:
    - PCMU
    - PCMA
    - opus

ai:
  asr_model: openai/whisper-large-v3
  llm_model: Qwen/Qwen2.5-7B
  tts_model: kokoro-tts
  vad_threshold: 0.5
```

---

## 📊 Monitoramento

### Métricas Prometheus

```
# SIP metrics
sip_calls_total{status="accepted|rejected"}
sip_auth_attempts_total{result="success|failed"}

# RTP metrics
rtp_packets_sent_total
rtp_packets_received_total
rtp_packet_loss_percent

# AI metrics
asr_latency_seconds
llm_latency_seconds
tts_latency_seconds
```

Endpoint: `http://localhost:8000/metrics`

### Logs Estruturados

```json
{
  "module": "sip.server",
  "level": "INFO",
  "message": "Call established",
  "session_id": "abc-123",
  "caller_id": "+5511999999999"
}
```

---

## 🔌 Extensibilidade

### Adicionar Novo Provedor ASR

```python
# src/ai/asr.py
from src.ai.base import ASRInterface

class DeepgramASR(ASRInterface):
    async def transcribe(self, audio: bytes) -> str:
        # Implementar integração com Deepgram
        pass

# config/local.yaml
ai:
  asr_provider: deepgram
  asr_model: nova-2
```

### Adicionar Novo Codec

```python
# src/rtp/codec.py
class G729Codec(CodecInterface):
    def encode(self, pcm: bytes) -> bytes:
        # Implementar G.729
        pass

    def decode(self, encoded: bytes) -> bytes:
        pass
```

---

## 🐛 Troubleshooting

### SIP não aceita chamadas

```bash
# Verificar se porta está aberta
sudo netstat -tulpn | grep 5060

# Testar com softphone (Zoiper, Linphone)
sip:test@<server_ip>:5060

# Verificar logs
tail -f logs/sip.log
```

### RTP sem áudio

```bash
# Verificar range de portas RTP
sudo ufw allow 10000:20000/udp

# Capturar pacotes RTP
sudo tcpdump -i any -n udp port 10000

# Verificar codec negociado
grep "codec negotiated" logs/rtp.log
```

### AI Pipeline lento

```bash
# Verificar latência de cada componente
curl http://localhost:8000/metrics | grep latency

# Profile do código
python -m cProfile src/main.py
```

Ver [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) para mais detalhes.

---

## 🤝 Contribuindo

1. Fork o projeto
2. Crie uma branch (`git checkout -b feature/nova-funcionalidade`)
3. Commit suas mudanças (`git commit -am 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Crie um Pull Request

### Guidelines

- Siga PEP 8
- Adicione testes para novas funcionalidades
- Mantenha coverage > 80%
- Documente APIs públicas
- Use type hints

---

## 📄 Licença

MIT License - ver [LICENSE](LICENSE) para detalhes.

---

## 📞 Suporte

- **Issues**: [GitHub Issues](https://github.com/your-repo/issues)
- **Documentação**: [docs/](docs/)
- **Email**: support@voiceagent.com

---

**Desenvolvido com ❤️ usando Python + pjsua2 + Whisper + Qwen2.5 + Kokoro**
