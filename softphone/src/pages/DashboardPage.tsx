import { Activity, Phone, Clock, TrendingUp } from 'lucide-react'

export function DashboardPage() {
  return (
    <div className="page dashboard-page">
      <header className="page-header">
        <h1>
          <Activity size={24} />
          Dashboard
        </h1>
      </header>

      <div className="dashboard-grid">
        <div className="stat-card">
          <div className="stat-icon">
            <Phone size={24} />
          </div>
          <div className="stat-content">
            <span className="stat-value">--</span>
            <span className="stat-label">Chamadas Hoje</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">
            <Clock size={24} />
          </div>
          <div className="stat-content">
            <span className="stat-value">--</span>
            <span className="stat-label">Tempo Medio</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">
            <TrendingUp size={24} />
          </div>
          <div className="stat-content">
            <span className="stat-value">--</span>
            <span className="stat-label">Transcricoes</span>
          </div>
        </div>
      </div>

      <div className="coming-soon">
        <Activity size={48} />
        <h2>Em Desenvolvimento</h2>
        <p>
          O dashboard com metricas em tempo real estara disponivel em breve.
          Acompanhe chamadas, transcricoes e analises de sentimento.
        </p>
      </div>
    </div>
  )
}
