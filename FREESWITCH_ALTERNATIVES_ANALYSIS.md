# 🔍 Análise de Alternativas - Problema FreeSWITCH

**Data**: 2026-01-16
**Problema**: Instalação do FreeSWITCH via repositório requer token SignalWire (pago)

---

## 📊 Resumo do Problema

### Erro Encontrado

```
wget -O - https://files.freeswitch.org/repo/deb/debian-release/fsstretch-archive-keyring.asc
HTTP request sent, awaiting response... 401 Unauthorized
Username/Password Authentication Failed.
```

### Causa Raiz

Desde 2023, **FreeSWITCH mudou para modelo de subscrição paga**:
- Pacotes DEB/RPM oficiais requerem **SignalWire Personal Access Token (PAT)**
- PAT é obtido apenas com **SignalWire Enterprise subscription**
- Repositórios públicos gratuitos foram descontinuados

---

## 🎯 Alternativas Analisadas

### Opção 1: ✅ Compilar FreeSWITCH do Código-Fonte (RECOMENDADO)

**Descrição**: Build direto do repositório GitHub

#### Prós
- ✅ **100% gratuito e open-source**
- ✅ Não requer token ou subscrição
- ✅ Controle total sobre módulos instalados
- ✅ Versão mais recente (main/master branch)
- ✅ Funciona em Docker perfeitamente

#### Contras
- ⏱️ Build leva ~15-20 minutos (primeira vez)
- 📦 Imagem Docker maior (~500MB vs ~300MB)
- 🔧 Requer build dependencies

#### Viabilidade
**95% - Altamente viável**

#### Implementação
```dockerfile
FROM debian:bookworm-slim

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git build-essential cmake autoconf automake \
    libtool pkg-config libssl-dev zlib1g-dev \
    libsqlite3-dev libcurl4-openssl-dev \
    libpcre3-dev libspeex-dev libspeexdsp-dev \
    libedit-dev libtiff-dev

# Clone and build FreeSWITCH
RUN git clone --branch v1.10 --depth 1 \
    https://github.com/signalwire/freeswitch.git /usr/src/freeswitch

WORKDIR /usr/src/freeswitch

RUN ./bootstrap.sh && \
    ./configure --enable-core-pgsql-support && \
    make && make install
```

**Tempo de build**: 15-20 min
**Tamanho final**: ~500MB

---

### Opção 2: ✅ Usar Imagem Docker Oficial SignalWire

**Descrição**: Usar imagens pré-buildadas do Docker Hub

#### Prós
- ⚡ Setup instantâneo (pull de imagem)
- ✅ Mantida oficialmente pelo SignalWire
- 📦 Tamanho otimizado
- 🔒 Testada e estável

#### Contras
- ⚠️ Pode exigir token para acesso (não confirmado)
- ⚠️ Menos controle sobre configuração
- 🔄 Dependência de terceiros

#### Viabilidade
**85% - Viável com validação**

#### Implementação
```yaml
# docker-compose.yml
services:
  freeswitch:
    image: signalwire/freeswitch:latest
    # ou: signalwire/freeswitch:1.10.12
    network_mode: host
    volumes:
      - ./freeswitch/config:/etc/freeswitch
```

**Tempo de setup**: 2-3 min
**Tamanho**: ~300MB

**⚠️ Nota**: Precisa validar se requer autenticação

---

### Opção 3: ⚠️ Obter Token SignalWire (Teste Gratuito)

**Descrição**: Registrar em SignalWire para obter PAT de teste

#### Prós
- ✅ Pacotes oficiais otimizados
- ✅ Instalação rápida e tradicional
- ✅ Suporte oficial

#### Contras
- 💰 Pode ter custos após trial
- 🔐 Requer registro e credenciais
- ⏰ Limitação de tempo (trial)
- 🚫 Não sustentável para open-source PoC

#### Viabilidade
**60% - Viável mas não ideal**

#### Implementação
```dockerfile
# Dockerfile com token
ARG SIGNALWIRE_TOKEN
RUN curl -sSL https://freeswitch.org/fsget | \
    bash -s $SIGNALWIRE_TOKEN release install
```

**Custo**: Trial gratuito → depois pago
**Sustentabilidade**: ❌ Baixa

---

### Opção 4: 🔄 Trocar para Asterisk

**Descrição**: Substituir FreeSWITCH por Asterisk (alternativa open-source)

#### Prós
- ✅ 100% gratuito, sem tokens
- ✅ Comunidade enorme e ativa
- ✅ Documentação extensa
- ✅ Pacotes oficiais Debian disponíveis
- ✅ Mais simples para PBX tradicional

#### Contras
- 🔄 Requer mudanças no roadmap
- 📝 Dialplan diferente (sintaxe Asterisk)
- ⚡ Performance inferior para WebRTC/media
- 🎯 Menos flexível que FreeSWITCH

#### Viabilidade
**75% - Viável mas requer adaptação**

#### Implementação
```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y asterisk
```

**Impacto no projeto**: Moderado (2-3 dias de adaptação)
**Compatibilidade com PoC**: ✅ Total

---

### Opção 5: 🔄 Usar Kamailio (SIP Proxy)

**Descrição**: SIP proxy leve + outro softswitch

#### Prós
- ⚡ Extremamente rápido
- ✅ Gratuito e open-source
- 🚀 Altíssima escalabilidade

