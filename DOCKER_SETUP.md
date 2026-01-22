# AI Voice Agent - Docker Setup Guide

Este guia explica como iniciar o AI Voice Agent usando Docker Compose para um setup completo em um único comando.

## ⚡ ASR Provider (NOVO - Jan 2026)

O sistema agora suporta **3 providers ASR**:

### ✅ DEFAULT: Distil-Whisper (Recomendado)
- **6x mais rápido** que Whisper (latência ~100ms)
- **WER 8.22% PT-BR** (qualidade excelente)
- **Instalação automática** via `faster-whisper`
- **CPU-only** (não requer GPU)

### 🚀 OPCIONAL: Parakeet TDT (Ultra-Fast GPU)
- **Sub-25ms latency** em GPU
- **WER 6.32%** (melhor accuracy)
- **Requer GPU NVIDIA** + instalação complexa

### 🔧 Configuração

O Docker Compose já está configurado para usar **Distil-Whisper por padrão**:

```yaml
# docker-compose.yml (já configurado)
environment:
  - ASR_PROVIDER=distil-whisper  # ✅ DEFAULT
```

**Não precisa mudar nada!** O sistema irá:
1. Instalar `faster-whisper` automaticamente
2. Baixar modelo `distil-large-v3` na primeira execução
3. Usar CPU (int8 quantization)

---

## 🚀 Quick Start

### 1. Pré-requisitos

- **Docker** (versão 20.10+)
- **Docker Compose** (versão 2.0+)
- **GPU** (opcional, mas recomendado para melhor performance dos modelos AI)
- **8GB+ RAM** recomendado
- **15GB+ espaço em disco** para modelos AI e build de dependências
- **Tempo de build inicial**: 15-30 minutos (compila PJSIP e instala todas as dependências)

### 2. Configuração Inicial

```bash
# Clone o repositório (se ainda não tiver)
git clone <repository-url>
cd ai-voice-agent

# Copie o arquivo de ambiente de exemplo
cp .env.example .env

# Edite o .env se necessário (opcional)
nano .env
```

### 3. Build da Imagem (Primeira Vez)

**IMPORTANTE**: O primeiro build pode demorar 15-30 minutos pois compila o PJSIP do zero e instala todas as dependências.

```bash
# Build da imagem do AI Voice Agent (inclui PJSIP + Kokoro TTS)
docker-compose build voiceagent
```

O que será instalado automaticamente:
- ✅ **PJSIP 2.14.1** com Python bindings (pjsua2) - compilado do source
- ✅ **Kokoro TTS** (onnx) - instalado do GitHub
- ✅ **PyTorch, Transformers, Whisper** - modelos AI
- ✅ **Todas as dependências Python** do requirements-docker.txt

### 4. Iniciar Todos os Serviços

#### Opção A: Serviços Básicos (sem monitoramento)

```bash
docker-compose up -d
```

Isso irá iniciar:
- **Asterisk** (SIP Gateway) na porta 5060
- **AI Voice Agent** (SIP/RTP Server + AI Pipeline) na porta 5080

#### Opção B: Com Monitoramento (Prometheus + Grafana)

```bash
docker-compose --profile monitoring up -d
```

Isso irá iniciar todos os serviços acima mais:
- **Prometheus** (métricas) na porta 9090
- **Grafana** (dashboards) na porta 3000

### 4. Verificar Status

```bash
# Ver todos os containers rodando
docker-compose ps

# Ver logs em tempo real
docker-compose logs -f

# Ver logs de um serviço específico
docker-compose logs -f voiceagent
docker-compose logs -f asterisk
```

## 📊 Acessar os Serviços

### AI Voice Agent

- **SIP Server**: `sip:voiceagent@localhost:5080`
- **Metrics API**: http://localhost:8001/metrics
- **Metrics JSON**: http://localhost:8001/metrics/rtp

### Asterisk (SIP Gateway)

- **SIP Server**: `sip:asterisk@localhost:5060`
- **ARI API**: http://localhost:8088

### Prometheus (se usando perfil monitoring)

- **URL**: http://localhost:9090
- **Targets**: http://localhost:9090/targets
- **Queries**: Execute queries PromQL para visualizar métricas

### Grafana (se usando perfil monitoring)

- **URL**: http://localhost:3000
- **Usuário**: `admin`
- **Senha**: `admin` (ou conforme configurado no docker-compose.yml)
- **Dashboard**: "AI Voice Agent - RTP Metrics"

## 🔧 Configuração Avançada

### Usar CPU ao invés de GPU

Edite o `.env` e remova ou comente a linha:

```bash
# CUDA_VISIBLE_DEVICES=0
CUDA_VISIBLE_DEVICES=
```

### Trocar Modelos AI

Edite o `.env`:

```bash
# ASR Model
WHISPER_MODEL=base  # Options: tiny, base, small, medium, large-v3

# LLM Model
LLM_MODEL=phi-3-mini  # Options: phi-3-mini, mistral-7b, Qwen/Qwen2.5-7B

# TTS Voice
TTS_VOICE=pt_BR-faber-medium
```

### Ajustar Portas RTP

Por padrão o AI Voice Agent usa portas RTP 10200-10300. Se precisar ajustar, edite o `.env`:

```bash
RTP_PORT_START=10200
RTP_PORT_END=10300
```

