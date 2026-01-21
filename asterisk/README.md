# Configuração Asterisk - AI Voice Agent

## 📋 Visão Geral

Esta pasta contém as configurações do Asterisk para testar o AI Voice Agent com autenticação digest (SHA-256 + MD5 fallback).

---

## 📁 Estrutura de Arquivos

```
asterisk/
├── configs/
│   ├── pjsip.conf          # Configuração SIP (trunks + endpoints)
│   └── extensions.conf     # Dialplan (extensões de teste)
└── README.md               # Este arquivo
```

---

## 🔧 Configurações Criadas

### 1. Trunk AI Voice Agent (`pjsip.conf`)

**Endpoint:** `ai-agent-trunk`
- **Tipo:** Outbound trunk
- **Codec:** G.711 μ-law (PCMU), A-law (PCMA)
- **Destino:** `sip:agent@127.0.0.1:5061`
- **Autenticação:** Digest (SHA-256 + MD5 fallback)

**Credenciais:**
- **Username:** `carrier_demo`
- **Password:** `demo123`
- **Realm:** `voiceagent`

**Configuração:**
```ini
[ai-agent-trunk]
type=endpoint
context=default
disallow=all
allow=ulaw
allow=alaw
outbound_auth=ai-agent-auth
aors=ai-agent-trunk
direct_media=no
from_user=carrier_demo
from_domain=voiceagent

[ai-agent-auth]
type=auth
auth_type=userpass
username=carrier_demo
password=demo123
realm=voiceagent
```

---

### 2. Extensões de Teste (`extensions.conf`)

| Extensão | Descrição | Uso |
|----------|-----------|-----|
| **7000** | Chamada ao AI Agent com autenticação | Teste principal |
| **7001** | Toca "hello-world" e transfere para AI | Teste de conversação |
| **7002** | Teste de RTP através do AI Agent | Teste de mídia |
| **7777** | Atalho para 7000 | Número curto |

**Exemplo de dialplan (7000):**
```
exten => 7000,1,NoOp(=== Calling AI Voice Agent with Auth ===)
 same => n,Set(CALLERID(name)=Asterisk Test)
 same => n,Dial(PJSIP/agent@ai-agent-trunk,60)
 same => n,Hangup()
```

---

## 🚀 Como Usar

### Opção 1: Asterisk Local

#### 1. Copiar configurações

```bash
sudo cp asterisk/configs/pjsip.conf /etc/asterisk/
sudo cp asterisk/configs/extensions.conf /etc/asterisk/
```

#### 2. Recarregar Asterisk

```bash
sudo asterisk -rx "pjsip reload"
sudo asterisk -rx "dialplan reload"
```

#### 3. Verificar trunk

```bash
sudo asterisk -rx "pjsip show endpoints"
```

**Saída esperada:**
```
Endpoint:  ai-agent-trunk/agent                             Unavailable   0 of inf
    OutAuth:  ai-agent-auth/carrier_demo
```

#### 4. Testar chamada

```bash
sudo asterisk -rx "channel originate Local/7000@default application Milliwatt"
```

---

### Opção 2: Asterisk Docker

#### 1. Copiar configurações para container

```bash
docker cp asterisk/configs/pjsip.conf asterisk:/etc/asterisk/
docker cp asterisk/configs/extensions.conf asterisk:/etc/asterisk/
```

#### 2. Recarregar

```bash
docker exec asterisk asterisk -rx "pjsip reload"
docker exec asterisk asterisk -rx "dialplan reload"
```

#### 3. Testar

```bash
docker exec asterisk asterisk -rx "channel originate Local/7000@default application Milliwatt"
```

---

## 🧪 Testes de Autenticação

### Teste 1: Autenticação Válida ✅

**Objetivo:** Verificar que credenciais corretas autenticam com sucesso

**Comando:**
```bash
# De um softphone registrado no Asterisk
# Discar: 7000

# Ou via CLI
asterisk -rx "channel originate Local/7000@default application Milliwatt"
```

**Resultado esperado:**
- ✅ Asterisk recebe 401 Unauthorized
- ✅ Asterisk reenvia INVITE com Authorization header
- ✅ AI Agent responde 200 OK
- ✅ Chamada conecta
- ✅ Logs do AI Agent mostram: "✅ Authentication successful"

---

### Teste 2: Credenciais Inválidas ❌

**Objetivo:** Verificar que senha errada é rejeitada

**Passos:**
1. Editar `pjsip.conf` temporariamente:
   ```ini
   [ai-agent-auth]
   password=SENHA_ERRADA
   ```

2. Recarregar: `asterisk -rx "pjsip reload"`

3. Tentar chamada: `originate Local/7000@default application Milliwatt`

