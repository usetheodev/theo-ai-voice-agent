# Download de Modelos ML — `download_models.sh`

## Por que este script existe

O pipeline de voz depende de 3 modelos ML que somam ~500MB:

| Modelo | Função | Lib | Tamanho aprox. |
|--------|--------|-----|----------------|
| **Whisper** (tiny) | STT — transcrição de fala | `faster-whisper` | ~150MB |
| **Kokoro** (82M) | TTS — síntese de voz | `kokoro` | ~200MB |
| **E5 multilingual** (small) | Embeddings — busca semântica | `sentence-transformers` | ~130MB |

Sem o script, os modelos só são baixados em dois momentos:

1. **No `docker build`** — Stage 4 do `Dockerfile.base` (lento, acoplado ao build)
2. **Na primeira execução** — o container baixa em runtime (imprevisível, depende de rede)

O script resolve isso: **pré-download explícito, fora do build, com feedback claro**.

## Quando usar

| Cenário | Comando |
|---------|---------|
| Setup inicial do projeto | `./download_models.sh` |
| Dev local sem Docker | `./download_models.sh` |
| CI/CD — aquecer cache antes do build | `./download_models.sh --cache-dir /mnt/ci-cache` |
| Trocar modelo Whisper (ex: tiny → small) | `./download_models.sh --only stt --whisper-model small` |
| Validar que tudo está instalado | `./download_models.sh --dry-run` |

## Uso

```bash
# Todos os modelos (padrão: whisper tiny)
./download_models.sh

# Whisper com modelo maior
./download_models.sh --whisper-model small
./download_models.sh --whisper-model medium
./download_models.sh --whisper-model large-v3

# Apenas um modelo específico
./download_models.sh --only stt          # Whisper
./download_models.sh --only tts          # Kokoro
./download_models.sh --only embeddings   # E5

# Cache em diretório customizado
./download_models.sh --cache-dir /mnt/models

# Ver o que faria sem baixar
./download_models.sh --dry-run

# Ajuda
./download_models.sh --help
```

## Flags

| Flag | Descrição | Default |
|------|-----------|---------|
| `--whisper-model <nome>` | Modelo Whisper a baixar | `tiny` |
| `--only <tipo>` | Baixa apenas um tipo: `stt`, `tts`, `embeddings` | todos |
| `--cache-dir <path>` | Diretório de cache (define `HF_HOME`) | `~/.cache/huggingface` |
| `--dry-run` | Mostra o que faria sem baixar | — |
| `-h`, `--help` | Mostra ajuda | — |

## Variáveis de ambiente

| Variável | Onde | Descrição | Default |
|----------|------|-----------|---------|
| `WHISPER_MODEL` | Script | Modelo Whisper (sobrescrito por `--whisper-model`) | `tiny` |
| `HF_HOME` | Script | Diretório de cache HuggingFace (sobrescrito por `--cache-dir`) | `~/.cache/huggingface` |
| `MODEL_CACHE_DIR` | Docker Compose | Diretório do host montado como `/root/.cache` nos containers | `~/.cache` |

## Modelos Whisper disponíveis

| Modelo | Parâmetros | Tamanho | VRAM | Velocidade | Qualidade |
|--------|-----------|---------|------|------------|-----------|
| `tiny` | 39M | ~150MB | ~1GB | Muito rápido | Básica |
| `base` | 74M | ~290MB | ~1GB | Rápido | Boa |
| `small` | 244M | ~960MB | ~2GB | Moderado | Muito boa |
| `medium` | 769M | ~3GB | ~5GB | Lento | Excelente |
| `large-v3` | 1.5B | ~6GB | ~10GB | Muito lento | Estado da arte |

Variantes `.en` (ex: `tiny.en`) são otimizadas para inglês.

Para telefonia em português com CPU, o **`tiny`** é o melhor custo-benefício. Se tiver GPU, considere `small`.

## Onde os modelos ficam

```
~/.cache/
├── huggingface/
│   └── hub/
│       ├── models--Systran--faster-whisper-tiny/   # Whisper STT
│       ├── models--hexgrad--Kokoro-82M/            # Kokoro TTS
│       └── models--intfloat--multilingual-e5-small/ # E5 embeddings
└── kokoro/                                          # Kokoro vozes
```

