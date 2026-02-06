# PJSIP_ERXOVERFLOW — Diagnóstico e Solução

## Problema

Chamadas WebRTC do softphone para o Asterisk falhavam silenciosamente.
O INVITE era descartado sem resposta (sem 100 Trying, sem erro para o browser).

```
sip_endpoint.c Error processing packet from 10.0.1.1:33628:
Rx buffer overflow (PJSIP_ERXOVERFLOW) [code 171062]
Content-Length: 3632
```

## Causa Raiz

O `mlan/asterisk` usa pjproject com `PJSIP_MAX_PKT_LEN=4000` bytes (padrão).
O SIP INVITE com SDP WebRTC excedia esse limite.

### Por que o SDP era tão grande

O browser gera ICE candidates para **cada interface de rede × cada ICE server**:

| Interface          | IP              | host | srflx (coturn) | srflx (Google) | relay | TCP  |
|--------------------|-----------------|------|----------------|----------------|-------|------|
| voip-network (gw)  | 10.0.1.1        | 1    | 1              | 1              | 1     | 1    |
| docker0            | 10.0.0.1        | 1    | 1              | 1              | 1     | 1    |
| LAN                | 192.168.2.111   | 1    | 1              | 1              | 1     | 1    |
| IPv6               | 2804:c90:...    | 1    | 1              | —              | 1     | 1    |

**Total: 19 candidates × ~120 bytes = ~2280 bytes só de candidates.**
Somado ao restante do SDP (~1350 bytes) = **3632 bytes**.
Com headers SIP (~400 bytes) = **~4032 bytes > 4000 = ERXOVERFLOW**.

### Tentativa que NÃO funcionou: sip.js modifiers

Os `sessionDescriptionHandlerModifiers` do sip.js rodam **ANTES** do ICE gathering:

```
1. createOffer()              → SDP inicial (0 candidates)
2. ► modifiers rodam aqui ◄   → filtra 0 candidates (inútil)
3. setLocalDescription()      → browser inicia ICE gathering
4. ICE gathering completa     → 19 candidates adicionados
5. SDP final enviado          → 3632 bytes → ERXOVERFLOW
```

## Solução: Factory Wrapper no SessionDescriptionHandler

Interceptamos `getDescription()` **DEPOIS** do ICE gathering (passo 5), não antes (passo 2).

### Implementação

```typescript
// softphone/src/hooks/useSIP.ts

import { Web } from 'sip.js'

function createFilteredSDHFactory(): any {
  const defaultFactory = Web.defaultSessionDescriptionHandlerFactory()
  return (session: any, options: any) => {
    const sdh: any = defaultFactory(session, options)

    const originalGetDescription = sdh.getDescription.bind(sdh)
    sdh.getDescription = async function (opts?: any, mods?: any) {
      const result = await originalGetDescription(opts, mods)
      if (result.body) {
        result.body = filterICECandidates(result.body)
      }
      return result
    }

    return sdh
  }
}

// No UserAgent:
const userAgent = new UserAgent({
  sessionDescriptionHandlerFactory: createFilteredSDHFactory(),
  sessionDescriptionHandlerFactoryOptions: { ... },
})
```

### Estratégia do Filtro

| Tipo        | Ação                    | Motivo                                        |
|-------------|-------------------------|-----------------------------------------------|
| TCP         | **Remove todos**        | RTP usa UDP exclusivamente                    |
| IPv6        | **Remove todos**        | Desnecessário em ambiente Docker/dev           |
| host (UDP)  | **Mantém todos**        | Conectividade direta (3 interfaces = 3 cands) |
| srflx       | **Mantém exatamente 1** | ICE connectivity checks validam reachability  |
| relay       | **Mantém exatamente 1** | Fallback TURN — um é suficiente               |

### Resultado

```
ANTES: 19 candidates | SDP: 3632 bytes | INVITE: ~4032 bytes → ERXOVERFLOW
DEPOIS:  5 candidates | SDP: ~1500 bytes | INVITE: ~1900 bytes → OK
```

Candidates mantidos:
```
a=candidate:... udp ... 10.0.1.1   ... typ host    (voip-network gateway)
a=candidate:... udp ... 10.0.0.1   ... typ host    (docker0)
a=candidate:... udp ... 192.168.x  ... typ host    (LAN)
a=candidate:... udp ... 10.0.1.1   ... typ srflx   (reflexivo via coturn STUN)
a=candidate:... udp ... 10.0.0.1   ... typ relay   (TURN relay via coturn)
```

## Configurações Relacionadas

### rtp.conf

```ini
strictrtp=no          ; Obrigatório com bridge networking (NAT)
icesupport=yes
; stunaddr removido  ; external_media_address no pjsip.conf já define o IP
```

`stunaddr=stun.l.google.com:19302` foi removido porque:
- Retorna IP WAN público, inacessível sem port forwarding
- Conflita com `external_media_address` (IP host Docker)
- Gera ICE candidates inúteis no SDP do Asterisk (200 OK)

### pjsip.conf (transport-wss)