E também atualize o `docker-compose.yml` na seção `ports` do serviço `voiceagent`.

## 🧪 Testar a Aplicação

### 1. Verificar Health dos Serviços

```bash
# Health check do AI Voice Agent (métricas)
curl http://localhost:8001/metrics

# Health check do Asterisk
docker exec asterisk asterisk -rx "core show version"
```

### 2. Fazer uma Chamada de Teste

Você pode usar qualquer softphone SIP (como Zoiper, Linphone, etc.):

**Configuração do Softphone:**
- **SIP Server**: `localhost:5060`
- **Usuário**: `100` (ou 101, 102)
- **Senha**: `123456`
- **Domínio**: `voiceagent`

**Ligar para o AI Agent:**
- Disque: `1000` (extensão do AI Voice Agent)

### 3. Monitorar Métricas

Se você iniciou com o perfil `monitoring`:

1. Acesse Grafana: http://localhost:3000
2. Login: `admin` / `admin`
3. Navegue até: Dashboards → "AI Voice Agent - RTP Metrics"
4. Você verá 12 painéis com métricas em tempo real:
   - RTP Server Status
   - Active Sessions
   - MOS Score (qualidade de áudio)
   - Round-Trip Time (latência)
   - DTMF Events
   - Packet Loss Rate
   - Jitter
   - Network Throughput

## 🛠️ Comandos Úteis

### Parar Todos os Serviços

```bash
docker-compose down
```

### Parar e Remover Volumes (apaga dados persistentes)

```bash
docker-compose down -v
```

### Rebuild das Imagens

Se você modificou o código ou Dockerfile:

```bash
docker-compose build
docker-compose up -d
```

### Ver Logs de um Container

```bash
docker-compose logs -f voiceagent
docker-compose logs -f asterisk
docker-compose logs -f prometheus
docker-compose logs -f grafana
```

### Entrar no Shell de um Container

```bash
docker exec -it ai-voice-agent bash
docker exec -it asterisk bash
```

### Ver Uso de Recursos

```bash
docker stats
```

## 🐛 Troubleshooting

### Problema: Container não inicia

```bash
# Ver logs de erro
docker-compose logs voiceagent

# Verificar se as portas estão em uso
netstat -tulpn | grep 5060
netstat -tulpn | grep 8001
```

### Problema: Métricas não aparecem no Grafana

1. Verifique se o Prometheus está coletando métricas:
   ```bash
   curl http://localhost:9090/api/v1/query?query=rtp_server_running
   ```

2. Verifique se o AI Voice Agent está expondo métricas:
   ```bash
   curl http://localhost:8001/metrics
   ```

3. Verifique os logs do Prometheus:
   ```bash
   docker logs prometheus
   ```

### Problema: Modelos AI não carregam

Se você está usando GPU, verifique se o NVIDIA Docker está instalado:

```bash
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

Se não tiver GPU ou der erro, use CPU editando o `.env`:

```bash
CUDA_VISIBLE_DEVICES=
```

### Problema: Chamada SIP não conecta

1. Verifique se o Asterisk está rodando:
   ```bash
   docker exec asterisk asterisk -rx "core show version"
   ```

2. Verifique logs do Asterisk:
   ```bash
   docker logs asterisk | grep INVITE
   ```

3. Verifique se as portas estão acessíveis:
   ```bash
   nc -zv localhost 5060
   nc -zuv localhost 5060
   ```

## 📚 Arquitetura Docker

```
┌─────────────────────────────────────────────────────────┐
│                      Docker Host                         │
│                                                           │
│  ┌────────────────┐  ┌─────────────────┐                │
│  │   Asterisk     │←→│  AI Voice Agent │                │
│  │  (SIP Gateway) │  │  (SIP/RTP + AI) │                │
│  │   Port: 5060   │  │   Port: 5080    │                │
│  │   Port: 10000- │  │   Port: 10200-  │                │
│  │        10100   │  │        10300    │                │
│  └───────┬────────┘  └────────┬────────┘                │
│          │                    │                          │
│          │    voip-net       │                          │
│          │  172.20.0.0/16    │                          │
│          │                    │                          │
│  ┌───────┴────────────────────┴────────┐                │
│  │         Monitoring (optional)        │                │
│  │  ┌────────────┐  ┌──────────────┐   │                │
│  │  │ Prometheus │←→│   Grafana    │   │                │
│  │  │ Port: 9090 │  │  Port: 3000  │   │                │
│  │  └────────────┘  └──────────────┘   │                │
│  └──────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────┘
```

## 🔐 Segurança

Para ambiente de produção, certifique-se de:

1. Trocar senhas padrão no `.env`
2. Usar SSL/TLS para SIP (SIPS)
3. Configurar firewall para limitar acesso às portas
4. Usar rede privada para comunicação entre containers
5. Não expor Prometheus/Grafana publicamente sem autenticação

## 📖 Mais Informações

- **Monitoring Stack**: Ver `monitoring/README.md`
- **Métricas Disponíveis**: Ver lista completa em `monitoring/README.md`
- **Configuração Manual**: Ver `README.md` principal para setup sem Docker

## 🤝 Suporte

Se encontrar problemas, verifique:
1. Logs dos containers: `docker-compose logs`
2. Issues do repositório
3. Documentação principal no `README.md`