#### Contras
- ❌ Não é um PBX completo
- ❌ Requer outro componente para media
- 🔧 Mais complexo de configurar
- 📚 Curva de aprendizado maior

#### Viabilidade
**40% - Complexo demais para PoC**

---

## 🏆 Decisão Recomendada

### **Opção 1: Compilar FreeSWITCH do Código-Fonte**

#### Justificativa

1. **Gratuito e Sustentável**
   - Sem custos ou dependências de tokens
   - Alinhado com filosofia open-source da PoC

2. **Tecnicamente Viável**
   - Build automatizado em Docker
   - 15-20 min de build é aceitável para desenvolvimento
   - Uma vez buildado, reutilizável

3. **Controle Total**
   - Podemos escolher exatamente quais módulos incluir
   - Versão sempre atualizada (branch v1.10 stable)

4. **Compatível com Roadmap**
   - Zero mudanças no plano de implementação
   - Mesmas configurações e dialplan
   - RTP direto funciona igual

#### Alternativa de Fallback

Se build from source falhar → **Opção 2** (Docker Hub oficial)
Se imagem Docker falhar → **Opção 4** (trocar para Asterisk)

---

## 📝 Plano de Implementação

### Passo 1: Atualizar Dockerfile

Criar novo Dockerfile que compila do source:

```dockerfile
FROM debian:bookworm-slim as builder

# Build dependencies
RUN apt-get update && apt-get install -y \
    git build-essential cmake autoconf \
    automake libtool pkg-config \
    libssl-dev zlib1g-dev libsqlite3-dev \
    libcurl4-openssl-dev libpcre3-dev \
    libspeexdsp-dev libedit-dev

# Clone FreeSWITCH
WORKDIR /usr/src
RUN git clone --branch v1.10 --depth 1 \
    https://github.com/signalwire/freeswitch.git freeswitch

WORKDIR /usr/src/freeswitch

# Configure and build (only essential modules)
RUN ./bootstrap.sh && \
    ./configure \
        --disable-core-odbc-support \
        --disable-core-pgsql-support \
        --enable-core-odbc-support=no \
    && make && make install

# Final stage (slim image)
FROM debian:bookworm-slim

# Runtime dependencies only
RUN apt-get update && apt-get install -y \
    libsqlite3-0 libcurl4 libpcre3 \
    libspeexdsp1 libedit2 \
    && rm -rf /var/lib/apt/lists/*

# Copy FreeSWITCH from builder
COPY --from=builder /usr/local/freeswitch /usr/local/freeswitch

# Symlinks
RUN ln -sf /usr/local/freeswitch/bin/freeswitch /usr/bin/freeswitch && \
    ln -sf /usr/local/freeswitch/bin/fs_cli /usr/bin/fs_cli

# User and permissions
RUN adduser --disabled-password --gecos "" freeswitch && \
    chown -R freeswitch:freeswitch /usr/local/freeswitch

USER freeswitch
CMD ["freeswitch", "-nonat", "-c"]
```

### Passo 2: Otimizar Build

- Usar multi-stage build para reduzir tamanho final
- Cache de layers Docker para builds incrementais
- Compilar apenas módulos essenciais

### Passo 3: Testar

```bash
cd ai-voice-agent
docker build -t freeswitch-poc docker/freeswitch/
docker run --rm freeswitch-poc freeswitch -version
```

---

## ⏱️ Estimativa de Tempo

| Etapa | Tempo |
|-------|-------|
| Atualizar Dockerfile | 15 min |
| Primeiro build | 20 min |
| Testes | 10 min |
| **Total** | **45 min** |

Builds subsequentes: ~5 min (com cache)

---

## 📊 Comparação de Alternativas

| Critério | Build Source | Docker Hub | Token PAT | Asterisk |
|----------|--------------|------------|-----------|----------|
| **Custo** | ✅ Grátis | ✅ Grátis? | 💰 Pago | ✅ Grátis |
| **Tempo Setup** | ⏱️ 20 min | ⚡ 2 min | ⚡ 2 min | ⚡ 5 min |
| **Sustentabilidade** | ✅ 100% | ⚠️ 80% | ❌ 30% | ✅ 100% |
| **Compatibilidade** | ✅ 100% | ✅ 100% | ✅ 100% | ⚠️ 80% |
| **Controle** | ✅ Total | ⚠️ Médio | ⚠️ Médio | ✅ Total |
| **Complexidade** | ⚠️ Média | ✅ Baixa | ✅ Baixa | ⚠️ Média |
| **Score** | **90%** | **75%** | **50%** | **80%** |

---

## ✅ Decisão Final

### Implementar Opção 1: Build from Source

**Razões**:
1. Alinhamento com princípios open-source
2. Zero dependências externas
3. Custo zero
4. Controle total
5. Sustentável a longo prazo

**Trade-off aceitável**: 20 min de build inicial

---

## 📋 Checklist de Implementação

- [ ] Criar novo Dockerfile com multi-stage build
- [ ] Testar build localmente
- [ ] Atualizar documentação (README)
- [ ] Executar `./scripts/setup.sh` novamente
- [ ] Validar que FreeSWITCH inicia corretamente
- [ ] Testar registro SIP
- [ ] Documentar lições aprendidas

---

**Próximo passo**: Implementar Dockerfile atualizado
