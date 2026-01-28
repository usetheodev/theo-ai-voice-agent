import { useState } from 'react';
import { Brain, Search, Clock, Tag } from 'lucide-react';
import { useAgentStore } from '../hooks/useAgentState';

export function MemoryPanel() {
  const { episodes } = useAgentStore();
  const [searchQuery, setSearchQuery] = useState('');

  const filteredEpisodes = episodes.filter((ep) =>
    ep.summary.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const formatTimestamp = (timestamp: number) => {
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diff = now.getTime() - date.getTime();

    // Less than 1 hour
    if (diff < 3600000) {
      const minutes = Math.floor(diff / 60000);
      return `${minutes}min atras`;
    }

    // Less than 24 hours
    if (diff < 86400000) {
      const hours = Math.floor(diff / 3600000);
      return `${hours}h atras`;
    }

    // More than 24 hours
    return date.toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: 'short',
    });
  };

  return (
    <div className="h-full overflow-hidden flex flex-col">
      {/* Search */}
      <div className="relative mb-3">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          type="text"
          placeholder="Buscar episodios..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full pl-9 pr-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-primary-500"
        />
      </div>

      {/* Episodes List */}
      <div className="flex-1 overflow-y-auto space-y-2">
        {filteredEpisodes.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-gray-500">
            <Brain size={32} className="mb-2 opacity-50" />
            <p className="text-sm text-center">
              {searchQuery
                ? 'Nenhum episodio encontrado'
                : 'Nenhum episodio na memoria'}
            </p>
            <p className="text-xs text-center mt-1">
              Os episodios aparecerao aqui durante a conversa
            </p>
          </div>
        ) : (
          filteredEpisodes.map((episode) => (
            <div key={episode.id} className="episode-card">
              <div className="flex items-start gap-2">
                <Brain size={16} className="text-purple-400 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-200 line-clamp-2">
                    {episode.summary}
                  </p>
                  <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                      <Clock size={12} />
                      {formatTimestamp(episode.timestamp)}
                    </span>
                    <span className="text-gray-600 truncate">
                      {episode.id.slice(0, 8)}...
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Memory Stats */}
      {episodes.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700 flex items-center justify-between text-xs text-gray-500">
          <span>{episodes.length} episodios</span>
          <span className="flex items-center gap-1">
            <Tag size={12} />
            Memoria ativa
          </span>
        </div>
      )}
    </div>
  );
}