No Docker, o cache do host é montado via **bind mount** nos containers:

```yaml
# docker-compose.yml
services:
  ai-agent:
    volumes:
      - ${MODEL_CACHE_DIR:-~/.cache}:/root/.cache

  ai-transcribe:
    volumes:
      - ${MODEL_CACHE_DIR:-~/.cache}:/root/.cache
```

Isso significa que **modelos baixados no host ficam disponíveis imediatamente nos containers**, sem rebuild.

### Fluxo completo

```bash
# 1. Baixa modelos no host
./download_models.sh

# 2. Sobe os containers (já enxergam os modelos)
docker compose up -d
```

### Cache customizado

Se quiser usar um diretório diferente de `~/.cache`:

```bash
# Baixa para diretório customizado
./download_models.sh --cache-dir /mnt/models

# Sobe containers apontando para o mesmo diretório
MODEL_CACHE_DIR=/mnt/models docker compose up -d
```

Ou defina `MODEL_CACHE_DIR` no `.env` da raiz do projeto.

## Pré-requisitos

### Sistema operacional

| OS | Suporte | Notas |
|----|---------|-------|
| **Linux** | Nativo | Funciona direto |
| **macOS** | Nativo | Funciona direto |
| **Windows** | Via WSL2 | Requer WSL2 com Docker Desktop |

**Windows**: o script é bash e o bind mount usa `~/.cache` (expansão POSIX). No Windows, execute tudo de dentro do WSL2:

```powershell
# PowerShell: entrar no WSL2
wsl

# Dentro do WSL2: tudo funciona normalmente
cd ~/projetos/theo-ai-voice-agent
./download_models.sh
docker compose up -d
```

O Docker Desktop com backend WSL2 compartilha o daemon — `docker compose` rodado dentro do WSL2 funciona igual ao do host Windows.

### Libs Python

O script precisa das libs Python instaladas **antes** de rodar:

```bash
pip install -r requirements-models.txt
```

No contexto Docker, essas libs já estão na imagem `voice-base` (instaladas no `Dockerfile.base` Stage 3).

## Exit codes

| Código | Significado |
|--------|-------------|
| `0` | Todos os modelos baixados com sucesso |
| `1` | Erro de validação (argumento inválido, Python ausente) |
| `N` | N modelos falharam no download |

## Troubleshooting

### Modelo não baixa (timeout / rede)

HuggingFace Hub faz download via HTTPS. Se estiver atrás de proxy:

```bash
export HTTPS_PROXY=http://proxy:3128
./download_models.sh
```

### "No module named 'faster_whisper'"

As libs Python não estão instaladas. Instale com:

```bash
pip install -r requirements-models.txt
```

### Cache corrompido

Se um download falhou no meio, o HuggingFace pode ter deixado cache parcial:

```bash
# Remove cache do modelo específico e rebaixa
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-tiny/
./download_models.sh --only stt
```

### Warnings do PyTorch/Kokoro

Mensagens como `dropout option adds dropout after all but last recurrent layer` e `torch.nn.utils.weight_norm is deprecated` são **normais**. Vêm das libs internas do Kokoro, não afetam funcionalidade.

## Relação com o Dockerfile.base

O `Dockerfile.base` (Stage 4, linhas 107-144) faz o mesmo download durante o build via BuildKit cache. O script `download_models.sh` é **complementar**, não substituto:

| | `Dockerfile.base` | `download_models.sh` |
|---|---|---|
| **Quando roda** | `docker build` | Manual, antes ou fora do build |
| **Onde salva** | Imagem Docker (via `/tmp/hf-cache`) | Host local (`~/.cache/`) |
| **Cache** | BuildKit volumes (`voice-model-cache`) | Filesystem direto |
| **Uso principal** | CI/CD, build de produção | Dev local, pré-download, validação |

Com o bind mount no `docker-compose.yml`, o cache do host tem **prioridade** sobre os modelos embarcados na imagem — se o modelo existe em `~/.cache/`, o container usa esse ao invés do que foi baixado no build.