```ini
external_media_address=__EXTERNAL_IP__      ; Substituído pelo entrypoint
external_signaling_address=__EXTERNAL_IP__  ; com IP do host Docker
local_net=192.168.0.0/16
local_net=10.0.0.0/8
local_net=127.0.0.0/8
; 172.16.0.0/12 removido: conexões via Docker gateway = externas
```

### Dockerfile.base (PJSIP para media-server)

```dockerfile
CFLAGS="-fPIC -O2 -DPJSIP_MAX_PKT_LEN=8192"
```

**ATENÇÃO**: Esta CFLAG afeta apenas `ai-agent`, `media-server` e `ai-transcribe`.
O serviço `asterisk` usa `image: mlan/asterisk` (pré-compilado, buffer = 4000).
O filtro de ICE candidates é a única defesa no lado do Asterisk.

---

## Troubleshooting

### Sintoma: INVITE descartado silenciosamente (sem 100 Trying)

1. Verificar log do Asterisk:
```bash
docker logs asterisk-pabx 2>&1 | grep ERXOVERFLOW
```

2. Se aparecer `PJSIP_ERXOVERFLOW`:
```bash
# Ver tamanho do SDP
docker logs asterisk-pabx 2>&1 | grep "Content-Length:" | tail -5

# Contar candidates no SDP recebido
docker logs asterisk-pabx 2>&1 | grep "a=candidate:" | tail -20
```

3. Se candidates > 6, o filtro não está ativo:
   - **Ctrl+Shift+R** no browser (hard refresh)
   - Verificar console do browser para `[ICE-FILTER]`
   - Se não aparecer, verificar que `sessionDescriptionHandlerFactory` usa `createFilteredSDHFactory()`

### Sintoma: Filtro roda mas mostra "candidates: 0 → 0"

O filtro está usando **modifiers** (rodam antes do ICE gathering) em vez do **factory wrapper**.
Verificar que NÃO está usando `sessionDescriptionHandlerModifiers` no Inviter/accept.
O filtro DEVE estar no `sessionDescriptionHandlerFactory` do UserAgent.

### Sintoma: Browser não obtém relay candidates (TURN)

1. Verificar coturn está rodando:
```bash
docker logs coturn-turn 2>&1 | grep "ALLOCATE"
```

2. Se `ALLOCATE processed, success` → TURN funciona, problema está em outro lugar.
3. Se não há ALLOCATE, verificar:
   - `.env` do softphone tem `VITE_TURN_URL`, `VITE_TURN_USER`, `VITE_TURN_PASS`
   - Porta 3478/UDP está mapeada no docker-compose
   - Credenciais batem com `turnserver.conf`

### Sintoma: TURN allocations expiram (allocation timeout)

```bash
docker logs coturn-turn 2>&1 | grep "allocation timeout"
```

Isso é **normal** quando o browser não precisa do relay (conectou por host/srflx).
O browser faz ALLOCATE preventivo, usa se necessário, e libera com REFRESH lifetime=0.

### Sintoma: Áudio unidirecional após chamada conectar

1. Verificar `strictrtp`:
```bash
docker exec asterisk-pabx asterisk -rx "rtp show settings" 2>&1 | grep -i strict
```
Deve ser `no` em bridge networking.

2. Verificar `external_media_address` foi aplicado:
```bash
docker exec asterisk-pabx cat /etc/asterisk/pjsip.conf | grep external_media
```
Deve mostrar o IP do host (ex: `10.0.0.1`), não `__EXTERNAL_IP__`.

3. Verificar RTP está fluindo:
```bash
docker exec asterisk-pabx asterisk -rx "rtp show channels"
```

### Ativar debug PJSIP

```bash
docker exec asterisk-pabx asterisk -rx "pjsip set logger on"
docker logs -f asterisk-pabx 2>&1 | grep -E "INVITE|Trying|Ringing|200 OK|ERXOVERFLOW"
```

### Verificar healthcheck do coturn (limitação conhecida)

O healthcheck atual (`nc -z localhost 3478`) apenas testa se a porta TCP está aberta.
**Não valida** que TURN allocations funcionam. Para testar TURN de verdade:

```bash
docker exec coturn-turn turnutils_uclient -u voip_relay -w SENHA -p 3478 10.0.1.3
```

**Nota**: `error 403 (Forbidden IP)` neste teste é esperado (peer = loopback).
O teste real é via browser: console deve mostrar `[ICE-FILTER] candidates: N → 5`.

---

## Referências

- [pjproject PJSIP_MAX_PKT_LEN](https://github.com/pjsip/pjproject/blob/master/pjsip/include/pjsip/sip_config.h)
- [mlan/docker-asterisk strict RTP](https://github.com/mlan/docker-asterisk#strict-rtp-protection)
- [sip.js SessionDescriptionHandler](https://github.com/onsip/SIP.js/tree/main/src/platform/web/session-description-handler)
- [coturn external-ip](https://github.com/coturn/coturn/wiki/turnserver#external-ip)
