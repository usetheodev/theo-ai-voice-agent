# Monitoring Stack - Prometheus + Grafana

Este diretório contém a configuração completa do stack de monitoramento para o AI Voice Agent.

## Stack de Monitoramento

- **Prometheus**: Coleta e armazena métricas time-series
- **Grafana**: Visualização de métricas em dashboards interativos

## Iniciar o Monitoramento

### 1. Iniciar todos os serviços (incluindo monitoramento)

```bash
docker-compose --profile monitoring up -d
```

### 2. Verificar se os serviços estão rodando

```bash
docker-compose --profile monitoring ps
```

Você deve ver:
- `asterisk` - SIP Gateway
- `ai-voice-agent` - Nosso servidor RTP
- `prometheus` - Coletor de métricas
- `grafana` - Dashboard de visualização

## Acessar os Serviços

### Grafana
- **URL**: http://localhost:3000
- **Usuário**: `admin`
- **Senha**: `admin`

**Dashboard**: "AI Voice Agent - RTP Metrics"

### Prometheus
- **URL**: http://localhost:9090
- Query metrics diretamente no Prometheus Query UI

### AI Voice Agent Metrics (Raw)
- **Prometheus format**: http://localhost:8000/metrics
- **JSON format**: http://localhost:8000/metrics/rtp

## Dashboard do Grafana

O dashboard "AI Voice Agent - RTP Metrics" contém os seguintes painéis:

### Status Overview (Linha 1)
1. **RTP Server Status** - Verde quando rodando
2. **Active Sessions** - Número de chamadas ativas
3. **MOS Score** - Qualidade de áudio (1.0-5.0)
4. **Round-Trip Time** - Latência de rede em ms
5. **DTMF Events Total** - Total de teclas pressionadas

### RTP Performance (Linha 2)
6. **RTP Packet Rate** - Pacotes recebidos/perdidos por segundo
7. **Packet Loss Rate** - Percentual de perda de pacotes

### Network Quality (Linha 3)
8. **Jitter** - Variação de latência em ms
9. **RTCP Round-Trip Time** - Latência medida via RTCP

### Audio Quality Over Time (Linha 4)
10. **MOS Score Over Time** - Evolução da qualidade de áudio
11. **DTMF Events Rate** - Eventos DTMF por minuto

### Network Throughput (Linha 5)
12. **Network Throughput** - Banda RX/TX em bytes/sec

## Métricas Disponíveis

### Prometheus Metrics (expostas em `/metrics`)

| Métrica | Tipo | Descrição |
|---------|------|-----------|
| `rtp_server_running` | gauge | Status do servidor (0=parado, 1=rodando) |
| `rtp_active_sessions` | gauge | Número de sessões ativas |
| `rtp_packets_received_total` | counter | Total de pacotes RTP recebidos |
| `rtp_packets_lost_total` | counter | Total de pacotes RTP perdidos |
| `rtp_packet_loss_rate_percent` | gauge | Taxa de perda de pacotes (%) |
| `rtp_bytes_received_total` | counter | Total de bytes recebidos |
| `rtp_bytes_sent_total` | counter | Total de bytes enviados |
| `rtp_mos_score` | gauge | Mean Opinion Score (1.0-5.0) |
| `rtp_jitter_ms` | gauge | Jitter médio em ms |
| `rtcp_rtt_ms` | gauge | Round-Trip Time em ms (via RTCP) |
| `dtmf_events_total` | counter | Total de eventos DTMF detectados |

### Interpretação do MOS Score

| MOS Score | Qualidade | Descrição |
|-----------|-----------|-----------|
| 4.3 - 5.0 | Excelente | Qualidade de telefone fixo |
| 4.0 - 4.3 | Boa | Aceitável para a maioria dos usuários |
| 3.6 - 4.0 | Razoável | Alguns usuários insatisfeitos |
| 3.1 - 3.6 | Pobre | Muitos usuários insatisfeitos |
| 1.0 - 3.1 | Ruim | Quase todos os usuários insatisfeitos |

## Parar o Monitoramento

```bash
# Parar todos os serviços
docker-compose --profile monitoring down

# Parar e remover volumes (APAGA DADOS)
docker-compose --profile monitoring down -v
```

## Configuração

### Prometheus (`prometheus.yml`)
- Scrape interval: 15s
- Targets: `voiceagent:8000`
- Métricas coletadas: `rtp_*`, `rtcp_*`, `dtmf_*`

### Grafana
- Datasource: Prometheus (auto-provisionado)
- Dashboard: Auto-provisionado via JSON
- Refresh: 5 segundos

## Troubleshooting

### Métricas não aparecem no Grafana

1. Verificar se o AI Voice Agent está expondo métricas:
```bash
curl http://localhost:8000/metrics
```

2. Verificar se o Prometheus está coletando:
```bash
# Acessar http://localhost:9090
# Executar query: rtp_server_running
```

3. Verificar logs do Prometheus:
```bash
docker logs prometheus
```

### Grafana não mostra o dashboard

1. Verificar se o datasource está configurado:
   - Acessar: Configuration → Data Sources
   - Deve ter "Prometheus" com URL `http://prometheus:9090`

2. Verificar logs do Grafana:
```bash
docker logs grafana
```

3. Re-importar o dashboard manualmente:
   - Dashboards → Import
   - Copiar conteúdo de `monitoring/grafana/dashboards/ai-voice-agent-dashboard.json`

## Exemplo de Queries PromQL

### Taxa de perda de pacotes nas últimas 5 minutos
```promql
rate(rtp_packets_lost_total[5m]) / rate(rtp_packets_received_total[5m]) * 100
```

### MOS Score abaixo de 4.0 (qualidade ruim)
```promql
rtp_mos_score < 4.0
```

### RTT acima de 150ms (latência alta)
```promql
rtcp_rtt_ms > 150
```

### DTMF events por hora
```promql
increase(dtmf_events_total[1h])
```

## Estrutura de Arquivos

```
monitoring/
├── README.md                          # Este arquivo
├── prometheus.yml                     # Configuração do Prometheus
└── grafana/
    ├── datasources/
    │   └── prometheus.yml             # Datasource auto-provisionado
    └── dashboards/
        ├── dashboard-provider.yml     # Provisionamento de dashboards
        └── ai-voice-agent-dashboard.json  # Dashboard principal
```

## Referências

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [PromQL Cheat Sheet](https://promlabs.com/promql-cheat-sheet/)
