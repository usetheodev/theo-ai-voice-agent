# Integração com SBC (Session Border Controller)

## Fluxo de Arquitetura

```
                                    ┌─────────────────────────────────────────┐
                                    │           NOSSA SOLUÇÃO                 │
┌──────────┐     ┌─────────┐        │  ┌──────────┐    ┌──────────────────┐  │
│   PSTN   │────▶│   SBC   │───────▶│  │ Asterisk │───▶│   Media Server   │  │
│  (ITSP)  │     │(Externo)│  NLB   │  │  (PABX)  │    │   (ramal 2000)   │  │
└──────────┘     └─────────┘        │  └──────────┘    └────────┬─────────┘  │
                                    │       ▲                    │            │
                                    │       │ SIP/RTP            │ WebSocket  │
                                    │       │                    ▼            │
                                    │  ┌────┴─────┐       ┌──────────────┐   │
                                    │  │ Softphone│       │   AI Agent   │   │
                                    │  │ (WebRTC) │       │ (STT+LLM+TTS)│   │
                                    │  └──────────┘       └──────────────┘   │
                                    └─────────────────────────────────────────┘
```

## Princípio de Design: Neutralidade de Origem

O Asterisk **não deve saber nem se importar** se a chamada veio de:
- WebRTC (Softphone)
- SBC (PSTN/ITSP)
- Qualquer outra origem SIP

Toda normalização acontece **na borda**, não no core.

---

## Configuração do Asterisk para SBC

### 1. Trunk SBC (pjsip.conf)

Adicione ao arquivo `asterisk/config/pjsip.conf`:

```ini
;===============================================
; TRUNK SBC - Chamadas Externas
; Identificação por IP (SBC não se registra)
;===============================================

; Identificação do SBC por IP
[sbc-identify]
type=identify
endpoint=sbc-trunk
match=<SBC_IP_1>
match=<SBC_IP_2>
; Adicione todos os IPs do SBC/NLB aqui

; AOR (sem registro - SBC envia direto)
[sbc-trunk]
type=aor
contact=sip:<SBC_IP>:5060
qualify_frequency=30

; Autenticação (se o SBC exigir)
[auth-sbc]
type=auth
auth_type=userpass
username=<SBC_USERNAME>
password=<SBC_PASSWORD>

; Endpoint do SBC
[sbc-trunk]
type=endpoint
context=from-sbc
disallow=all
allow=ulaw
allow=alaw
; Descomente se SBC exigir autenticação:
; auth=auth-sbc
aors=sbc-trunk
; NAT/Media
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes
; Sem ICE/DTLS (SBC já trata)
ice_support=no
media_encryption=no
; Timers
timers=yes
timers_sess_expires=1800
; DTMF
dtmf_mode=rfc4733
; Trust headers do SBC
trust_id_inbound=yes
send_pai=yes
```

### 2. Dialplan para SBC (extensions.conf)

Adicione/modifique o contexto `from-sbc`:

```ini
;===============================================
; CONTEXTO SBC - Chamadas do SBC Externo
; Todas as chamadas do SBC caem aqui
;===============================================
[from-sbc]

; Log de entrada
exten => _X.,1,NoOp(=== CHAMADA DO SBC ===)
 same => n,NoOp(De: ${CALLERID(all)})
 same => n,NoOp(Para: ${EXTEN})
 same => n,Set(__CALL_ORIGIN=sbc)

; Rotear para o Agente IA (ramal 2000)
; Ajuste o pattern conforme seus DIDs
exten => _X.,n,Dial(PJSIP/2000,60,tT)
 same => n,Hangup()

; DID específico (exemplo)
; exten => 551199999999,1,NoOp(DID: ${EXTEN})
;  same => n,Set(__CALL_ORIGIN=sbc)
;  same => n,Dial(PJSIP/2000,60,tT)
;  same => n,Hangup()

; Fallback
exten => h,1,NoOp(=== FIM CHAMADA SBC ===)
```

### 3. Ajustes no RTP (rtp.conf)

Para SBC, ajuste:

```ini
[general]
rtpstart=20000
rtpend=20100
; IMPORTANTE: Desabilitar strictrtp se SBC faz ancoragem de mídia
strictrtp=no
; ICE não é necessário com SBC
icesupport=no
; Jitter buffer
jbenable=yes
jbimpl=adaptive
jbtargetextra=40
jbmaxsize=200
```

---

## Configuração do NLB (Network Load Balancer)

### Requisitos

| Protocolo | Porta | Descrição |
|-----------|-------|-----------|
| UDP | 5160 | SIP Signaling |
| UDP | 20000-20100 | RTP Media |

### Considerações

1. **SIP é stateful** - Use sticky sessions baseado em Call-ID ou IP de origem
2. **RTP segue SIP** - O balanceamento deve garantir que mídia siga a sinalização
3. **Health checks** - Use `OPTIONS` SIP ou TCP probe na porta 5160

### Exemplo AWS NLB

```yaml
# Target Group - SIP
Protocol: UDP
Port: 5160
Health Check:
  Protocol: TCP
  Port: 5160
  Interval: 30s
Stickiness:
  Type: source_ip
  Duration: 3600s

# Target Group - RTP
Protocol: UDP
Port: 20000-20100
```

