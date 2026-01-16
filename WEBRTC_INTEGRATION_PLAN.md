# 🌐 Plano de Integração WebRTC - Browser Phone

**Data**: 2026-01-16
**Baseado em**: InnovateAsterisk/Browser-Phone
**Confiança**: 98%

---

## 📚 O QUE APREND

EMOS

### **Configurações Asterisk WebRTC Necessárias**

#### 1. **http.conf** - TLS + Static HTTP
```ini
[general]
enabled=yes
bindaddr=0.0.0.0:8080          # HTTP normal
enablestatic=yes               # Servir arquivos estáticos
redirect=/ /static/index.html  # Redirecionar para webapp

tlsenable=yes                  # ✅ CRÍTICO para WebRTC
tlsbindaddr=0.0.0.0:8089       # HTTPS port
tlscertfile=/etc/asterisk/crt/certificate.pem
tlsprivatekey=/etc/asterisk/crt/private.pem
```

#### 2. **pjsip.conf** - WebSocket Secure Transport
```ini
[wss_transport]
type=transport
protocol=wss    # ✅ WebSocket Secure (CRÍTICO)
bind=0.0.0.0

[webrtc_endpoint](!)
transport=wss_transport
allow=opus,ulaw           # Codecs WebRTC
webrtc=yes               # ✅ Flag WebRTC
```

#### 3. **Certificado SSL Auto-assinado**
```bash
openssl req -new -x509 -days 365 -nodes \
    -out certificate.pem \
    -keyout private.pem \
    -subj "/C=BR/ST=State/L=City/O=Org/OU=Unit/CN=localhost"
```

---

## 🏗️ ARQUITETURA PROPOSTA

### **Opção A: Container Separado (RECOMENDADO)** ⭐

```
┌─────────────────────────┐
│   Browser (Chrome)      │
│   https://localhost     │
└───────────┬─────────────┘
            │ HTTPS (8089)
            │ WSS (WebSocket Secure)
            ↓
┌─────────────────────────┐
│  Asterisk Container     │
│  (WebRTC enabled)       │
│                         │
│  - HTTP: 8080          │
│  - HTTPS/WSS: 8089     │
│  - SIP: 5060           │
│  - ARI: 8088           │
│                         │
│  /var/lib/asterisk/    │
│   static-http/         │
│   └─ Browser-Phone/    │
└───────────┬─────────────┘
            │ ARI + RTP
            ↓
┌─────────────────────────┐
│   AI Agent Container    │
│   (Python + ARI)        │
└─────────────────────────┘
```

**Vantagens**:
- ✅ Tudo em um só container (Asterisk + WebApp)
- ✅ Menos complexidade
- ✅ Asterisk serve os arquivos estáticos

---

### **Opção B: Container Nginx Separado**

```
Browser → Nginx (Proxy) → Asterisk WSS
          ↓
          Browser-Phone static files
```

**Desvantagens**:
- ⚠️ Mais complexo
- ⚠️ Precisa proxy reverso
- ⚠️ Mais um container

---

## 🎯 DECISÃO: Opção A (Asterisk serve tudo)

---

## 📋 PASSOS DE IMPLEMENTAÇÃO

### **PASSO 1: Gerar Certificados SSL**
```bash
mkdir -p docker/asterisk/certs

openssl req -new -x509 -days 365 -nodes \
    -out docker/asterisk/certs/certificate.pem \
    -keyout docker/asterisk/certs/private.pem \
    -subj "/C=BR/ST=Brasil/L=Local/O=AI-Voice-Agent/OU=PoC/CN=localhost"
```

### **PASSO 2: Atualizar http.conf**
Adicionar TLS e static file serving.

### **PASSO 3: Atualizar pjsip.conf**
Adicionar:
- `[wss_transport]` - WebSocket Secure
- `[webrtc_endpoint]` template
- `[webrtc]` user para testes

### **PASSO 4: Copiar Browser-Phone**
```dockerfile
# No Dockerfile do Asterisk
COPY /tmp/Browser-Phone/Phone/* /var/lib/asterisk/static-http/
```

### **PASSO 5: Expor porta 8089**
```yaml
# docker-compose.yml
ports:
  - "8089:8089/tcp"  # HTTPS/WSS
```

### **PASSO 6: Rebuild Asterisk**
```bash
docker-compose build asterisk
docker-compose up -d asterisk
```