**Resultado esperado:**
- ✅ Asterisk recebe 401
- ✅ Asterisk tenta autenticar com senha errada
- ✅ AI Agent responde **403 Forbidden**
- ✅ Chamada é REJEITADA
- ✅ Logs mostram: "Authentication failed - Invalid credentials"

---

### Teste 3: Usuário Desconhecido ❌

**Objetivo:** Verificar que usuário inexistente é rejeitado

**Passos:**
1. Criar trunk com usuário inexistente:
   ```ini
   [ai-agent-auth-unknown]
   username=usuario_nao_existe
   password=qualquer
   ```

2. Tentar chamada

**Resultado esperado:**
- ✅ 403 Forbidden
- ✅ Logs: "Authentication failed - unknown user"

---

## 🔍 Debugging

### Verificar Status do Trunk

```bash
asterisk -rx "pjsip show endpoint ai-agent-trunk"
```

### Verificar Autenticação Configurada

```bash
asterisk -rx "pjsip show auth ai-agent-auth"
```

**Saída esperada:**
```
Auth:  ai-agent-auth
    type=userpass
    username=carrier_demo
    realm=voiceagent
```

### Verificar Chamadas Ativas

```bash
asterisk -rx "pjsip show channels"
```

### Aumentar Verbosidade

```bash
asterisk -rx "core set verbose 10"
asterisk -rx "pjsip set logger on"
```

### Capturar Tráfego SIP

```bash
# Na máquina do Asterisk
sudo tcpdump -i lo -w asterisk_sip.pcap port 5060 or port 5061

# Fazer chamada de teste

# Analisar com Wireshark
wireshark asterisk_sip.pcap
```

**Filtro no Wireshark:**
```
sip and (sip.Method == "INVITE" or sip.Status-Code)
```

---

## 📊 Fluxo de Autenticação Esperado

```
┌─────────┐                                  ┌───────────┐
│ Asterisk│                                  │ AI Agent  │
└────┬────┘                                  └─────┬─────┘
     │                                             │
     │  1. INVITE (sem Authorization)              │
     │ ──────────────────────────────────────────> │
     │                                             │
     │  2. 401 Unauthorized                        │
     │     WWW-Authenticate: Digest                │
     │        realm="voiceagent"                   │
     │        nonce="abc123:1234567890"            │
     │        algorithm=SHA-256                    │
     │ <────────────────────────────────────────── │
     │                                             │
     │  3. ACK                                     │
     │ ──────────────────────────────────────────> │
     │                                             │
     │  4. INVITE (com Authorization)              │
     │     Authorization: Digest                   │
     │        username="carrier_demo"              │
     │        response="6629fae49393a..."          │
     │        algorithm=SHA-256                    │
     │ ──────────────────────────────────────────> │
     │                                             │
     │  5. 200 OK ✅                               │
     │     + SDP (RTP port)                        │
     │ <────────────────────────────────────────── │
     │                                             │
     │  6. ACK                                     │
     │ ──────────────────────────────────────────> │
     │                                             │
     │═════════════════════════════════════════════│
     │         RTP Audio (porta 10000+)            │
     │═════════════════════════════════════════════│
```

---

## ⚠️ Notas Importantes

1. **Credenciais Devem Coincidir**
   - As credenciais em `pjsip.conf` devem ser **EXATAMENTE** iguais às de `config/default.yaml` do AI Agent

2. **Realm Correto**
   - O realm deve ser `voiceagent` (configurado no AI Agent)

3. **Porta Correta**
   - AI Agent usa porta **5061** (não 5060)
   - Asterisk usa porta **5060**

4. **Codec Compatível**
   - Certifique-se que `ulaw` ou `alaw` está habilitado em ambos os lados

5. **Firewall**
   - Se estiver testando entre máquinas diferentes, libere portas:
     - 5060/UDP (Asterisk SIP)
     - 5061/UDP (AI Agent SIP)
     - 10000-20000/UDP (RTP)

---

## 🔗 Links Úteis

- **Guia de Teste Completo:** `docs/TESTE_AUTENTICACAO_ASTERISK.md`
- **Script de Teste:** `scripts/test_auth.sh`
- **Manual Testing Guide (EN):** `docs/MANUAL_TESTING_AUTH.md`

---

## ✅ Checklist Rápido

Antes de testar:

- [ ] AI Voice Agent rodando na porta 5061
- [ ] Asterisk rodando
- [ ] Configurações copiadas para `/etc/asterisk/`
- [ ] `pjsip reload` executado
- [ ] `dialplan reload` executado
- [ ] Trunk visível em `pjsip show endpoints`
- [ ] Credenciais corretas (carrier_demo/demo123)

Pronto para testar! 🚀