### Exemplo Kubernetes

```yaml
apiVersion: v1
kind: Service
metadata:
  name: asterisk-sip
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local  # Preserva IP de origem
  ports:
    - name: sip
      port: 5160
      protocol: UDP
    - name: rtp-start
      port: 20000
      protocol: UDP
    - name: rtp-end
      port: 20100
      protocol: UDP
```

---

## Checklist de Validação

### Antes de Habilitar

- [ ] IPs do SBC estão no `match=` do identify
- [ ] Codecs compatíveis (ulaw/alaw)
- [ ] Portas RTP abertas no firewall (20000-20100)
- [ ] NLB configurado com sticky sessions

### Teste de Conectividade

```bash
# No Asterisk - verificar trunk
asterisk -rx "pjsip show endpoint sbc-trunk"

# Verificar se identify está funcionando
asterisk -rx "pjsip show identifies"

# Monitorar chamadas em tempo real
asterisk -rx "pjsip set logger on"
asterisk -rvvvvv
```

### Teste de Chamada

1. Envie INVITE do SBC para o IP do NLB
2. Verifique no Asterisk: `asterisk -rx "core show channels"`
3. Confirme que caiu no contexto `from-sbc`
4. Verifique conexão com Media Server: `asterisk -rx "pjsip show channels"`

---

## Troubleshooting

### Chamada não chega no Asterisk

```bash
# Verificar se porta está escutando
ss -ulnp | grep 5160

# Capturar SIP
tcpdump -i any -n port 5160 -w sip.pcap

# Verificar firewall
iptables -L -n | grep 5160
```

### Chamada chega mas é rejeitada

```bash
# Verificar identify
asterisk -rx "pjsip show identifies"

# Ver logs em tempo real
asterisk -rx "core set verbose 5"
asterisk -rvvvvv
```

### Áudio unidirecional

1. Verificar `direct_media=no` no endpoint
2. Confirmar `rtp_symmetric=yes`
3. Verificar se portas RTP estão abertas
4. Confirmar que `strictrtp=no` se SBC ancora mídia

### Latência alta

1. Verificar jitter buffer em `rtp.conf`
2. Monitorar métricas RTP:
   ```bash
   asterisk -rx "rtp set debug on"
   ```
3. Verificar rota de rede entre NLB e Asterisk

---

## Métricas Recomendadas

### Prometheus

```yaml
# Adicionar ao prometheus.yml
- job_name: 'asterisk'
  static_configs:
    - targets: ['asterisk:8088']  # Se AMI/ARI habilitado
```

### Métricas Críticas

| Métrica | Descrição | Alerta |
|---------|-----------|--------|
| `sip_registrations_total` | Registros SIP | - |
| `calls_from_sbc_total` | Chamadas do SBC | - |
| `call_setup_time_seconds` | Tempo INVITE→200 OK | > 3s |
| `rtp_packet_loss_percent` | Perda de pacotes | > 1% |
| `call_duration_seconds` | Duração das chamadas | - |

---

## Arquitetura de Alta Disponibilidade

### Multi-Node com NLB

```
                    ┌─────────┐
                    │   SBC   │
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │   NLB   │
                    └────┬────┘
              ┌──────────┼──────────┐
              │          │          │
         ┌────▼───┐ ┌────▼───┐ ┌────▼───┐
         │Asterisk│ │Asterisk│ │Asterisk│
         │  Pod 1 │ │  Pod 2 │ │  Pod 3 │
         └────┬───┘ └────┬───┘ └────┬───┘
              │          │          │
              └──────────┼──────────┘
                         │
                    ┌────▼────┐
                    │AI Agent │
                    │ (Pool)  │
                    └─────────┘
```

### Considerações

1. **Estado da chamada** - Usar Redis/DB compartilhado se precisar de failover mid-call
2. **Media Server** - Um por instância Asterisk (ramal 2000 registrado localmente)
3. **AI Agent** - Pool stateless, pode ser compartilhado

---

## Comandos Úteis

### Verificar Trunk

```bash
# Status do endpoint
asterisk -rx "pjsip show endpoint sbc-trunk"

# AOR e contatos
asterisk -rx "pjsip show aor sbc-trunk"

# Identify (mapeamento IP→endpoint)
asterisk -rx "pjsip show identifies"
```

### Monitorar Chamadas

```bash
# Canais ativos
asterisk -rx "core show channels verbose"

# Chamadas SIP ativas
asterisk -rx "pjsip show channels"

# Debug SIP em tempo real
asterisk -rx "pjsip set logger on"
```

### Captura de Tráfego

```bash
# SIP signaling
tcpdump -i any -n port 5160 -w sip.pcap

# RTP media
tcpdump -i any -n portrange 20000-20100 -w rtp.pcap

# Ambos
tcpdump -i any -n '(port 5160) or (portrange 20000-20100)' -w voip.pcap
```

---

## Referências

- [Asterisk PJSIP Trunk Configuration](https://wiki.asterisk.org/wiki/display/AST/PJSIP+Configuration+Sections)
- [NAT and Firewall Issues](https://wiki.asterisk.org/wiki/display/AST/NAT)
- [RTP Configuration](https://wiki.asterisk.org/wiki/display/AST/RTP+Configuration)
