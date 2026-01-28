import { useState } from 'react';
import { Server, Plus, Trash2, Loader2, Check, X } from 'lucide-react';
import { useAgentStore } from '../hooks/useAgentState';

export function MCPPanel() {
  const { mcpServers, mcpTools } = useAgentStore();
  const [showAddForm, setShowAddForm] = useState(false);
  const [newServer, setNewServer] = useState({ name: '', url: '', transport: 'http' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAddServer = async () => {
    if (!newServer.name || !newServer.url) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/mcp/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newServer),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to connect');
      }

      setNewServer({ name: '', url: '', transport: 'http' });
      setShowAddForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async (serverName: string) => {
    try {
      await fetch(`/api/mcp/${serverName}`, { method: 'DELETE' });
    } catch (err) {
      console.error('Error disconnecting:', err);
    }
  };

  return (
    <div className="space-y-4">
      {/* Connected Servers */}
      <div className="space-y-2">
        {mcpServers.length === 0 ? (
          <p className="text-sm text-gray-500">Nenhum servidor MCP conectado</p>
        ) : (
          mcpServers.map((server) => (
            <div
              key={server}
              className="flex items-center justify-between p-2 bg-gray-700/50 rounded-lg"
            >
              <div className="flex items-center gap-2">
                <Server size={16} className="text-green-500" />
                <span className="text-sm">{server}</span>
              </div>
              <button
                onClick={() => handleDisconnect(server)}
                className="p-1 text-gray-500 hover:text-red-500 transition-colors"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Add Server Form */}
      {showAddForm ? (
        <div className="space-y-3 p-3 bg-gray-700/30 rounded-lg">
          <input
            type="text"
            placeholder="Nome do servidor"
            value={newServer.name}
            onChange={(e) => setNewServer({ ...newServer, name: e.target.value })}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-primary-500"
          />
          <input
            type="text"
            placeholder="URL (ex: http://localhost:3000)"
            value={newServer.url}
            onChange={(e) => setNewServer({ ...newServer, url: e.target.value })}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-primary-500"
          />
          <select
            value={newServer.transport}
            onChange={(e) => setNewServer({ ...newServer, transport: e.target.value })}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-primary-500"
          >
            <option value="http">HTTP</option>
            <option value="sse">SSE</option>
            <option value="stdio">STDIO</option>
          </select>

          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          <div className="flex gap-2">
            <button
              onClick={() => setShowAddForm(false)}
              className="btn btn-secondary flex-1 py-1.5"
              disabled={loading}
            >
              <X size={16} />
              Cancelar
            </button>
            <button
              onClick={handleAddServer}
              className="btn btn-primary flex-1 py-1.5"
              disabled={loading || !newServer.name || !newServer.url}
            >
              {loading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Check size={16} />
              )}
              Conectar
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setShowAddForm(true)}
          className="btn btn-secondary w-full py-2"
        >
          <Plus size={16} />
          Adicionar Servidor
        </button>
      )}

      {/* MCP Tools Count */}
      {mcpTools.length > 0 && (
        <div className="text-xs text-gray-500 text-center">
          {mcpTools.length} ferramentas MCP disponiveis
        </div>
      )}
    </div>
  );
}
