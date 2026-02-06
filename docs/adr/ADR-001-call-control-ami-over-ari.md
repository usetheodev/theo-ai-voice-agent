# ADR-001: Controle de Chamadas via AMI ao inves de ARI

**Status:** Aceito
**Data:** 2026-02-05
**Autores:** Eduardo Vasconcelos (revisao tecnica), Paulo (decisao final)
**Contexto:** Evolucao do agente de voz para suportar transferencia assistida de chamadas

---

## Contexto

O sistema theo-ai-voice-agent possui um pipeline conversacional funcional:

```
Caller --> Asterisk --> Media Server (PJSIP/pjsua2) --> AI Agent (STT->LLM->TTS)
```

O Media Server registra o ramal 2000 no Asterisk via PJSIP direto (pjsua2 binding Python), controla midia via streaming ports, e isola o path critico de RTP do processamento de IA atraves do Media Fork Manager.

**Novo requisito:** O agente de voz precisa controlar chamadas durante a conversa. Cenario principal: cliente liga, agente conversa, agente decide transferir para departamento (suporte, vendas), cliente e colocado em hold, sistema disca pro destino, conecta os dois.

Um PRD foi proposto sugerindo ARI (Asterisk REST Interface) como mecanismo de controle. Esta ADR documenta a decisao de usar AMI (Asterisk Manager Interface) ao inves de ARI.

---

## Decisao

**Usar AMI + Dialplan para controle de chamadas, mantendo PJSIP direto para midia.**

---

## Opcoes Consideradas

### Opcao A: ARI (Asterisk REST Interface) — Rejeitada

ARI fornece controle total sobre canais via Stasis applications. O processo Python se conecta via WebSocket e gerencia bridges, canais e midia programaticamente.

**Motivos da rejeicao:**

1. **Regressao de midia.** O projeto usa PJSIP direto — o Media Server E o endpoint SIP. ARI exige que o canal entre em Stasis, o que significaria reescrever a camada de midia. O Media Fork Manager (ring buffer, isolamento path critico, fallback mode) nao tem equivalente em ARI.

2. **Fragilidade da conexao.** Se a conexao WebSocket do ARI cair (upgrade, OOM kill, network blip), canais em Stasis ficam orfaos. Bridges e canais pendurados sem controller. Com PJSIP direto, se o Media Server morrer, o Asterisk detecta que o endpoint sumiu e limpa automaticamente.

3. **Complexidade desnecessaria.** ARI requer gerenciamento manual de bridges (criar, adicionar canais, destruir), tratamento de race conditions em eventos (StasisEnd antes de originate, double cleanup), e reconexao com redescoberta de estado. Para transfer assistida, AMI resolve com 1 comando.

4. **Overhead de latencia.** Cada operacao ARI e um HTTP roundtrip (~5-20ms). Em pipeline de voz onde milissegundos importam, isso e overhead evitavel.

5. **Destruicao de funcionalidades existentes.** Migrar para ARI perderia: Media Fork Manager, streaming ports (~100-200ms latencia), barge-in, VAD, protocolo ASP — sem ganho funcional equivalente.

### Opcao B: SIP REFER — Descartada

O Media Server poderia enviar SIP REFER para o Asterisk, solicitando transfer do caller. Tecnicamente possivel, mas REFER em PJSIP e fragil, mal documentado para o cenario de B-leg transferindo A-leg, e dificil de debugar.

### Opcao C: AMI + Dialplan — Aceita

AMI e um socket TCP com comandos texto. O comando `Redirect` move um canal para outro contexto/extensao no dialplan. O Asterisk executa o dialplan e gerencia bridge, MOH e cleanup nativamente.

**Motivos da aceitacao:**

1. **Minima invasao.** Adiciona 1 modulo novo (AMI client, ~100-150 linhas) ao Media Server. Zero mudanca no pipeline de midia, Media Fork Manager, ASP, streaming ports.

2. **Resiliencia.** Se a conexao AMI cair, chamadas ativas continuam normalmente. AMI e usado apenas no momento do transfer, nao para controle continuo.

3. **Cleanup automatico.** O Asterisk gerencia bridges e canais via dialplan. Sem bridges orfas, sem canais pendurados. O dialplan tem fallback nativo (destino nao atende -> volta pro AI Agent).

4. **Simplicidade operacional.** AMI existe ha 20+ anos, e estavel, bem documentado, e familiar para qualquer engenheiro de telefonia.

5. **Preserva separacao IA <-> telefonia.** O AI Agent chama `transfer_call("suporte")` via tool calling. O Media Server traduz em `AMI Redirect(channel, context, exten)`. A IA nao sabe que AMI existe.

---

## Arquitetura da Solucao

### Fluxo de Transfer Assistida

```
FASE 1: Conversa normal (sem mudanca)
  Caller --SIP--> Asterisk --Dial(2000)--> Media Server --ASP--> AI Agent
                    |                         |
                    | X-Caller-Channel        | call_id, session_id,
                    | header no INVITE        | caller_channel (extraido do header)
                    |                         |
                                          STT->LLM->TTS (pipeline existente)

FASE 2: LLM decide transferir
  LLM: "Vou transferir voce para o suporte" + tool_call: transfer_call("1001")
  AI Agent: fala via TTS, depois envia ASP {call.action: transfer, target: "1001"}

FASE 3: Media Server executa
  Media Server: AMI Redirect(caller_channel, [transfer-assistida], 1001)

FASE 4: Asterisk cuida do resto
  - Encerra perna com Media Server (automatico)
  - Move caller para contexto [transfer-assistida]
  - Caller ouve MOH enquanto 1001 toca
  - Se 1001 atende -> conectado
  - Se 1001 nao atende -> fallback para AI Agent (Dial(PJSIP/2000))
```

