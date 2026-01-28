import { useEffect, useState } from 'react';
import { Wrench, Check, X, Loader2, MessageSquare } from 'lucide-react';
import { useAgentStore } from '../hooks/useAgentState';

interface Tool {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  source: string;
}

export function ToolPanel() {
  const { tools: executions } = useAgentStore();
  const [availableTools, setAvailableTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(false);

  // Fetch available tools
  useEffect(() => {
    const fetchTools = async () => {
      setLoading(true);
      try {
        const response = await fetch('/api/tools');
        if (response.ok) {
          const data = await response.json();
          setAvailableTools(data.tools || []);
        }
      } catch (error) {
        console.error('Error fetching tools:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchTools();
  }, []);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'executing':
        return <Loader2 size={16} className="animate-spin text-yellow-500" />;
      case 'completed':
        return <Check size={16} className="text-green-500" />;
      case 'error':
        return <X size={16} className="text-red-500" />;
      default:
        return <Wrench size={16} className="text-gray-500" />;
    }
  };

  return (
    <div className="h-full overflow-y-auto space-y-4">
      {/* Active Executions */}
      {executions.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold text-gray-400 uppercase">Execucoes</h3>
          {executions.slice(-5).reverse().map((execution) => (
            <div
              key={execution.id}
              className={`p-3 rounded-lg border ${
                execution.status === 'executing'
                  ? 'bg-yellow-500/10 border-yellow-500/30 tool-executing'
                  : execution.status === 'completed'
                  ? 'bg-green-500/10 border-green-500/30'
                  : execution.status === 'error'
                  ? 'bg-red-500/10 border-red-500/30'
                  : 'bg-gray-700/50 border-gray-600'
              }`}
            >
              <div className="flex items-center gap-2">
                {getStatusIcon(execution.status)}
                <span className="font-medium">{execution.name}</span>
              </div>

              {/* Feedback phrase */}
              {execution.feedback && (
                <div className="mt-2 flex items-center gap-2 text-sm text-gray-400">
                  <MessageSquare size={14} />
                  <span className="italic">"{execution.feedback}"</span>
                </div>
              )}

              {/* Result preview */}
              {execution.result && (
                <div className="mt-2 text-xs text-gray-400 bg-gray-800 rounded p-2 max-h-20 overflow-y-auto">
                  <pre className="whitespace-pre-wrap">
                    {JSON.stringify(execution.result, null, 2).slice(0, 200)}
                    {JSON.stringify(execution.result).length > 200 && '...'}
                  </pre>
                </div>
              )}

              {/* Error */}
              {execution.error && (
                <div className="mt-2 text-xs text-red-400">
                  {execution.error}
                </div>
              )}

              {/* Duration */}
              {execution.endTime && (
                <div className="mt-1 text-xs text-gray-500">
                  {execution.endTime - execution.startTime}ms
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Available Tools */}
      <div className="space-y-2">
        <h3 className="text-xs font-semibold text-gray-400 uppercase">
          Ferramentas Disponiveis ({availableTools.length})
        </h3>

        {loading ? (
          <div className="flex items-center justify-center py-4">
            <Loader2 size={20} className="animate-spin text-gray-500" />
          </div>
        ) : availableTools.length === 0 ? (
          <p className="text-sm text-gray-500">Nenhuma ferramenta disponivel</p>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {availableTools.map((tool) => (
              <div
                key={tool.name}
                className="p-2 rounded bg-gray-700/50 border border-gray-600 hover:border-gray-500 transition-colors"
                title={tool.description}
              >
                <div className="flex items-center gap-2">
                  <Wrench size={14} className="text-primary-400" />
                  <span className="text-sm font-medium truncate">{tool.name}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                  {tool.description}
                </p>
                <span className={`text-xs px-1.5 py-0.5 rounded mt-1 inline-block ${
                  tool.source === 'mcp'
                    ? 'bg-purple-500/20 text-purple-400'
                    : 'bg-blue-500/20 text-blue-400'
                }`}>
                  {tool.source}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
