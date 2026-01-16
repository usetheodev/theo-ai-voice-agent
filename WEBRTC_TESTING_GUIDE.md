# 🌐 Guia de Teste - WebRTC Browser Phone

**Data**: 2026-01-16
**Status**: ✅ **PRONTO PARA TESTAR!**

---

## 🎉 O QUE FOI IMPLEMENTADO

✅ **Asterisk com WebRTC habilitado**
- TLS/HTTPS na porta 8089
- WebSocket Secure (WSS) transport
- Endpoint `webrtc` configurado
- Browser-Phone interface instalada

✅ **Certificados SSL**
- Certificado auto-assinado gerado
- Válido por 365 dias
- CN=localhost

✅ **Browser-Phone**
- Interface completa copiada
- Servida estaticamente pelo Asterisk
- Acessível via HTTPS

---

## 📱 COMO TESTAR

### **PASSO 1: Abrir o Browser Phone**

Abra seu navegador (Chrome ou Edge recomendado) e acesse:

```
https://localhost:8089
```

**⚠️ IMPORTANTE**: Você verá um aviso de segurança!

---

### **PASSO 2: Aceitar o Certificado Auto-Assinado**

O navegador mostrará algo como:
```
⚠️ Your connection is not private
   NET::ERR_CERT_AUTHORITY_INVALID
```

**Isso é NORMAL e SEGURO para testes locais!**

**Como proceder**:

#### **Chrome/Edge**:
1. Clicar em **"Advanced"** (Avançado)
2. Clicar em **"Proceed to localhost (unsafe)"** (Continuar para localhost)

#### **Firefox**:
1. Clicar em **"Advanced"** (Avançado)
2. Clicar em **"Accept the Risk and Continue"** (Aceitar o Risco e Continuar)

---

### **PASSO 3: Configurar Conta WebRTC**

Quando a página carregar, você verá a interface do Browser Phone.

**Se pedir configuração de conta, use**:

```
┌─────────────────────────────────────┐
│  Account Configuration              │
├─────────────────────────────────────┤
│  Secure WebSocket Server: localhost │
│  WebSocket Port: 8089               │
│  WebSocket Path: /ws                │
│                                     │
│  Full Name: WebRTC User             │
│  Domain: localhost                  │
│                                     │
│  SIP Username: webrtc               │
│  SIP Password: 1234                 │
│                                     │
│  Subscribe to VoiceMail (MWI): OFF  │
│  Chat Engine: SIP                   │
└─────────────────────────────────────┘
```

**Clicar em "Save" (Salvar)**

---

### **PASSO 4: Aguardar Registro**

Após salvar, a página vai recarregar e você deverá ver:

```
Status: ● Registered
```

✅ **SE VIR "Registered"** → Tudo funcionando!
❌ **SE VIR "Unavailable"** → Ver seção Troubleshooting

---

### **PASSO 5: Fazer Chamadas de Teste**

#### **Teste 1: Echo Test (Extensão 100)**

1. Digite `100` no teclado numérico
2. Clique no botão **"Call"** (ou aperte Enter)
3. **Resultado esperado**:
   - Chamada conecta
   - Você ouve sua própria voz com delay (eco)

#### **Teste 2: AI Voice Agent (Extensão 9999)** ⭐

1. Digite `9999`
2. Clique **"Call"**
3. **Resultado esperado**:
   - Chamada conecta
   - Silêncio inicial (AI esperando você falar)
   - Logs Python mostram:
     ```
     📞 New call received!
     ✅ ExternalMedia channel created
     ✅ Call bridged successfully!
     ```

4. **FALE ALGO!** (em português)
5. Aguarde resposta do AI (atualmente apenas logs, AI pipeline não implementado)

---

## 🔍 MONITORAR LOGS

Em outro terminal, rode:

```bash
# Ver todos os logs
cd ~/Projetos/pesquisas/ai-voice-agent
./scripts/logs.sh

# Ver apenas logs do AI Agent
docker-compose logs -f ai-agent | grep -E "(call|channel|bridge|RTP)"

# Ver logs do Asterisk
docker-compose logs -f asterisk | tail -50
```

---

## ⚙️ VERIFICAÇÕES TÉCNICAS

### **Verificar Endpoint WebRTC**
```bash
docker exec asterisk asterisk -rx "pjsip show endpoints" | grep webrtc
```

**Output esperado**:
```
Endpoint:  webrtc                    Unavailable   0 of inf
     InAuth:  webrtc/webrtc
        Aor:  webrtc                 5
  Transport:  transport-wss  wss
```

### **Verificar HTTPS/WSS**
```bash
# Testar HTTPS
curl -k https://localhost:8089

# Deve retornar HTML do Browser-Phone
```

### **Verificar Portas Expostas**
```bash
docker ps --format "table {{.Names}}\t{{.Ports}}" | grep asterisk
```

**Deve mostrar**:
```
asterisk    0.0.0.0:5060->5060/tcp,
            0.0.0.0:5060->5060/udp,
            0.0.0.0:8088->8088/tcp,
            0.0.0.0:8089->8089/tcp,
            0.0.0.0:8090->8080/tcp,
            0.0.0.0:10000-10100->10000-10100/udp
```

---

## 🐛 TROUBLESHOOTING

### **Problema 1: "Connection Refused"**

