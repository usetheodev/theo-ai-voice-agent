# Configuração do Asterisk — Guia Completo

Documentação variável por variável de todas as configurações do Asterisk
usadas neste projeto. Cada entrada contém descrição, opções disponíveis,
como configurar, exemplo e impacto de configuração incorreta.

---

## Índice

1. [pjsip.conf — Sinalização SIP](#1-pjsipconf--sinalização-sip)
2. [rtp.conf — Transporte de Mídia](#2-rtpconf--transporte-de-mídia)
3. [http.conf — HTTP/WebSocket](#3-httpconf--httpwebsocket)
4. [extensions.conf — Dialplan](#4-extensionsconf--dialplan)
5. [modules.conf — Módulos](#5-modulesconf--módulos)
6. [docker-entrypoint.sh — NAT Dinâmico](#6-docker-entrypointsh--nat-dinâmico)
7. [coturn/turnserver.conf — Servidor TURN](#7-coturnturserverconf--servidor-turn)
8. [softphone/.env — Cliente WebRTC](#8-softphoneenv--cliente-webrtc)
9. [docker-compose.yml — Portas e Rede](#9-docker-composeyml--portas-e-rede)

---

## 1. pjsip.conf — Sinalização SIP

Arquivo: `asterisk/config/pjsip.conf`
Montado como template (`:ro`), copiado e processado pelo entrypoint.

### 1.1 Seção [global]

#### `type=global`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Declara a seção como configuração global do PJSIP. |
| Como config | Valor fixo, não alterar. |
| Exemplo     | `type=global` |
| Impacto     | Sem esta linha, Asterisk ignora a seção. |

#### `user_agent=Asterisk PABX`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | String enviada no header `User-Agent` de todas as mensagens SIP. |
| Como config | Texto livre. Identifica o servidor em traces e logs. |
| Exemplo     | `user_agent=Asterisk PABX` |
| Impacto     | Cosmético. Aparece nos logs do peer remoto. Em produção, ocultar versão por segurança. |

---

### 1.2 Seção [transport-udp]

Transporte SIP/UDP para comunicação com o media-server (ramal 2000) e softphones SIP tradicionais.

#### `type=transport`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Declara a seção como transporte de rede. |
| Como config | Valor fixo. |
| Exemplo     | `type=transport` |
| Impacto     | Sem esta linha, Asterisk não cria o listener. |

#### `protocol=udp`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Protocolo de transporte da seção. |
| Opções      | `udp` — SIP sobre UDP (padrão, mais comum). `tcp` — SIP sobre TCP (conexões persistentes). `tls` — SIP sobre TLS (criptografado). `ws` — WebSocket sem TLS (dev/localhost). `wss` — WebSocket sobre TLS (WebRTC produção). |
| Como config | `udp` para SIP tradicional. `wss` para WebRTC. |
| Exemplo     | `protocol=udp` |
| Impacto     | Define como os pacotes SIP são transmitidos. UDP é o padrão do SIP. |

#### `bind=0.0.0.0:5160`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Endereço e porta onde Asterisk escuta para SIP/UDP. |
| Como config | `0.0.0.0` = todas as interfaces. Porta padrão SIP é 5060; usamos 5160 para evitar conflito. |
| Exemplo     | `bind=0.0.0.0:5160` |
| Impacto     | Se a porta estiver em uso, Asterisk não inicia. Precisa bater com o mapeamento Docker (`5160:5160/udp`). |

---

### 1.3 Seção [transport-wss]

Transporte WebSocket Secure para clientes WebRTC (softphone React).

#### `protocol=wss`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Protocolo de transporte da seção. |
| Opções      | `udp` — SIP sobre UDP. `tcp` — SIP sobre TCP. `tls` — SIP sobre TLS. `ws` — WebSocket sem TLS (funciona apenas em `localhost`). `wss` — WebSocket sobre TLS (obrigatório para WebRTC em produção). |
| Como config | `wss` para WebRTC com TLS. `ws` funciona apenas em `localhost`. |
| Exemplo     | `protocol=wss` |
| Impacto     | Se usar `ws` em produção, browsers bloqueiam `getUserMedia()` (sem microfone). |

#### `bind=0.0.0.0:8189`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Porta WSS. Funciona em conjunto com `http.conf` que habilita TLS na mesma porta. |
| Como config | Deve bater com `tlsbindaddr` do `http.conf`. |
| Exemplo     | `bind=0.0.0.0:8189` |
| Impacto     | Porta errada = browser não conecta via WebSocket. |

#### `external_media_address=__EXTERNAL_IP__`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | IP que Asterisk anuncia no SDP para recepção de RTP. Placeholder `__EXTERNAL_IP__` é substituído pelo entrypoint com o IP do host Docker. |
| Como config | `auto` via env `EXTERNAL_MEDIA_IP`, ou IP fixo. Entrypoint resolve `host.docker.internal`. |
| Exemplo     | Após entrypoint: `external_media_address=10.0.0.1` |
| Impacto     | **CRÍTICO**. Sem isso, Asterisk anuncia IP interno do container (10.0.1.x) no SDP. Browser não consegue enviar RTP para esse IP = **sem áudio**. |

#### `external_signaling_address=__EXTERNAL_IP__`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | IP que Asterisk coloca nos headers Via e Contact das mensagens SIP. |
| Como config | Mesmo valor de `external_media_address`. Processado pelo entrypoint junto. |
| Exemplo     | Após entrypoint: `external_signaling_address=10.0.0.1` |
| Impacto     | Se incorreto, respostas SIP podem não retornar ao browser (Via errado). Menos crítico que media porque WebSocket mantém conexão persistente. |

#### `local_net=192.168.0.0/16` / `10.0.0.0/8` / `127.0.0.0/8`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Sub-redes consideradas "locais". Asterisk NÃO aplica `external_media_address` para peers nessas redes. |
| Como config | Listar todas as sub-redes internas. **NÃO incluir** 172.16.0.0/12 em Docker bridge. |
| Exemplo     | `local_net=192.168.0.0/16` |
| Impacto     | Se 172.16.0.0/12 estiver na lista, conexões via Docker gateway (172.x.x.x) NÃO usam external_media_address = browser recebe IP interno no SDP = sem áudio. A exclusão de 172.16.0.0/12 é intencional. |

---

### 1.4 Seção [RAMAL] — AOR (Address of Record)

Cada ramal tem 3 seções: AOR, auth e endpoint. A AOR define onde encontrar o dispositivo.

#### `type=aor`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Declara a seção como Address of Record — registro de localização do dispositivo. |
| Como config | Valor fixo. |
| Exemplo     | `type=aor` |
| Impacto     | Sem AOR, o endpoint não pode ser localizado para receber chamadas. |

#### `max_contacts=5`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Número máximo de dispositivos simultâneos registrados no mesmo ramal. |
| Como config | 1 = apenas um dispositivo. 5 = até 5 dispositivos tocam simultaneamente (fork). |
| Exemplo     | `max_contacts=5` (SIP softphones), `max_contacts=10` (ramal 2000, múltiplas instâncias do media-server) |
| Impacto     | Se excedido, novo REGISTER falha com 403. Para ramal 2000 (media-server), valor maior permite múltiplas instâncias. |

#### `remove_existing=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Quando `max_contacts` é atingido, define se remove o registro mais antigo para permitir o novo. |
| Opções      | `yes` — remove o contato mais antigo automaticamente (bom para dev, dispositivos reiniciam sem desregistrar). `no` — rejeita novo registro até o antigo expirar (prod com SLA, previne hijack). |
| Como config | `yes` para dev/ambientes onde dispositivos reiniciam frequentemente. `no` em prod com SLA. |
| Exemplo     | `remove_existing=yes` |
| Impacto     | Com `no`, se o browser recarregar sem desregistrar, o ramal fica ocupado até o registro expirar (até 600s). |

#### `qualify_frequency=30`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Intervalo (segundos) entre OPTIONS enviados ao dispositivo para verificar se está online. |
| Como config | 30 = verifica a cada 30s. 0 = desabilita. |
| Exemplo     | `qualify_frequency=30` |
| Impacto     | Se o dispositivo não responder, Asterisk marca como "Unavailable". Valor muito baixo gera tráfego desnecessário. Valor muito alto demora a detectar dispositivo offline. |

---

### 1.5 Seção [authRAMAL] — Autenticação

#### `type=auth`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Declara seção de autenticação. |
| Como config | Valor fixo. |
| Exemplo     | `type=auth` |
| Impacto     | Sem auth, qualquer um pode registrar no ramal. |

#### `auth_type=userpass`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Método de autenticação SIP. |
| Opções      | `userpass` — usuário e senha em texto claro no arquivo de config (simples, bom para dev). `md5` — hash MD5 pré-computado `MD5(username:realm:password)`, senha não fica exposta no config (recomendado para prod). |
| Como config | `userpass` para simplicidade. `md5` para não expor senhas no config (produção). |
| Exemplo     | `auth_type=userpass` |
| Impacto     | Com `userpass`, a senha fica em texto claro no arquivo. Em produção, usar `md5` ou Asterisk Realtime (banco de dados). |

#### `username` / `password`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Credenciais SIP. Usuário geralmente igual ao número do ramal. |
| Como config | Senhas fortes, únicas por ramal. NUNCA usar senha = ramal. |
| Exemplo     | `username=1004` / `password=xe9JDXRiUeK2848Uvoz1` |
| Impacto     | Credenciais fracas = registro não autorizado. Em produção, brute-force SIP é extremamente comum. |

---

### 1.6 Seção [RAMAL] — Endpoint

O endpoint define o comportamento de chamadas para este ramal.

#### `context=interno`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Contexto do dialplan (extensions.conf) onde chamadas deste endpoint entram. |
| Como config | Deve corresponder a um contexto definido em extensions.conf. |
| Exemplo     | `context=interno` |
| Impacto     | **SEGURANÇA CRÍTICA**. Contexto errado pode permitir chamadas externas não autorizadas. Sempre usar contextos restritos. |

#### `disallow=all` + `allow=ulaw` + `allow=alaw`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Codecs permitidos para negociação de mídia. `disallow=all` limpa a lista, depois `allow` adiciona os desejados em ordem de prioridade (primeiro = preferido). |
| Opções      | `opus` — alta qualidade, compressão variável, obrigatório para WebRTC (RFC 6716). `ulaw` — G.711µ-law, 64kbps, padrão América do Norte. `alaw` — G.711 A-law, 64kbps, padrão Europa/Brasil. `g722` — wideband 16kHz, melhor qualidade que G.711. `g729` — baixa banda (8kbps), requer licença. `gsm` — baixa banda, sem licença, qualidade inferior. |
| Como config | SIP tradicional: `ulaw` + `alaw`. WebRTC: `opus` primeiro, depois `ulaw` como fallback. |
| Exemplo     | SIP: `allow=ulaw` / `allow=alaw`. WebRTC: `allow=opus` / `allow=ulaw` |
| Impacto     | Se os codecs não forem compatíveis entre os dois lados, a chamada falha com "488 Not Acceptable Here". Opus é obrigatório para qualidade WebRTC. |

#### `auth=authRAMAL`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Associa a seção de autenticação ao endpoint. |
| Como config | Nome da seção auth correspondente. |
| Exemplo     | `auth=auth1004` |
| Impacto     | Sem auth, o ramal aceita registro sem credenciais. |

#### `aors=RAMAL`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Associa o AOR (localização) ao endpoint. |
| Como config | Nome da seção AOR correspondente. |
| Exemplo     | `aors=1004` |
| Impacto     | Sem AOR, Asterisk não sabe onde enviar chamadas para este endpoint. |

#### `callerid=Nome <Número>`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Identificação do chamador padrão para este endpoint. |
| Como config | Formato: `Nome <número>`. |
| Exemplo     | `callerid=Ramal WebRTC 1004 <1004>` |
| Impacto     | Cosmético. Aparece no display do telefone que recebe a chamada. |

#### `direct_media=no`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla se Asterisk tenta enviar RTP direto entre os dois endpoints (sem passar pelo Asterisk). |
| Opções      | `yes` — Asterisk envia re-INVITE para tentar mídia direta peer-to-peer (menor latência, sem transcodificação). `no` — RTP sempre passa pelo Asterisk (necessário para gravação, media fork, e quando os peers usam protocolos diferentes como WebRTC vs SIP). |
| Como config | `no` neste projeto (obrigatório). |
| Exemplo     | `direct_media=no` |
| Impacto     | **OBRIGATÓRIO `no` neste projeto**. Com `yes`, Asterisk tenta mídia direta entre WebRTC (SRTP/DTLS) e SIP (RTP), que são incompatíveis. Também necessário para gravação e media fork. |

#### `rtp_symmetric=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Envia RTP de volta para o mesmo IP:porta de onde recebeu, ignorando o que o SDP diz. |
| Opções      | `yes` — usa IP:porta de origem do pacote recebido (necessário em NAT/Docker). `no` — usa IP:porta declarado no SDP (apenas em redes sem NAT). |
| Como config | `yes` para NAT/Docker. |
| Exemplo     | `rtp_symmetric=yes` |
| Impacto     | **OBRIGATÓRIO em Docker bridge**. Sem isso, Asterisk envia RTP para o IP do SDP (container interno), não para o IP real de onde o pacote veio (Docker gateway). Resultado: áudio unidirecional. |

#### `force_rport=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Força Asterisk a responder SIP para a porta de origem real (rport), não a porta declarada no header Via. |
| Opções      | `yes` — usa porta de origem real do pacote (necessário em NAT/Docker). `no` — usa porta declarada no Via header (apenas redes sem NAT). |
| Como config | `yes` para NAT/Docker. |
| Exemplo     | `force_rport=yes` |
| Impacto     | Sem isso, respostas SIP podem ir para a porta errada quando há NAT. Em Docker, o mapeamento de portas altera a porta de origem. |

#### `rewrite_contact=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Reescreve o header Contact com o IP:porta real do dispositivo (observado na rede), em vez do que o dispositivo declarou. |
| Opções      | `yes` — reescreve com IP:porta observado no pacote de rede (necessário em NAT/Docker). `no` — mantém o Contact original enviado pelo dispositivo (apenas redes sem NAT). |
| Como config | `yes` para NAT/Docker. |
| Exemplo     | `rewrite_contact=yes` |
| Impacto     | Sem isso, re-INVITEs e BYEs vão para o IP declarado pelo dispositivo (que pode ser o IP interno do container/browser). |

#### `dtmf_mode=rfc4733`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Método de envio de tons DTMF (teclas do telefone). |
| Opções      | `rfc4733` — out-of-band via RTP (eventos telephone-event), padrão e mais compatível. `inband` — dentro do stream de áudio (requer codec sem compressão, G.711). `info` — via mensagens SIP INFO (fora do RTP, pode ter delay). `auto` — tenta detectar automaticamente. |
| Como config | `rfc4733` é o padrão e mais compatível. |
| Exemplo     | `dtmf_mode=rfc4733` |
| Impacto     | Modo errado = URA não reconhece dígitos. `rfc4733` funciona com WebRTC e SIP. |

#### `timers=yes` + `timers_sess_expires=1800`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Session timers (RFC 4028). Envia re-INVITEs periódicos para confirmar que a chamada ainda está ativa. |
| Opções      | `timers=yes` — habilita session timers (previne chamadas fantasma). `timers=no` — desabilita (chamadas podem ficar abertas indefinidamente se um lado desconectar sem BYE). |
| Como config | `timers=yes` habilita. `timers_sess_expires=1800` = 30 minutos entre verificações. |
| Exemplo     | `timers_sess_expires=1800` |
| Impacto     | Sem timers, chamadas "fantasma" podem ficar abertas indefinidamente se um lado desconectar sem enviar BYE. 1800s é um valor seguro. Valor muito baixo gera re-INVITEs excessivos. |

---

### 1.7 Variáveis exclusivas de endpoints WebRTC

Aplicam-se aos ramais 1004 e 1005.

#### `webrtc=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Atalho que habilita todas as features necessárias para WebRTC. |
| Opções      | `yes` — habilita automaticamente: `media_encryption=dtls`, `dtls_auto_generate_cert=yes`, `ice_support=yes`, `rtcp_mux=yes`, `use_avpf=yes`. `no` (padrão) — SIP tradicional sem WebRTC. |
| Como config | `yes` para ramais que conectam via browser/WebRTC. `no` (padrão) para SIP tradicional. |
| Exemplo     | `webrtc=yes` |
| Impacto     | **OBRIGATÓRIO para WebRTC**. Sem isso, DTLS handshake falha, sem áudio. NÃO usar em ramais SIP tradicionais (ex: ramal 2000). |

#### `dtls_auto_generate_cert=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla geração de certificados DTLS-SRTP. |
| Opções      | `yes` — Asterisk gera certificado efêmero automaticamente a cada chamada (simples, bom para dev). `no` — requer `dtls_cert_file` e `dtls_private_key` com certificados fixos (recomendado para prod). |
| Como config | `yes` para dev. Em produção, usar certificados fixos via `dtls_cert_file` e `dtls_private_key`. |
| Exemplo     | `dtls_auto_generate_cert=yes` |
| Impacto     | Sem certificado DTLS, o handshake falha e a chamada não tem áudio. Auto-generate simplifica dev mas gera certificados diferentes a cada chamada. |

#### `media_encryption=dtls`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Tipo de criptografia de mídia (RTP). |
| Opções      | `dtls` — DTLS-SRTP, obrigatório para WebRTC (RFC 8827). Handshake sobre DTLS, mídia criptografada via SRTP. `sdes` — SDES-SRTP, chave trocada em texto no SDP (inseguro sem TLS). `no` (padrão) — RTP sem criptografia (SIP tradicional entre containers Docker). |
| Como config | `dtls` para WebRTC. Não definir para SIP tradicional. |
| Exemplo     | `media_encryption=dtls` |
| Impacto     | WebRTC exige criptografia de mídia. Sem DTLS, o browser rejeita a conexão RTP. |

---

### 1.8 Ramal 2000 — Agente Python (Media Server)

#### Diferenças do ramal 2000

| Variável         | Valor | Motivo |
|------------------|-------|--------|
| `max_contacts`   | 10    | Permite múltiplas instâncias do media-server |
| `webrtc`         | não   | Media-server usa SIP/RTP puro, não WebRTC |
| `allow`          | ulaw, alaw | Codecs tradicionais, sem opus (media-server não suporta) |
| `media_encryption` | não  | RTP não criptografado entre containers Docker (rede interna) |

---

## 2. rtp.conf — Transporte de Mídia

Arquivo: `asterisk/config/rtp.conf`

### 2.1 Faixa de portas RTP

#### `rtpstart=20000` + `rtpend=20100`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Faixa de portas UDP usadas para streams RTP. Cada chamada usa 1 porta (com rtcp-mux) ou 2 portas (sem). |
| Como config | Faixa deve comportar o dobro de chamadas simultâneas esperadas. 100 portas = ~50 chamadas. |
| Exemplo     | `rtpstart=20000` / `rtpend=20100` |
| Impacto     | **Deve bater com o mapeamento Docker** (`20000-20100:20000-20100/udp`). Faixa muito pequena = chamadas rejeitadas por falta de porta. Faixa muito grande = Docker cria muitas regras iptables (lento). |

### 2.2 Strict RTP

#### `strictrtp=no`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla validação de origem dos pacotes RTP recebidos. |
| Opções      | `yes` — descarta pacotes RTP de IP:porta diferente do esperado no SDP (protege contra injeção de mídia, mas quebra em NAT). `no` — aceita RTP de qualquer IP:porta (necessário em Docker bridge/NAT). `secrtp` (Asterisk 16+) — aprendizado: aceita os primeiros pacotes de qualquer fonte, depois trava no IP:porta observado. |
| Como config | `no` em Docker bridge networking. `yes` em rede sem NAT. |
| Exemplo     | `strictrtp=no` |
| Impacto     | **OBRIGATÓRIO `no` em Docker bridge**. NAT muda o IP/porta de origem dos pacotes RTP. Com `yes`, Asterisk descarta esses pacotes = áudio unidirecional ou sem áudio. Ref: [mlan/docker-asterisk](https://github.com/mlan/docker-asterisk#strict-rtp-protection) |

### 2.3 ICE Support

#### `icesupport=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Habilita Interactive Connectivity Establishment no lado do Asterisk. |
| Opções      | `yes` — Asterisk participa da negociação ICE (obrigatório para WebRTC). `no` (padrão) — sem ICE, RTP vai direto para IP:porta do SDP. |
| Como config | `yes` sempre que houver endpoints WebRTC. |
| Exemplo     | `icesupport=yes` |
| Impacto     | WebRTC exige ICE. Sem isso, a negociação de mídia com browsers falha. |

### 2.4 stunaddr (REMOVIDO)

```ini
; stunaddr removido intencionalmente para Docker bridge networking:
; - external_media_address no pjsip.conf já define o IP correto (host Docker)
; - Google STUN retorna IP WAN público, inacessível sem port forwarding
; - Gera ICE candidates inúteis que poluem o SDP e confundem o ICE negotiation
```

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Servidor STUN que Asterisk usaria para descobrir seu próprio IP externo. |
| Por que removido | Em Docker bridge, `external_media_address` já define o IP. STUN externo retorna IP WAN, inacessível para chamadas locais. |
| Impacto da remoção | Nenhum negativo. Asterisk usa `external_media_address` para NAT. |

### 2.5 Jitter Buffer

#### `jbenable=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla ativação do jitter buffer para compensar variações de latência nos pacotes RTP. |
| Opções      | `yes` — ativa jitter buffer (recomendado, melhora qualidade em redes com jitter). `no` — desativa (menor latência, mas áudio picota em redes instáveis). |
| Como config | `yes` para melhor qualidade de áudio. |
| Exemplo     | `jbenable=yes` |
| Impacto     | Sem jitter buffer, variações de rede causam áudio picotado. Adiciona latência fixa (~40ms). |

#### `jbimpl=adaptive`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Implementação do jitter buffer. |
| Opções      | `adaptive` — ajusta tamanho dinamicamente conforme condições da rede (recomendado para redes variáveis). `fixed` — tamanho fixo, ignora variações de rede (previsível mas pode desperdiçar latência ou ser insuficiente). |
| Como config | `adaptive` é recomendado para redes variáveis (Docker, internet). |
| Exemplo     | `jbimpl=adaptive` |
| Impacto     | `fixed` desperdiça latência em redes estáveis ou não compensa o suficiente em redes instáveis. |

#### `jbtargetextra=40`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Latência extra (ms) adicionada ao target do jitter buffer adaptativo. |
| Como config | 40ms é um bom padrão. Aumente para redes com alto jitter. |
| Exemplo     | `jbtargetextra=40` |
| Impacto     | Valor alto = mais latência mas menos artefatos. Valor baixo = menos latência mas áudio pode picotar. |

#### `jbmaxsize=200`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Tamanho máximo do jitter buffer em ms. Pacotes com atraso maior são descartados. |
| Como config | 200ms para redes locais. 500ms para internet. |
| Exemplo     | `jbmaxsize=200` |
| Impacto     | Muito baixo = descarta pacotes em redes lentas. Muito alto = latência acumulada se a rede degradar. |

#### `jbresyncthreshold=1000`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Se o atraso exceder este valor (ms), o jitter buffer é resetado em vez de tentar sincronizar gradualmente. |
| Como config | 1000ms é o padrão. |
| Exemplo     | `jbresyncthreshold=1000` |
| Impacto     | Se a rede tiver um salto de latência > 1s, resync abrupto causa "corte" no áudio mas recupera mais rápido. |

#### `jblog=no`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla logging detalhado do comportamento do jitter buffer. |
| Opções      | `yes` — log por pacote RTP (muito verboso, útil para debug de qualidade de áudio). `no` — sem log de jitter buffer (recomendado para produção). |
| Como config | `no` em produção (muito verboso). `yes` para debug de qualidade de áudio. |
| Exemplo     | `jblog=no` |
| Impacto     | Com `yes`, gera uma linha de log por pacote RTP. Útil para diagnosticar áudio picotado. |

---

## 3. http.conf — HTTP/WebSocket

Arquivo: `asterisk/config/http.conf`

Necessário para WebRTC — o WebSocket SIP roda sobre o HTTP server do Asterisk.

#### `enabled=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla ativação do servidor HTTP embutido do Asterisk. |
| Opções      | `yes` — ativa HTTP server (obrigatório para WebSocket/WebRTC). `no` (padrão) — HTTP desabilitado. |
| Como config | `yes` obrigatório para WebRTC/WebSocket. |
| Exemplo     | `enabled=yes` |
| Impacto     | Sem isso, WebSocket SIP não funciona. Browsers não conseguem conectar. |

#### `bindaddr=0.0.0.0`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Endereço de escuta HTTP. `0.0.0.0` = todas as interfaces. |
| Como config | `0.0.0.0` em Docker (necessário para port mapping). |
| Exemplo     | `bindaddr=0.0.0.0` |
| Impacto     | Se `127.0.0.1`, apenas conexões locais são aceitas (inacessível de fora do container). |

#### `bindport=8188`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Porta HTTP (WebSocket sem TLS). O caminho do WebSocket é `/ws`. |
| Como config | Porta livre que não conflite com outros serviços. Mapeada no Docker como `8188:8188`. |
| Exemplo     | `bindport=8188` → URL: `ws://localhost:8188/ws` |
| Impacto     | Porta errada = softphone não conecta. Funciona sem TLS apenas em `localhost` (browsers aceitam contexto inseguro para localhost). |

#### `tlsenable=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla ativação de HTTPS/WSS com TLS. |
| Opções      | `yes` — habilita TLS (obrigatório para `wss://` e WebRTC em produção). `no` — sem TLS (apenas `ws://`, funciona em localhost). |
| Como config | `yes` para WebRTC em produção. Requer certificados. |
| Exemplo     | `tlsenable=yes` |
| Impacto     | Sem TLS, `wss://` não funciona. Em produção, browsers exigem TLS para `getUserMedia()`. |

#### `tlsbindaddr=0.0.0.0:8189`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Endereço e porta para HTTPS/WSS. |
| Como config | Deve bater com `bind` do `transport-wss` no pjsip.conf. |
| Exemplo     | `tlsbindaddr=0.0.0.0:8189` → URL: `wss://hostname:8189/ws` |
| Impacto     | Porta deve ser mapeada no Docker (`8189:8189`). |

#### `tlscertfile` / `tlsprivatekey`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Caminho para certificado e chave privada TLS. |
| Como config | Montados via volume Docker: `./asterisk/keys:/etc/asterisk/keys:ro`. Para dev, certificados auto-assinados. Para prod, Let's Encrypt ou similar. |
| Exemplo     | `tlscertfile=/etc/asterisk/keys/asterisk.crt` |
| Impacto     | Certificados inválidos/ausentes = TLS handshake falha. Browser mostra erro de segurança. |

---

## 4. extensions.conf — Dialplan

Arquivo: `asterisk/config/extensions.conf`

### 4.1 Seção [general]

#### `static=yes` + `writeprotect=no`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controlam como o dialplan é carregado e se pode ser salvo via CLI. |
| Opções      | `static=yes` — carrega dialplan do arquivo (padrão). `static=no` — usa Asterisk Realtime (banco de dados). `writeprotect=yes` — bloqueia `dialplan save` no CLI. `writeprotect=no` — permite salvar mudanças feitas via CLI. |
| Como config | Valores padrão para arquivos estáticos com flexibilidade de debug. |
| Exemplo     | `static=yes` / `writeprotect=no` |
| Impacto     | Com `writeprotect=yes`, `dialplan save` no CLI é bloqueado. |

#### `clearglobalvars=no`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla se variáveis globais são resetadas ao recarregar o dialplan. |
| Opções      | `yes` — reseta todas as variáveis globais em cada `dialplan reload`. `no` — preserva valores atuais das variáveis globais entre reloads. |
| Como config | `no` para preservar estado. `yes` para reset completo. |
| Exemplo     | `clearglobalvars=no` |
| Impacto     | Com `yes`, variáveis como `OPERADOR` e `SUPORTE` são resetadas em cada reload. |

### 4.2 Seção [globals]

#### `OPERADOR=1001` / `SUPORTE=1002` / `TIMEOUT_URA=10`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Variáveis globais usadas no dialplan. Centralizam configurações. |
| Como config | Altere para redirecionar ramais da URA sem mexer no dialplan. |
| Exemplo     | `OPERADOR=1001` → URA opção 1 encaminha para 1001. |
| Impacto     | Se o ramal não existir, chamada vai para VoiceMail ou falha. |

### 4.3 Contexto [interno]

#### `exten => _100X,...,Dial(PJSIP/${EXTEN},30,tT)`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Regra de discagem para ramais internos. |
| Opções      | Pattern `_100X` — captura ramais 1001-1009 (X = dígito 0-9). Opções do `Dial`: `t` — chamado pode transferir. `T` — chamador pode transferir. `m` — música de espera em vez de ringback. `r` — gera ringback artificial. |
| Como config | Ajuste o pattern conforme os ramais. `30` = timeout em segundos. |
| Exemplo     | Chamada para 1004 → `Dial(PJSIP/1004,30,tT)` |
| Impacto     | Timeout muito curto = não dá tempo de atender. Sem `tT`, transferência não funciona. |

#### `exten => 2000,...,Dial(PJSIP/2000,60,tT)`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Ramal do AI Agent. Timeout 60s (mais longo pois o media-server pode demorar a iniciar o pipeline de áudio). |
| Como config | Timeout deve cobrir o tempo de setup do pipeline STT→LLM→TTS. |
| Exemplo     | `Dial(PJSIP/2000,60,tT)` |
| Impacto     | Timeout < tempo de setup do media-server = chamada cai antes do agente atender. |

### 4.4 Contexto [from-external]

#### `exten => _X.,...,Congestion()`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | **Contexto de segurança**: rejeita todas as chamadas externas por padrão. |
| Opções      | `Congestion()` — retorna tom de congestionamento (rejeição silenciosa). `Hangup()` — desliga imediatamente. `Goto(outro-contexto,...)` — redireciona para processamento específico (ex: URA pública). |
| Como config | Adicione `exten =>` específicos para DIDs que devem ser aceitos. |
| Exemplo     | `exten => _X.,1,Congestion()` → rejeita tudo |
| Impacto     | **SEGURANÇA CRÍTICA**. Sem este contexto restritivo, chamadas externas podem acessar recursos internos. |

---

## 5. modules.conf — Módulos

Arquivo: `asterisk/config/modules.conf`

#### `autoload=yes`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Controla carregamento automático de módulos. |
| Opções      | `yes` — carrega todos os módulos disponíveis automaticamente (simples, mais memória). `no` — não carrega nada; exige `load =>` explícito para cada módulo (seguro, mínima superfície de ataque). |
| Como config | `yes` para simplicidade. Em produção com segurança estrita, usar `autoload=no` e carregar módulos individualmente. |
| Exemplo     | `autoload=yes` |
| Impacto     | Carrega módulos desnecessários (maior uso de memória, superfície de ataque maior). |

#### `preload => res_pjsip.so` + `preload => res_http_websocket.so`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Módulos carregados ANTES dos demais. PJSIP e HTTP/WebSocket devem estar prontos antes que endpoints dependam deles. |
| Como config | `preload` garante a ordem. Sem isso, módulos dependentes podem falhar. |
| Exemplo     | `preload => res_pjsip.so` |
| Impacto     | Se res_http_websocket não carregar antes dos endpoints PJSIP, WebSocket pode não funcionar. |

#### `noload => chan_sip.so` (e outros)

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Impede carregamento de módulos obsoletos ou desnecessários. |
| Opções      | `chan_sip.so` — driver SIP legado, conflita com PJSIP na mesma porta. `chan_skinny.so` — protocolo Cisco Skinny, desnecessário. `chan_mgcp.so` — protocolo MGCP, desnecessário. `chan_oss.so` — áudio via placa de som, irrelevante em container. `app_voicemail.so` — voicemail, remover se não usar. |
| Como config | Liste todos os módulos que não são necessários. |
| Exemplo     | `noload => chan_sip.so` |
| Impacto     | `chan_sip` conflita com PJSIP na mesma porta. Sem `noload`, ambos tentam escutar na 5060 e Asterisk falha. |

---

## 6. docker-entrypoint.sh — NAT Dinâmico

Arquivo: `asterisk/scripts/docker-entrypoint.sh`

### Variáveis de Ambiente

#### `EXTERNAL_MEDIA_IP`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | IP externo para NAT traversal. Usado no `external_media_address` do pjsip.conf. |
| Opções      | `auto` (padrão) — resolve `host.docker.internal` automaticamente via getent/ping/nslookup. IP fixo (ex: `192.168.1.100`) — usa o valor exato, sem resolução DNS. |
| Como config | `auto` para ambientes Docker Desktop/Linux com host.docker.internal. IP fixo para ambientes sem resolução DNS. |
| Exemplo     | `EXTERNAL_MEDIA_IP=auto` ou `EXTERNAL_MEDIA_IP=192.168.1.100` |
| Impacto     | Se não resolver, Asterisk anuncia IP interno do container = browser não alcança RTP. Entrypoint remove as linhas `__EXTERNAL_IP__` do config neste caso. |

### Fluxo do Entrypoint

1. Resolve `host.docker.internal` via getent/ping/nslookup
2. Copia `pjsip.conf.template` → `pjsip.conf` (template é `:ro`)
3. Substitui `__EXTERNAL_IP__` pelo IP resolvido via `sed`
4. Se falhar, remove as linhas com `__EXTERNAL_IP__` (mídia depende de TURN)
5. Executa `asterisk -fp`

---

## 7. coturn/turnserver.conf — Servidor TURN

Arquivo: `coturn/turnserver.conf`

O TURN server é necessário como fallback quando a conectividade direta (host/srflx) falha.

#### `listening-port=3478`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Porta principal STUN/TURN. Padrão RFC. |
| Como config | 3478 é o padrão. Mapeada no Docker como `3478:3478/udp` e `3478:3478/tcp`. |
| Exemplo     | `listening-port=3478` |
| Impacto     | Browser envia TURN Allocate para esta porta. Se não mapeada no Docker, TURN não funciona. |

#### `realm=pabx.local`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Domínio (realm) usado na autenticação TURN. Enviado no challenge 401 Unauthorized. |
| Como config | Qualquer string. O browser obtém o realm automaticamente da resposta 401. |
| Exemplo     | `realm=pabx.local` |
| Impacto     | Deve ser consistente. Se mudar, sessions ativas perdem autenticação. |

#### `lt-cred-mech`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Mecanismo de autenticação TURN. |
| Opções      | `lt-cred-mech` — long-term credentials (RFC 5389), username + password fixos. `use-auth-secret` — TURN REST API, tokens temporários via HMAC-SHA1 (mais seguro para produção). |
| Como config | `lt-cred-mech` para dev com `user=username:password`. `use-auth-secret` para prod com token rotation. |
| Exemplo     | `lt-cred-mech` |
| Impacto     | Sem mecanismo de auth, qualquer um usa o TURN como relay aberto (risco de abuso). |

#### `user=voip_relay:myz4tMwCRi5IrPbDwOCZ5ZCW`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Credenciais TURN. Formato `user=username:password`. |
| Como config | Deve bater com `VITE_TURN_USER` e `VITE_TURN_PASS` do softphone. |
| Exemplo     | `user=voip_relay:senhaForte123` |
| Impacto     | Credenciais erradas = `401 Unauthorized` = browser não obtém relay candidates. |

#### `min-port=49152` + `max-port=49252`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Faixa de portas UDP usadas para relay. Cada TURN allocation usa ~2 portas. |
| Como config | 100 portas = ~50 sessões simultâneas (suficiente para dev). Deve bater com o mapeamento Docker. |
| Exemplo     | `min-port=49152` / `max-port=49252` → Docker: `49152-49252:49152-49252/udp` |
| Impacto     | **Faixa deve ser idêntica ao mapeamento Docker**. Se diferente, relay aloca porta que não está mapeada = pacotes não chegam. Faixa grande demais = Docker cria milhares de regras iptables (muito lento). |

#### `no-multicast-peers`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Bloqueia relay para endereços multicast. |
| Como config | Sempre habilitado por segurança. |
| Exemplo     | `no-multicast-peers` |
| Impacto     | Sem isso, atacante poderia usar TURN para enviar tráfego multicast na rede interna. |

### Entrypoint do coturn

#### `EXTERNAL_TURN_IP`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | IP externo anunciado nos relay candidates (XOR-RELAYED-ADDRESS). |
| Opções      | `auto` (padrão) — resolve `host.docker.internal` automaticamente. IP fixo (ex: `10.0.0.1`) — usa o valor exato. |
| Como config | `auto` para ambientes Docker com host.docker.internal. IP fixo para ambientes sem resolução DNS. |
| Exemplo     | `EXTERNAL_TURN_IP=auto` → resolve para `10.0.0.1` |
| Impacto     | Sem external-ip, coturn anuncia IP interno do container (10.0.1.x). Browser cria relay candidate com IP inacessível. O relay parece funcionar (ALLOCATE OK) mas o peer (Asterisk) não consegue enviar media pelo relay. |

---

## 8. softphone/.env — Cliente WebRTC

Arquivo: `softphone/.env`

#### `VITE_SIP_SERVER=ws://localhost:8188/ws`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | URL WebSocket do Asterisk. |
| Opções      | `ws://host:porta/ws` — WebSocket sem TLS (apenas dev/localhost). `wss://host:porta/ws` — WebSocket com TLS (obrigatório em produção). |
| Como config | Deve bater com `bindport` do http.conf. Path `/ws` é fixo do Asterisk. |
| Exemplo     | Dev: `ws://localhost:8188/ws` / Prod: `wss://sip.example.com:8189/ws` |
| Impacto     | URL errada = softphone não conecta ao Asterisk. |

#### `VITE_SIP_USER` / `VITE_SIP_PASS`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Credenciais do ramal WebRTC. Devem bater com a seção `auth` no pjsip.conf. |
| Como config | Copiar do pjsip.conf. |
| Exemplo     | `VITE_SIP_USER=1004` / `VITE_SIP_PASS=xe9JDXRiUeK2848Uvoz1` |
| Impacto     | Credenciais erradas = REGISTER falha com 401. |

#### `VITE_STUN_URL=stun:stun.l.google.com:19302`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Servidor STUN usado pelo browser para descobrir seu IP público (srflx candidates). |
| Opções      | `stun:stun.l.google.com:19302` — STUN público Google (gratuito, confiável). `stun:stun1.l.google.com:19302` — STUN Google alternativo. `stun:localhost:3478` — STUN local via coturn. |
| Como config | Google STUN é gratuito e confiável. Pode usar coturn local (`stun:localhost:3478`). |
| Exemplo     | `VITE_STUN_URL=stun:stun.l.google.com:19302` |
| Impacto     | Sem STUN, browser não gera srflx candidates. Em Docker bridge local, não é estritamente necessário (host candidates bastam), mas ajuda em cenários com NAT. |

#### `VITE_TURN_URL` / `VITE_TURN_USER` / `VITE_TURN_PASS`

| Campo       | Valor    |
|-------------|----------|
| Descrição   | Servidor TURN para relay candidates. Credenciais devem bater com coturn. |
| Opções      | `turn:host:porta` — TURN sobre UDP (padrão). `turn:host:porta?transport=tcp` — TURN sobre TCP (quando UDP é bloqueado). `turns:host:porta` — TURN sobre TLS (máxima compatibilidade com firewalls). |
| Como config | URL deve apontar para o coturn: `turn:localhost:3478`. User/pass = config coturn. |
| Exemplo     | `VITE_TURN_URL=turn:localhost:3478` / `VITE_TURN_USER=voip_relay` |
| Impacto     | Sem TURN, browser não tem relay candidates. Se NAT simétrica ou firewall restritiva bloquear host/srflx, a chamada não terá mídia. TURN é o fallback universal. |

---

## 9. docker-compose.yml — Portas e Rede

### Portas mapeadas do Asterisk

| Porta Host | Porta Container | Protocolo | Uso |
|------------|-----------------|-----------|-----|
| 5160       | 5160            | UDP       | SIP (media-server → Asterisk) |
| 8188       | 8188            | TCP       | HTTP/WebSocket (softphone `ws://`) |
| 8189       | 8189            | TCP       | HTTPS/WSS (softphone `wss://`) |
| 20000-20100| 20000-20100     | UDP       | RTP Media (áudio das chamadas) |

### Portas mapeadas do coturn

| Porta Host     | Porta Container | Protocolo | Uso |
|----------------|-----------------|-----------|-----|
| 3478           | 3478            | UDP+TCP   | STUN/TURN signaling |
| 5349           | 5349            | TCP       | TURN over TLS |
| 49152-49252    | 49152-49252     | UDP       | TURN relay media |

### Rede

```yaml
networks:
  voip-network:
    driver: bridge    # subnet: 10.0.1.0/24 (auto-atribuído)
```

Todos os serviços na mesma rede bridge. Comunicação entre containers por nome DNS (ex: `asterisk`, `coturn`, `ai-agent`).

### Volumes do Asterisk

| Volume Host | Mount Container | Modo | Motivo |
|-------------|-----------------|------|--------|
| `pjsip.conf` | `pjsip.conf.template` | `:ro` | Entrypoint copia e faz sed (não altera o original) |
| `extensions.conf` | `extensions.conf` | `:ro` | Dialplan estático |
| `http.conf` | `http.conf` | `:ro` | Config HTTP/WebSocket |
| `rtp.conf` | `rtp.conf` | `:ro` | Config RTP |
| `modules.conf` | `modules.conf` | `:ro` | Config de módulos |
| `asterisk/keys` | `/etc/asterisk/keys` | `:ro` | Certificados TLS |
| `asterisk/sounds` | `/var/lib/asterisk/sounds/en` | `:ro` | Áudios customizados |
| `docker-entrypoint.sh` | `/etc/asterisk/scripts/docker-entrypoint.sh` | `:ro` | Script de inicialização |

---

## Checklist de Reprodução do Ambiente

Para reproduzir este ambiente do zero:

1. **Certificados TLS**: Gerar em `asterisk/keys/`
   ```bash
   openssl req -x509 -nodes -days 365 \
     -newkey rsa:2048 \
     -keyout asterisk/keys/asterisk.key \
     -out asterisk/keys/asterisk.crt \
     -subj "/CN=localhost"
   ```

2. **Senhas**: Gerar senhas únicas para cada ramal e TURN
   ```bash
   openssl rand -base64 16  # gera senha aleatória
   ```

3. **Configurar pjsip.conf**: Criar ramais necessários seguindo o padrão AOR + auth + endpoint

4. **Configurar softphone/.env**: Copiar de `.env.example`, preencher credenciais

5. **Subir ambiente**:
   ```bash
   docker compose up -d
   ```

6. **Verificar**:
   ```bash
   # Asterisk saudável
   docker exec asterisk-pabx asterisk -rx "pjsip show endpoints"

   # TURN funcionando
   docker logs coturn-turn 2>&1 | grep "external-ip"

   # Entrypoint aplicou NAT
   docker exec asterisk-pabx cat /etc/asterisk/pjsip.conf | grep external_media
   ```
