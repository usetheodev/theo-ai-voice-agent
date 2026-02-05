import { Settings, Server, Volume2, Bell } from 'lucide-react'

export function SettingsPage() {
  return (
    <div className="page settings-page">
      <header className="page-header">
        <h1>
          <Settings size={24} />
          Configuracoes
        </h1>
      </header>

      <div className="settings-sections">
        <section className="card settings-section">
          <h2>
            <Server size={20} />
            Servidor
          </h2>
          <div className="form-group">
            <label>URL da API de Busca</label>
            <input
              type="text"
              defaultValue={import.meta.env.VITE_SEARCH_API_URL || 'http://localhost:8767'}
              disabled
            />
            <small>Configurado via variavel de ambiente VITE_SEARCH_API_URL</small>
          </div>
        </section>

        <section className="card settings-section">
          <h2>
            <Volume2 size={20} />
            Audio
          </h2>
          <div className="form-group">
            <label>Dispositivo de Entrada</label>
            <select disabled>
              <option>Microfone padrao do sistema</option>
            </select>
          </div>
          <div className="form-group">
            <label>Dispositivo de Saida</label>
            <select disabled>
              <option>Alto-falante padrao do sistema</option>
            </select>
          </div>
        </section>

        <section className="card settings-section">
          <h2>
            <Bell size={20} />
            Notificacoes
          </h2>
          <div className="form-group checkbox-group">
            <label>
              <input type="checkbox" defaultChecked disabled />
              Notificar chamadas recebidas
            </label>
          </div>
          <div className="form-group checkbox-group">
            <label>
              <input type="checkbox" defaultChecked disabled />
              Som de toque para chamadas
            </label>
          </div>
        </section>
      </div>

      <div className="coming-soon">
        <Settings size={48} />
        <h2>Configuracoes Adicionais</h2>
        <p>
          Mais opcoes de configuracao estarao disponiveis em breve,
          incluindo temas, atalhos de teclado e preferencias de audio.
        </p>
      </div>
    </div>
  )
}