**Sintoma**: Navegador não consegue conectar em https://localhost:8089

**Solução**:
```bash
# Verificar se Asterisk está rodando
docker-compose ps

# Verificar logs
docker-compose logs asterisk | grep -i error

# Restart
docker-compose restart asterisk
```

---

### **Problema 2: Status "Unavailable" (não registra)**

**Sintoma**: Browser Phone mostra "Unavailable" em vez de "Registered"

**Causas possíveis**:

1. **WebSocket Path incorreto**
   - Verificar que está usando `/ws` (não `/websocket`)

2. **Credenciais incorretas**
   - Username: `webrtc`
   - Password: `1234`

3. **Transport WSS não configurado**
   ```bash
   docker exec asterisk asterisk -rx "pjsip show transports"
   # Deve mostrar "transport-wss"
   ```

**Solução**:
```bash
# Ver logs em tempo real
docker-compose logs -f asterisk | grep -E "(webrtc|WSS|websocket)"
```

---

### **Problema 3: Áudio não funciona**

**Sintoma**: Chamada conecta mas sem áudio

**Causas**:

1. **Permissões do navegador**
   - Verificar se permitiu acesso ao microfone
   - Chrome: ícone de microfone na barra de endereços

2. **Codec negotiation**
   ```bash
   docker exec asterisk asterisk -rx "pjsip show endpoint webrtc"
   # Verificar: allow=opus,ulaw
   ```

3. **DTLS/SRTP**
   - Browser Phone requer DTLS-SRTP
   - Verificar configuração: `media_encryption=dtls`

---

### **Problema 4: Certificado continua aparecendo**

**Sintoma**: Toda vez que abre, pede para aceitar o certificado

**Solução**: Isso é normal com certificados auto-assinados. Para produção, use certificado válido (Let's Encrypt).

---

## 🎯 TESTES AVANÇADOS

### **Teste 1: Verificar Codec Negotiation**

Durante uma chamada ativa:

```bash
docker exec asterisk asterisk -rx "core show channels"
```

Procurar por:
- `opus` → WebRTC usando Opus
- `ulaw`/`alaw` → Transcodificação para AI Agent

### **Teste 2: Monitorar RTP**

```bash
docker exec asterisk asterisk -rx "rtp show stats"
```

### **Teste 3: Ver WebSocket Connections**

```bash
docker exec asterisk asterisk -rx "http show status"
```

---

## 📊 ARQUITETURA DO FLUXO

```
┌─────────────────┐
│  Chrome Browser │
│  localhost:8089 │
└────────┬────────┘
         │ HTTPS
         │ WSS (WebSocket Secure)
         ↓
┌──────────────────────┐
│  Asterisk Container  │
│  172.20.0.10         │
│                      │
│  Port 8089: HTTPS    │
│  Port 8088: ARI      │
│  Port 5060: SIP      │
│                      │
│  Endpoint: webrtc    │
│  Transport: WSS      │
│  Codec: Opus → Alaw  │
└────────┬─────────────┘
         │ ARI + ExternalMedia
         │ RTP (G.711 A-law)
         ↓
┌──────────────────────┐
│  AI Agent Container  │
│  172.20.0.20         │
│                      │
│  Python + ARI Client │
│  RTP Server: 5080    │
└──────────────────────┘
```

---

## ✅ CHECKLIST DE SUCESSO

- [ ] Abriu https://localhost:8089
- [ ] Aceitou certificado auto-assinado
- [ ] Configurou conta WebRTC (user: webrtc, pass: 1234)
- [ ] Status mostra "● Registered"
- [ ] Testou echo (ext 100) e ouviu própria voz
- [ ] Testou AI Agent (ext 9999) e chamada conectou
- [ ] Logs Python mostram "📞 New call received!"
- [ ] Logs Python mostram "✅ Call bridged successfully!"

---

## 🚀 PRÓXIMOS PASSOS

Agora que WebRTC está funcionando:

1. ✅ **FASE 1 COMPLETA**: Asterisk + ARI + WebRTC
2. ⏳ **FASE 2**: Implementar G.711 codec no Python
3. ⏳ **FASE 3**: Integrar Whisper (ASR) + LLM + TTS
4. ⏳ **FASE 4**: Full-duplex + Barge-in

---

## 📸 SCREENSHOTS ESPERADOS

### **1. Aviso de Certificado**
```
⚠️ Your connection is not private
[Advanced] → [Proceed to localhost]
```

### **2. Browser Phone - Registered**
```
┌─────────────────────────┐
│ 📞 Browser Phone        │
│ Status: ● Registered    │
│ User: webrtc            │
└─────────────────────────┘
```

### **3. Durante Chamada**
```
┌─────────────────────────┐
│ 📞 Calling 9999...      │
│ Status: Connected       │
│ Duration: 00:05         │
│ [Hangup]                │
└─────────────────────────┘
```

---

## 📞 SUPORTE

**Logs importantes**:
```bash
# Asterisk
docker-compose logs asterisk | tail -100

# AI Agent
docker-compose logs ai-agent | tail -100

# Ver registros WebRTC
docker exec asterisk asterisk -rx "pjsip show registrations"
```

---

**Status**: ✅ **IMPLEMENTATION COMPLETE!**
**Pronto para testar**: ✅ **SIM!**

🎉 **Abra https://localhost:8089 agora!** 🎉
