import { useState, useCallback } from 'react'
import {
  Search,
  Clock,
  User,
  Headphones,
  AlertCircle,
  Loader2,
  Filter,
  X,
} from 'lucide-react'
import { searchApi, SearchResult, SearchResponse } from '../services/searchApi'

export function SearchPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filtros
  const [showFilters, setShowFilters] = useState(false)
  const [speaker, setSpeaker] = useState<'caller' | 'agent' | ''>('')
  const [limit, setLimit] = useState(10)
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return

    setLoading(true)
    setError(null)

    try {
      const response = await searchApi.search({
        query: query.trim(),
        limit,
        speaker: speaker || undefined,
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        hybrid: true,
      })
      setResults(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao buscar')
      setResults(null)
    } finally {
      setLoading(false)
    }
  }, [query, limit, speaker, fromDate, toDate])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  const clearFilters = () => {
    setSpeaker('')
    setLimit(10)
    setFromDate('')
    setToDate('')
  }

  const formatDate = (isoDate: string) => {
    return new Date(isoDate).toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const formatDuration = (ms: number) => {
    const seconds = Math.round(ms / 1000)
    return `${seconds}s`
  }

  return (
    <div className="page search-page">
      <header className="page-header">
        <h1>
          <Search size={24} />
          Busca Semantica
        </h1>
      </header>

      {/* Barra de busca */}
      <div className="search-bar-container">
        <div className="search-bar">
          <Search size={20} className="search-icon" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Busque por conceitos, frases ou palavras-chave..."
            className="search-input"
          />
          {query && (
            <button className="clear-btn" onClick={() => setQuery('')}>
              <X size={18} />
            </button>
          )}
        </div>

        <button
          className={`btn btn-secondary filter-btn ${showFilters ? 'active' : ''}`}
          onClick={() => setShowFilters(!showFilters)}
        >
          <Filter size={18} />
          Filtros
        </button>

        <button
          className="btn btn-primary search-btn"
          onClick={handleSearch}
          disabled={loading || !query.trim()}
        >
          {loading ? <Loader2 size={18} className="spin" /> : <Search size={18} />}
          Buscar
        </button>
      </div>

      {/* Filtros */}
      {showFilters && (
        <div className="filters-panel card">
          <div className="filters-grid">
            <div className="form-group">
              <label>Speaker</label>
              <select value={speaker} onChange={(e) => setSpeaker(e.target.value as any)}>
                <option value="">Todos</option>
                <option value="caller">Caller (Cliente)</option>
                <option value="agent">Agent (Agente)</option>
              </select>
            </div>

            <div className="form-group">
              <label>Limite de resultados</label>
              <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
                <option value={5}>5 resultados</option>
                <option value={10}>10 resultados</option>
                <option value={20}>20 resultados</option>
                <option value={50}>50 resultados</option>
              </select>
            </div>

            <div className="form-group">
              <label>Data inicial</label>
              <input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Data final</label>
              <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
            </div>
          </div>

          <button className="btn btn-secondary btn-small" onClick={clearFilters}>
            Limpar filtros
          </button>
        </div>
      )}

      {/* Erro */}
      {error && (
        <div className="error-message">
          <AlertCircle size={20} />
          <span>{error}</span>
        </div>
      )}

      {/* Resultados */}
      {results && (
        <div className="search-results">
          <div className="results-header">
            <span className="results-count">
              {results.total} resultado{results.total !== 1 ? 's' : ''} encontrado
              {results.total !== 1 ? 's' : ''}
            </span>
            <span className="results-latency">
              Embedding: {results.embedding_latency_ms.toFixed(1)}ms
            </span>
          </div>

          {results.results.length === 0 ? (
            <div className="no-results">
              <Search size={48} />
              <p>Nenhum resultado encontrado para "{results.query}"</p>
              <span>Tente outros termos ou ajuste os filtros</span>
            </div>
          ) : (
            <div className="results-list">
              {results.results.map((result) => (
                <ResultCard key={result.id} result={result} formatDate={formatDate} formatDuration={formatDuration} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Estado inicial */}
      {!results && !loading && !error && (
        <div className="search-placeholder">
          <Search size={64} />
          <h2>Busca Semantica de Transcricoes</h2>
          <p>
            Pesquise por conceitos, frases ou palavras-chave nas transcricoes de chamadas.
            A busca semantica encontra resultados por significado, nao apenas por palavras
            exatas.
          </p>
          <div className="search-tips">
            <h3>Exemplos de busca:</h3>
            <ul>
              <li>"cliente reclamou do atendimento"</li>
              <li>"problema com pagamento"</li>
              <li>"cancelar pedido"</li>
              <li>"duvida sobre produto"</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

interface ResultCardProps {
  result: SearchResult
  formatDate: (date: string) => string
  formatDuration: (ms: number) => string
}

function ResultCard({ result, formatDate, formatDuration }: ResultCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className={`result-card ${expanded ? 'expanded' : ''}`} onClick={() => setExpanded(!expanded)}>
      <div className="result-main">
        <div className="result-speaker">
          {result.speaker === 'agent' ? (
            <Headphones size={16} />
          ) : (
            <User size={16} />
          )}
          <span>{result.speaker === 'agent' ? 'Agente' : 'Cliente'}</span>
        </div>

        <p className="result-text">{result.text}</p>

        <div className="result-meta">
          <span className="result-score" title="Score de relevancia">
            {(result.score * 100).toFixed(0)}%
          </span>
          <span className="result-date">
            <Clock size={14} />
            {formatDate(result.timestamp)}
          </span>
          <span className="result-duration">{formatDuration(result.audio_duration_ms)}</span>
        </div>
      </div>

      {expanded && (
        <div className="result-details">
          <div className="detail-row">
            <span className="detail-label">Session ID:</span>
            <code>{result.session_id}</code>
          </div>
          <div className="detail-row">
            <span className="detail-label">Call ID:</span>
            <code>{result.call_id}</code>
          </div>
          <div className="detail-row">
            <span className="detail-label">ID:</span>
            <code>{result.id}</code>
          </div>
        </div>
      )}
    </div>
  )
}