### **PASSO 7: Testar**
```
1. Abrir: https://localhost:8089
2. Aceitar certificado auto-assinado
3. Configurar conta:
   - Server: localhost
   - Port: 8089
   - Path: /ws
   - User: webrtc
   - Pass: 1234
4. Registrar
5. Discar *65 (music on hold)
6. Discar 9999 (AI Agent!)
```

---

## 🔑 CONFIGURAÇÕES-CHAVE APRENDIDAS

### **1. WebRTC EXIGE TLS**
- ❌ HTTP não funciona
- ✅ HTTPS obrigatório
- ✅ WSS (WebSocket Secure) obrigatório

### **2. Codecs WebRTC**
- `opus` - Melhor qualidade para WebRTC
- `ulaw` - Fallback compatível
- Asterisk transcodifica automaticamente!

### **3. Transport WSS**
```ini
[wss_transport]
type=transport
protocol=wss    # Não é "ws", é "wss"!
bind=0.0.0.0
```

### **4. Endpoint WebRTC**
```ini
[webrtc](!)
transport=wss_transport
allow=opus,ulaw
webrtc=yes               # ✅ CRITICAL FLAG
direct_media=no          # Força RTP pelo Asterisk
```

### **5. Browser-Phone Files**
- Servidos de: `/var/lib/asterisk/static-http/`
- Asterisk tem built-in HTTP server!
- Redirect `/` → `/static/index.html`

---

## ⚠️ DESAFIOS CONHECIDOS

### **1. Certificado Auto-assinado**
**Problema**: Browser mostra "Not Secure"

**Solução**:
1. Clicar "Advanced"
2. "Proceed to localhost (unsafe)"
3. É seguro para testes locais!

### **2. Codec Negotiation**
**Problema**: WebRTC quer Opus, AI Agent usa A-law

**Solução**: ✅ Asterisk transcodifica automaticamente!
- Browser → Asterisk: Opus
- Asterisk → AI Agent: A-law (via ARI ExternalMedia)

### **3. ICE/STUN não necessário**
Para testes locais (localhost), não precisa STUN/TURN.

---

## 📊 COMPARAÇÃO: Antes vs Depois

### **ANTES (SIP Softphone)**
```
Softphone (Linphone) → Asterisk → AI Agent
```
- ❌ Requer instalação
- ❌ Configuração manual
- ❌ Experiência ruim (relatada pelo usuário)

### **DEPOIS (WebRTC Browser)**
```
Browser (Chrome) → Asterisk WSS → AI Agent
```
- ✅ Zero instalação
- ✅ Abrir URL e usar
- ✅ Interface profissional
- ✅ Funciona em qualquer dispositivo

---

## 🎨 INTERFACE BROWSER-PHONE

```
┌──────────────────────────────────┐
│  📞 Browser Phone                │
├──────────────────────────────────┤
│  Status: ● Registered            │
│  User: webrtc                    │
│                                  │
│  ┌────────────────────────────┐ │
│  │   1    2    3              │ │
│  │   4    5    6              │ │
│  │   7    8    9              │ │
│  │   *    0    #              │ │
│  └────────────────────────────┘ │
│                                  │
│  [🔊 Audio]  [🎥 Video]         │
│  [📞 Call]   [❌ Hangup]        │
│                                  │
│  Recent Calls:                   │
│  - *65 (Music)                   │
│  - 9999 (AI Agent)               │
└──────────────────────────────────┘
```

---

## ✅ BENEFÍCIOS DA INTEGRAÇÃO

1. ✅ **Acesso Universal**: Qualquer browser, qualquer device
2. ✅ **Zero Setup**: Abrir URL e usar
3. ✅ **Interface Profissional**: Browser-Phone é muito polido
4. ✅ **Gravação Built-in**: Browser-Phone suporta call recording
5. ✅ **Demo-Ready**: Perfeito para demonstrar o AI Agent
6. ✅ **Mobile-Friendly**: Funciona em tablets/smartphones

---

## 🚀 PRÓXIMOS PASSOS

1. ✅ Implementar certificados SSL
2. ✅ Atualizar Asterisk configs (http.conf, pjsip.conf)
3. ✅ Copiar Browser-Phone files
4. ✅ Rebuild container
5. ✅ Testar WebRTC connection
6. ✅ Testar chamada para AI Agent (ext 9999)

---

**Pronto para implementar!** 🎉