### Componentes Novos

| Componente | Onde | Descricao |
|---|---|---|
| AMI Client | Media Server | Socket TCP, comandos Redirect/Originate, ~100-150 linhas |
| Mensagem ASP `call.action` | Protocolo ASP (shared/) | Nova mensagem para acoes de chamada |
| Call action handler | Media Server | Recebe ASP call.action, executa via AMI |
| LLM tools de chamada | AI Agent | transfer_call, end_call como tools do LLM |
| Header extraction | Media Server (SIP) | Extrair X-Caller-Channel do INVITE |
| Dialplan transfer | Asterisk (extensions.conf) | Contexto [transfer-assistida] com fallback |
| manager.conf | Asterisk | Habilitar AMI com credenciais |

### Onde o Estado Vive

O `caller_channel` e armazenado no objeto Call do Media Server (que ja e stateful por natureza — mantem call object pjsua2, session ASP, ring buffer, streaming ports).

**Decisao explicita:** NAO usar Redis, NAO repassar para AI Agent.

- Redis: overkill para 1 campo com lifetime = chamada
- AI Agent: channel name e detalhe de Asterisk, nao deve vazar para camada de IA

### Separacao de Concerns

```
Camada          | Sabe o que                    | NAO sabe
----------------|-------------------------------|---------------------------
LLM             | "transfer_call(suporte)"      | channel names, AMI, SIP
AI Agent        | tool call -> ASP call.action   | como executar transfer
Media Server    | AMI Redirect + caller_channel  | por que a IA decidiu isso
Asterisk        | dialplan + bridge + MOH        | que existe IA no sistema
```

---

## Configuracao Necessaria no Asterisk

### manager.conf (novo)

```ini
[general]
enabled = yes
port = 5038
bindaddr = 0.0.0.0

[media-server]
secret = <senha_segura>
read = call,system
write = call,originate,system
deny = 0.0.0.0/0.0.0.0
permit = 172.16.0.0/255.240.0.0
```

### extensions.conf (adicionar)

```ini
; Passar channel name do caller para Media Server
exten => 2000,1,Set(PJSIP_HEADER(add,X-Caller-Channel)=${CHANNEL})
 same => n,Dial(PJSIP/2000,30,tT)

; Contexto de transfer assistida
[transfer-assistida]
exten => _X.,1,Playback(please-hold)
 same => n,Dial(PJSIP/${EXTEN},30,tTm(default))
 same => n,GotoIf($["${DIALSTATUS}" = "ANSWER"]?done:fallback)
 same => n(done),Hangup()
 same => n(fallback),Dial(PJSIP/2000,30,tT)
 same => n,Hangup()
```

### docker-compose.yml (expor porta AMI)

```yaml
asterisk:
  ports:
    - "5038:5038"  # AMI (apenas rede interna Docker)
```

---

## Consequencias

### Positivas

- Pipeline conversacional preservado integralmente
- Media Fork Manager, streaming ports, barge-in, VAD preservados
- Modulo AMI e isolado — se falhar, conversa continua
- Fallback automatico via dialplan se destino nao atender
- Extensivel para futuras acoes (hold, conferencia) sem mudanca arquitetural
- Cleanup de chamadas gerenciado pelo Asterisk (sem bridges orfas)

### Negativas

- AMI e menos granular que ARI para cenarios complexos (ex: conferencia com 5+ participantes)
- Se no futuro precisarmos de controle fino de midia via Asterisk (ex: media fork nativo, audiohook), ARI pode se tornar necessario
- AMI nao suporta Stasis — nao podemos "pausar" o dialplan e tomar controle total do canal

### Riscos

- **Header X-Caller-Channel pode ser perdido** se intermediario SIP remover headers customizados. Mitigacao: Asterisk e Media Server estao na mesma rede Docker, sem proxy intermediario.
- **AMI Redirect durante RTP ativo** pode causar breve interrupcao de audio (~50-100ms). Mitigacao: TTS fala "aguarde" antes do redirect, caller espera transicao.
- **Fallback para AI Agent** apos transfer falha cria nova sessao (contexto da conversa anterior perdido). Mitigacao: aceitavel para v1; sessao persistente pode ser implementada depois.

---

## Evolucoes Futuras (fora desta ADR)

- **Hold explicito:** Media Server toca MOH localmente enquanto AI Agent processa
- **Conferencia:** Para 3+ participantes, avaliar ARI ou ConfBridge via AMI
- **Transfer consultiva:** Agente fala com destino antes de conectar caller
- **Sessao persistente:** Manter contexto da conversa apos fallback de transfer
- **Media fork nativo (Asterisk):** Se necessario ASR direto no Asterisk, avaliar ARI com externalMedia

---

## Referencias

- [Asterisk AMI Documentation](https://docs.asterisk.org/Configuration/Interfaces/Asterisk-Manager-Interface-AMI/)
- [AMI Redirect Action](https://docs.asterisk.org/Asterisk_18_Documentation/API_Documentation/AMI_Actions/Redirect/)
- [Asterisk ARI vs AMI](https://docs.asterisk.org/Configuration/Interfaces/)
- PRD original: "Agente de Voz com Controle de Chamadas via ARI" (analisado e rejeitado como abordagem)
- Projeto: theo-ai-voice-agent, branch create_ai_transcribe
