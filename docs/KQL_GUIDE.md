# KQL Guide - Voice Transcriptions

Guia prático do **Kibana Query Language (KQL)** para consultar transcrições de voz no índice `voice-transcriptions-*`.

> **Acesso**: Kibana em `http://localhost:5601` → Discover → Data View: `voice-transcriptions-*`

---

## Índice

1. [O que é KQL](#1-o-que-é-kql)
2. [Campos Disponíveis](#2-campos-disponíveis)
3. [Sintaxe Básica](#3-sintaxe-básica)
4. [Busca por Texto Livre](#4-busca-por-texto-livre)
5. [Busca por Campo Específico](#5-busca-por-campo-específico)
6. [Operadores Lógicos](#6-operadores-lógicos)
7. [Wildcards](#7-wildcards)
8. [Range Queries (Intervalos)](#8-range-queries-intervalos)
9. [Verificação de Existência](#9-verificação-de-existência)
10. [Campos Aninhados](#10-campos-aninhados)
11. [Cenários Reais de Investigação](#11-cenários-reais-de-investigação)
12. [Referência Rápida](#12-referência-rápida)
13. [Limitações do KQL](#13-limitações-do-kql)
14. [Dicas de Produtividade](#14-dicas-de-produtividade)

---

## 1. O que é KQL

KQL (Kibana Query Language) é a linguagem de consulta nativa do Kibana. Ela traduz queries textuais simples para o Elasticsearch Query DSL nos bastidores.

**Características:**
- Somente leitura (filtragem) — não faz agregações, transformações ou mutations
- Autocomplete nativo na barra de busca do Kibana
- Persiste entre aplicações (Discover, Dashboards, Lens)
- Suporta campos aninhados e wildcards

**Onde usar:**
- Barra de busca no **Discover**
- Filtros em **Dashboards**
- Filtros em **Lens** (visualizações)
- Alertas no **Rules**

> Para trocar entre KQL e Lucene, clique no label de linguagem à direita da barra de busca.

---

## 2. Campos Disponíveis

Campos indexados no `voice-transcriptions-YYYY.MM`:

| Campo | Tipo | Descrição | Exemplo |
|-------|------|-----------|---------|
| `utterance_id` | keyword | UUID único da utterance | `"a1b2c3d4-..."` |
| `session_id` | keyword | ID da sessão WebSocket | `"sess-001"` |
| `call_id` | keyword | ID da chamada SIP | `"call-abc-123"` |
| `text` | text (portuguese_analyzer) | Texto transcrito | `"olá, preciso de ajuda"` |
| `text.raw` | keyword | Texto exato (sem análise) | match exato |
| `timestamp` | date | Timestamp UTC ISO | `"2026-02-05T14:30:00Z"` |
| `audio_duration_ms` | integer | Duração do áudio (ms) | `2500` |
| `transcription_latency_ms` | integer | Latência STT (ms) | `180` |
| `language` | keyword | Código ISO-639-1 | `"pt"` |
| `language_probability` | float | Confiança do idioma (0-1) | `0.95` |
| `speaker` | keyword | Quem falou | `"caller"` ou `"agent"` |
| `caller_id` | keyword | Telefone do chamador | `"+5511999999999"` |
| `sentiment_label` | keyword | Sentimento detectado | `"positive"`, `"negative"`, `"neutral"` |
| `sentiment_score` | float | Score sentimento (-1 a 1) | `-0.8` |
| `topics` | keyword | Tópicos detectados | `"reclamação"` |
| `intent` | keyword | Intenção detectada | `"cancelar_plano"` |
| `embedding_model` | keyword | Modelo de embedding | `"intfloat/multilingual-e5-small"` |
| `embedding_latency_ms` | float | Latência do embedding (ms) | `15.3` |

---

## 3. Sintaxe Básica

```
campo: valor                    → match exato (keyword) ou analisado (text)
campo: "valor com espaços"      → match de frase
campo: valor1 OR campo: valor2  → operador lógico
campo > número                  → range (maior que)
NOT campo: valor                → negação
```

**Regras:**
- Strings com espaços **devem** estar entre aspas: `text: "preciso de ajuda"`
- Operadores lógicos (`AND`, `OR`, `NOT`) são **case-insensitive**
- Parênteses agrupam condições: `(A OR B) AND C`
- Campos `keyword` fazem match exato; campos `text` passam pelo analyzer

---

## 4. Busca por Texto Livre

Busca em **todos os campos** do documento.

```
ajuda
```
> Retorna qualquer documento que contenha "ajuda" em qualquer campo.

```
"preciso cancelar"
```
> Busca a frase exata "preciso cancelar" em qualquer campo.

```
erro timeout
```
> Busca documentos que contenham "erro" **OR** "timeout" em qualquer campo.

### Quando usar
- Exploração inicial, quando você não sabe em qual campo o dado está
- Busca rápida por palavras-chave

### Cuidado
- Texto livre é mais lento — prefira especificar o campo quando souber qual é

---

## 5. Busca por Campo Específico

### 5.1 Campos keyword (match exato)

```
speaker: "caller"
```
> Todas as utterances do chamador (cliente).

```
speaker: "agent"
```
> Todas as utterances do agente AI.

```
call_id: "call-abc-123"
```
> Todos os documentos de uma chamada específica.

```
session_id: "sess-001"
```
> Todos os documentos de uma sessão WebSocket específica.

```
language: "pt"
```
> Transcrições em português.

```
language: "es"
```
> Transcrições em espanhol (caso detectado).

```
sentiment_label: "negative"
```
> Utterances com sentimento negativo.

```
intent: "cancelar_plano"
```
> Utterances com intenção de cancelamento detectada.

```
topics: "reclamação"
```
> Utterances classificadas com o tópico "reclamação".

### 5.2 Campos text (analisados pelo portuguese_analyzer)

```
text: "ajuda"
```
> Busca a palavra "ajuda" no texto transcrito. O analyzer português trata stemming, então também retorna "ajudas", "ajudar", etc.

```
text: "quero cancelar meu plano"
```
> Busca a frase no texto transcrito. O analyzer tokeniza e normaliza cada palavra.

### 5.3 Campo text.raw (match exato do texto completo)

```
text.raw: "Olá, preciso de ajuda com minha conta"
```
> Match exato — a string inteira precisa ser idêntica (case-sensitive, sem stemming).

---

## 6. Operadores Lógicos

### AND (implícito e explícito)

```
speaker: "caller" AND sentiment_label: "negative"
```
> Utterances do chamador com sentimento negativo.

```
speaker: "caller" sentiment_label: "negative"
```
> Mesmo resultado — `AND` é implícito quando não há operador entre condições.

### OR

```
sentiment_label: "negative" OR sentiment_label: "neutral"
```
> Utterances com sentimento negativo ou neutro.

```
speaker: "caller" OR speaker: "agent"
```
> Todas as utterances (ambos os speakers).

```
intent: "cancelar_plano" OR intent: "reclamar"
```
> Utterances com intenção de cancelar ou reclamar.

### NOT

```
NOT speaker: "agent"
```
> Exclui utterances do agente (retorna só caller e outros).

```
NOT language: "pt"
```
> Utterances que NÃO são em português.

```
NOT sentiment_label: "positive"
```
> Exclui sentimento positivo (retorna negative e neutral).

### Combinações com parênteses

```
speaker: "caller" AND (sentiment_label: "negative" OR sentiment_label: "neutral")
```
> Utterances do caller que têm sentimento negativo ou neutro.

```
(intent: "cancelar_plano" OR intent: "trocar_plano") AND speaker: "caller"
```
> Caller com intenção de cancelar ou trocar plano.

```
text: "cancelar" AND NOT speaker: "agent"
```
> A palavra "cancelar" aparece, mas não foi dita pelo agente.

```
(speaker: "caller" AND sentiment_label: "negative") AND NOT intent: "saudacao"
```
> Caller insatisfeito, excluindo saudações iniciais.

---

## 7. Wildcards

Wildcards funcionam em campos **keyword** e **text**.

### Asterisco `*` — zero ou mais caracteres

```
caller_id: "+5511*"
```
> Chamadores com DDD 11 (São Paulo).

```
caller_id: "+5521*"
```
> Chamadores com DDD 21 (Rio de Janeiro).

```
call_id: "call-abc-*"
```
> Todas as chamadas que começam com "call-abc-".

```
intent: "cancelar_*"
```
> Todas as intenções que começam com "cancelar_" (cancelar_plano, cancelar_assinatura, etc.).

```
text: "cancel*"
```
> Palavras que começam com "cancel" (cancelar, cancelamento, cancelei).

```
session_id: "*prod*"
```
> Sessions que contêm "prod" em qualquer posição.

### Interrogação `?` — exatamente um caractere

```
language: "p?"
```
> Idiomas com código de 2 letras começando com "p" (pt, pl, etc.).

```
speaker: "c????r"
```
> Match de "caller" (c + 4 caracteres + r).

---

## 8. Range Queries (Intervalos)

Range queries funcionam em campos numéricos (`integer`, `float`) e `date`.

### Operadores: `>`, `>=`, `<`, `<=`

### 8.1 Latência de transcrição

```
transcription_latency_ms > 500
```
> Transcrições que demoraram mais de 500ms (lento).

```
transcription_latency_ms >= 200 AND transcription_latency_ms <= 500
```
> Latência entre 200ms e 500ms (aceitável mas monitorar).

```
transcription_latency_ms < 100
```
> Transcrições rápidas (abaixo de 100ms).

### 8.2 Duração do áudio

```
audio_duration_ms > 10000
```
> Utterances com mais de 10 segundos (falas longas).

```
audio_duration_ms < 500
```
> Utterances muito curtas — possível ruído ou falso positivo do VAD.

```
audio_duration_ms >= 2000 AND audio_duration_ms <= 5000
```
> Utterances entre 2 e 5 segundos (duração típica de uma frase).

### 8.3 Probabilidade do idioma

```
language_probability < 0.7
```
> Detecção de idioma com baixa confiança — vale investigar qualidade do áudio.

```
language_probability >= 0.95
```
> Alta confiança na detecção do idioma.

### 8.4 Sentimento

```
sentiment_score < -0.5
```
> Sentimento fortemente negativo.

```
sentiment_score > 0.5
```
> Sentimento fortemente positivo.

```
sentiment_score >= -0.2 AND sentiment_score <= 0.2
```
> Sentimento neutro (próximo de zero).

### 8.5 Latência de embedding

```
embedding_latency_ms > 50
```
> Embedding demorou mais de 50ms — possível gargalo.

### 8.6 Timestamps (combinado com date picker)

> **Nota:** Para filtros de data, prefira usar o **date picker** do Kibana (canto superior direito). KQL com datas é menos intuitivo. Porém, é possível:

```
timestamp >= "2026-02-01" AND timestamp < "2026-02-06"
```
> Transcrições da primeira semana de fevereiro de 2026.

```
timestamp >= "2026-02-05T14:00:00" AND timestamp <= "2026-02-05T15:00:00"
```
> Transcrições de uma hora específica.

---

## 9. Verificação de Existência

Verifica se um campo **existe** (tem valor) no documento.

```
caller_id: *
```
> Documentos que têm `caller_id` preenchido.

```
NOT caller_id: *
```
> Documentos sem `caller_id` (campo ausente ou null).

```
sentiment_label: *
```
> Documentos que passaram pela análise de sentimento.

```
NOT sentiment_label: *
```
> Documentos que ainda não têm análise de sentimento.

```
intent: *
```
> Documentos com intenção detectada.

```
text_embedding: *
```
> Documentos que têm embedding gerado.

```
topics: *
```
> Documentos com pelo menos um tópico classificado.

### Caso de uso: encontrar dados incompletos

```
NOT sentiment_label: * AND NOT intent: *
```
> Documentos sem sentimento E sem intenção — enriquecimento pode ter falhado.

```
text: * AND NOT text_embedding: *
```
> Tem texto mas não tem embedding — possível falha no embedding provider.

---

## 10. Campos Aninhados

O campo `metadata` é do tipo `object`, permitindo subcampos dinâmicos.

```
metadata.source: "ivr"
```
> Transcrições originadas da URA.

```
metadata.department: "suporte"
```
> Transcrições do departamento de suporte.

```
metadata.priority: "high"
```
> Transcrições marcadas como alta prioridade.

> **Nota:** Os subcampos de `metadata` dependem do que é enviado na indexação. Verifique os campos disponíveis no Discover clicando em "Available fields" no painel esquerdo.

---

## 11. Cenários Reais de Investigação

### Cenário 1: Chamada com problema — investigar toda a conversa

**Situação:** Recebemos reclamação sobre uma chamada específica.

```
call_id: "call-abc-123"
```
> Ordene por `timestamp` (asc) para ver a conversa na ordem cronológica.

### Cenário 2: Clientes insatisfeitos hoje

```
speaker: "caller" AND sentiment_label: "negative"
```
> Com o date picker setado para "Today". Identifique padrões de insatisfação.

### Cenário 3: Agente AI com respostas lentas

```
speaker: "agent" AND transcription_latency_ms > 500
```
> Latência alta na transcrição do agente pode indicar pipeline lento.

### Cenário 4: Qualidade de áudio ruim (baixa confiança no idioma)

```
language_probability < 0.6
```
> Quando o Whisper não tem confiança no idioma, geralmente o áudio está ruim (ruído, conexão instável, codec degradado).

### Cenário 5: Utterances muito curtas (possível ruído/VAD falso positivo)

```
audio_duration_ms < 300 AND NOT text: *
```
> Áudio curto e sem texto — provavelmente ruído que passou pelo VAD.

```
audio_duration_ms < 300 AND text: *
```
> Áudio curto mas com texto — pode ser "sim", "não", "ok" (válido).

### Cenário 6: Picos de latência no STT

```
transcription_latency_ms > 1000
```
> Transcrições que demoraram mais de 1 segundo. Correlacione com `timestamp` para ver se é um pico pontual ou degradação contínua.

### Cenário 7: Buscar menções a cancelamento

```
text: "cancelar" OR text: "cancelamento" OR text: "desistir"
```
> Com o analyzer português, `text: "cancelar"` já cobre variações de stemming. Mas ser explícito com sinônimos melhora o recall.

### Cenário 8: Agente AI respondendo sobre um tema específico

```
speaker: "agent" AND text: "política de reembolso"
```
> Ver como o agente está respondendo sobre reembolso.

### Cenário 9: Chamadas de um DDD específico com problemas

```
caller_id: "+5511*" AND sentiment_label: "negative"
```
> Chamadores de SP com sentimento negativo.

### Cenário 10: Sessões sem enriquecimento

```
NOT sentiment_label: * AND NOT topics: * AND NOT intent: *
```
> Documentos sem nenhum enriquecimento — possível falha no pipeline.

### Cenário 11: Comparar caller vs agent em uma chamada

```
call_id: "call-abc-123" AND speaker: "caller"
```
> Depois troque para:
```
call_id: "call-abc-123" AND speaker: "agent"
```
> Compare lado a lado o que cada um disse.

### Cenário 12: Volume de chamadas com intenção crítica

```
intent: "cancelar_plano" AND speaker: "caller"
```
> Quantos clientes estão querendo cancelar? Use com dashboard para ver tendência.

### Cenário 13: Transcrições em idioma inesperado

```
NOT language: "pt"
```
> Transcrições que não são em português — pode ser problema de detecção ou chamador falando outro idioma.

### Cenário 14: Investigar chamada completa com contexto de latência

```
call_id: "call-abc-123" AND transcription_latency_ms > 300
```
> Quais partes da chamada tiveram latência alta?

### Cenário 15: Busca complexa multi-critério

```
speaker: "caller" AND sentiment_label: "negative" AND transcription_latency_ms > 500 AND audio_duration_ms > 3000
```
> Caller insatisfeito + latência alta + fala longa — provavelmente uma reclamação detalhada que demorou para processar.

---

## 12. Referência Rápida

### Operadores

| Operador | Sintaxe | Exemplo |
|----------|---------|---------|
| Igual | `campo: valor` | `speaker: "caller"` |
| E | `AND` | `speaker: "caller" AND language: "pt"` |
| Ou | `OR` | `language: "pt" OR language: "es"` |
| Negação | `NOT` | `NOT speaker: "agent"` |
| Maior que | `>` | `transcription_latency_ms > 500` |
| Maior ou igual | `>=` | `audio_duration_ms >= 1000` |
| Menor que | `<` | `language_probability < 0.7` |
| Menor ou igual | `<=` | `sentiment_score <= -0.5` |
| Wildcard multi | `*` | `caller_id: "+5511*"` |
| Wildcard single | `?` | `language: "p?"` |
| Existe | `campo: *` | `intent: *` |
| Não existe | `NOT campo: *` | `NOT caller_id: *` |
| Agrupamento | `()` | `(A OR B) AND C` |
| Frase exata | `"frase"` | `text: "preciso de ajuda"` |

### Campos mais usados para filtrar

| Objetivo | Query |
|----------|-------|
| Toda a conversa de uma chamada | `call_id: "ID"` |
| Só o que o cliente disse | `speaker: "caller"` |
| Só o que o agente disse | `speaker: "agent"` |
| Sentimento negativo | `sentiment_label: "negative"` |
| Latência alta (STT) | `transcription_latency_ms > 500` |
| Áudio curto (ruído?) | `audio_duration_ms < 300` |
| Idioma diferente de PT | `NOT language: "pt"` |
| DDD São Paulo | `caller_id: "+5511*"` |
| Intenção de cancelar | `intent: "cancelar_plano"` |
| Sem enriquecimento | `NOT sentiment_label: *` |

---

## 13. Limitações do KQL

| O que KQL **não** faz | Alternativa |
|------------------------|-------------|
| Agregações (count, avg, sum) | Use Lens/Visualize no Kibana ou ES\|QL |
| Transformações de dados | Use Transforms no Elasticsearch |
| Regex completo | Use Lucene syntax (`/regex/`) |
| Fuzzy search | Use Lucene syntax (`termo~2`) |
| Ordenação | Use os controles de coluna no Discover |
| Busca vetorial (kNN) | Use a API REST (`GET /api/search?q=...` na porta 8767) |
| Full-text scoring | KQL filtra; para ranking use a Search API |

### Quando usar cada linguagem

| Necessidade | Ferramenta |
|-------------|------------|
| Filtrar no Discover/Dashboard | **KQL** |
| Regex ou fuzzy search | **Lucene** (troque na barra de busca) |
| Agregações complexas | **ES\|QL** ou **Lens** |
| Busca semântica por similaridade | **HTTP API** (`localhost:8767/api/search`) |

---

## 14. Dicas de Produtividade

### 1. Use o autocomplete
Comece digitando o nome do campo e o Kibana sugere campos e valores existentes.

### 2. Salve queries frequentes
No Discover, clique em **Save** para salvar queries que você usa com frequência.

### 3. Combine KQL com filtros visuais
Adicione filtros clicando nos valores nas tabelas do Discover — eles são combinados com o KQL da barra.

### 4. Use o date picker para janelas temporais
Filtre por tempo no date picker (canto superior direito) ao invés de usar `timestamp` no KQL.

### 5. Pin filters
Pinfiltros persistem entre páginas do Kibana — útil para manter `speaker: "caller"` enquanto navega.

### 6. Exporte resultados
No Discover, use **Share → CSV** para exportar resultados filtrados.

### 7. Crie dashboards com filtros KQL
Cada painel do dashboard pode ter seu próprio filtro KQL — combine com filtros globais.

---

## Referências

- [Kibana Query Language (KQL) - Elastic Docs](https://www.elastic.co/guide/en/kibana/current/kuery-query.html)
- [Data View: `voice-transcriptions-*`](http://localhost:5601)
- [API de Busca Semântica: `http://localhost:8767/api/search`](http://localhost:8767)
- [Dashboard de Transcrições](http://localhost:5601/app/dashboards) (importar `observability/kibana/voice-transcriptions-dashboard.ndjson`)
