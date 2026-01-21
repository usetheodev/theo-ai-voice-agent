# Browser Phone - Guia de Uso

## 🎯 Configuração Completa

O Browser Phone está completamente configurado e funcionando no container Asterisk.

---

## 📋 Informações de Acesso

### URLs de Acesso

- **Interface Web (HTTPS)**: `https://localhost:8089/`
- **WebSocket**: `wss://localhost:8089/ws`
- **HTTP (ARI)**: `http://localhost:8088/`

### Usuários WebRTC Configurados

| Extensão | Username    | Senha  | Descrição      |
|----------|-------------|--------|----------------|
| 100      | webrtc      | 1234   | WebRTC User    |

### Usuários Softphone (para testes)

| Extensão | Username   | Senha    | Descrição  |
|----------|------------|----------|------------|
| 1000     | testuser   | test123  | Test User  |
| 1001     | alice      | alice123 | Alice      |
| 1002     | bob        | bob123   | Bob        |

---

## 🚀 Como Usar o Browser Phone

### 1. Acesse a Interface Web

Abra seu navegador (Chrome, Firefox, Edge ou Safari) e acesse:

```
https://localhost:8089/
```

**Importante**: Você verá um aviso de certificado SSL inválido (é esperado, pois usamos certificado auto-assinado). Clique em "Avançado" e depois "Prosseguir" ou "Aceitar Risco".

### 2. Configure a Conexão SIP

Na primeira vez que acessar, você precisará configurar:

1. **WebSocket Server**: `wss://localhost:8089/ws`
2. **Username**: `webrtc`
3. **Password**: `1234`
4. **Extension**: `100`
5. **Display Name**: Seu nome (ex: "Meu Nome")

### 3. Registre o SIP

Clique em **"Register"** ou **"Connect"**.

Se tudo estiver correto, você verá:
- Status: **"Registered"** ou **"Online"**
- Ícone verde indicando conexão ativa

### 4. Fazer uma Chamada

#### Opção A: Ligar para Extensão de Teste

Digite uma das extensões de teste:
- `101` - Echo Test (você escuta sua própria voz)
- `102` - Playback Test (ouve mensagens gravadas)
- `103` - Milliwatt Test (tom de 1000Hz)

#### Opção B: Ligar para o AI Voice Agent

Digite:
```
100
```

Isso conectará você ao AI Voice Agent (quando ele estiver rodando).

#### Opção C: Ligar para outro usuário WebRTC

Se você tiver duas abas abertas (uma com `100` e outra com `200`):
- Da extensão 100, disque: `200`
- Da extensão 200, disque: `100`

---

## 🎥 Chamadas de Vídeo

O Browser Phone suporta chamadas de **vídeo** com os codecs:
- **VP8** (Google)
- **H.264** (padrão)

### Como fazer uma chamada de vídeo:

1. Clique no botão **"Video Call"** ou ative vídeo antes de discar
2. Permita acesso à câmera quando o navegador solicitar
3. Disque a extensão desejada

---

## 🔧 Troubleshooting

### Problema: "Failed to connect" ou "Registration Failed"

**Solução**:
1. Verifique se o container está rodando:
   ```bash
   docker ps | grep asterisk
   ```

2. Verifique logs do Asterisk:
   ```bash
   docker logs asterisk
   ```

3. Teste conectividade WebSocket:
   ```bash
   curl -k https://localhost:8089/ws
   ```

### Problema: "Certificate Error" no navegador

**Solução**:
- É esperado! Clique em "Avançado" → "Prosseguir" ou "Aceitar Risco"
- O certificado é auto-assinado (para produção, use Let's Encrypt)

### Problema: Áudio não funciona

**Solução**:
1. Certifique-se de permitir acesso ao microfone quando o navegador solicitar
2. Verifique se o volume não está mutado
3. Teste com a extensão `101` (Echo Test)

### Problema: Vídeo não funciona

**Solução**:
1. Certifique-se de permitir acesso à câmera
2. Verifique se os codecs de vídeo estão habilitados:
   ```bash
   docker exec asterisk asterisk -rx "core show codecs"
   ```
3. Procure por: `vp8`, `h264`

---

## 📊 Verificar Status do Asterisk

### Verificar endpoints registrados:

```bash
docker exec asterisk asterisk -rx "pjsip show endpoints"
```

### Verificar transports ativos:

```bash
docker exec asterisk asterisk -rx "pjsip show transports"
```

### Verificar status HTTP/WebSocket:

```bash
docker exec asterisk asterisk -rx "http show status"
```

### Ver chamadas ativas:

```bash
docker exec asterisk asterisk -rx "core show channels"
```

---

## 🎯 Extensões Disponíveis

| Extensão | Função                          |
|----------|---------------------------------|
| 100      | AI Voice Agent                  |
| 101      | Echo Test                       |
| 102      | Playback Test                   |
| 103      | Milliwatt Test (1000Hz tone)    |
| 1000     | Call user testuser              |
| 1001     | Call user alice                 |
| 1002     | Call user bob                   |

---

## 🔐 Certificados SSL

Os certificados SSL são gerados automaticamente no primeiro startup do container em:

```
/etc/asterisk/keys/asterisk.pem
/etc/asterisk/keys/asterisk.key
```

Para **produção**, substitua por certificados válidos (Let's Encrypt, etc).

---

## 🎛️ Configurações Avançadas

### Arquivos de configuração:

| Arquivo                     | Função                              |
|----------------------------|-------------------------------------|
| `docker/asterisk/config/pjsip.conf`      | Configuração SIP endpoints          |
| `docker/asterisk/config/http.conf`       | Configuração HTTP/HTTPS/WebSocket   |
| `docker/asterisk/config/extensions.conf` | Dialplan (rotas de chamadas)        |
| `docker/asterisk/config/modules.conf`    | Módulos Asterisk carregados         |

### Portas expostas:

| Porta | Protocolo | Função                    |
|-------|-----------|---------------------------|
| 5060  | UDP/TCP   | SIP Signaling             |
| 8088  | TCP       | HTTP (ARI)                |
| 8089  | TCP       | HTTPS/WSS (WebRTC)        |
| 10000-10100 | UDP | RTP Media (Asterisk)      |

---

## ✅ Checklist de Configuração

- [x] Asterisk rodando com suporte WebRTC
- [x] Browser Phone servido via HTTPS
- [x] Certificados SSL gerados
- [x] Transport WSS configurado (porta 8089)
- [x] Endpoints WebRTC configurados (100, 200)
- [x] Codecs de áudio habilitados (Opus, ulaw)
- [x] Codecs de vídeo habilitados (VP8, H.264)
- [x] Dialplan configurado
- [x] Extensões de teste funcionando

---

## 📚 Documentação Adicional

- **Browser Phone GitHub**: https://github.com/InnovateAsterisk/Browser-Phone
- **Asterisk WebRTC**: https://wiki.asterisk.org/wiki/display/AST/WebRTC
- **PJSIP Configuration**: https://wiki.asterisk.org/wiki/display/AST/Configuring+res_pjsip

---

## 🆘 Suporte

Para problemas ou dúvidas:

1. Verifique os logs: `docker logs asterisk`
2. Entre no CLI do Asterisk: `docker exec -it asterisk asterisk -r`
3. Consulte a documentação oficial

---

**Status**: ✅ **CONFIGURAÇÃO BÁSICA COMPLETA E FUNCIONAL**
