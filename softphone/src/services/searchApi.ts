const API_BASE_URL = import.meta.env.VITE_SEARCH_API_URL || 'http://localhost:8767'

export interface SearchResult {
  id: string
  score: number
  text: string
  timestamp: string
  speaker: 'caller' | 'agent'
  session_id: string
  call_id: string
  audio_duration_ms: number
}

export interface SearchResponse {
  query: string
  total: number
  count: number
  embedding_latency_ms: number
  results: SearchResult[]
}

export interface SearchParams {
  query: string
  limit?: number
  speaker?: 'caller' | 'agent'
  hybrid?: boolean
  from_date?: string
  to_date?: string
}

export interface HealthStatus {
  status: string
  timestamp: string
  components: {
    elasticsearch: boolean
    embedding_provider: boolean
  }
}

class SearchApiService {
  private baseUrl: string

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl
  }

  async search(params: SearchParams): Promise<SearchResponse> {
    const searchParams = new URLSearchParams()
    searchParams.set('q', params.query)

    if (params.limit) searchParams.set('limit', params.limit.toString())
    if (params.speaker) searchParams.set('speaker', params.speaker)
    if (params.hybrid !== undefined) searchParams.set('hybrid', params.hybrid.toString())
    if (params.from_date) searchParams.set('from_date', params.from_date)
    if (params.to_date) searchParams.set('to_date', params.to_date)

    const response = await fetch(`${this.baseUrl}/api/search?${searchParams}`)

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Erro desconhecido' }))
      throw new Error(error.error || `HTTP ${response.status}`)
    }

    return response.json()
  }

  async healthCheck(): Promise<HealthStatus> {
    const response = await fetch(`${this.baseUrl}/api/health`)

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    return response.json()
  }
}

export const searchApi = new SearchApiService()
