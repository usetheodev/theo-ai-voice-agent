import { Activity, Clock, Zap, MessageSquare } from 'lucide-react';
import { useAgentStore } from '../hooks/useAgentState';

export function MetricsBar() {
  const { metrics } = useAgentStore();

  const formatLatency = (ms: number | null) => {
    if (ms === null) return '-';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <div className="panel py-3">
      <div className="grid grid-cols-4 gap-4">
        {/* Turn Count */}
        <div className="metric">
          <div className="flex items-center gap-1 text-gray-500 mb-1">
            <MessageSquare size={14} />
          </div>
          <span className="metric-value">{metrics.turnCount}</span>
          <span className="metric-label">Turnos</span>
        </div>

        {/* TTFA - Time to First Audio */}
        <div className="metric">
          <div className="flex items-center gap-1 text-gray-500 mb-1">
            <Zap size={14} />
          </div>
          <span className="metric-value">
            {formatLatency(metrics.latency.ttfaMs)}
          </span>
          <span className="metric-label">TTFA</span>
        </div>

        {/* TTFT - Time to First Token */}
        <div className="metric">
          <div className="flex items-center gap-1 text-gray-500 mb-1">
            <Activity size={14} />
          </div>
          <span className="metric-value">
            {formatLatency(metrics.latency.ttftMs)}
          </span>
          <span className="metric-label">TTFT</span>
        </div>

        {/* E2E - End to End */}
        <div className="metric">
          <div className="flex items-center gap-1 text-gray-500 mb-1">
            <Clock size={14} />
          </div>
          <span className="metric-value">
            {formatLatency(metrics.latency.e2eMs)}
          </span>
          <span className="metric-label">E2E</span>
        </div>
      </div>

      {/* Latency explanation */}
      <div className="mt-3 pt-2 border-t border-gray-700 text-xs text-gray-500 flex justify-center gap-4">
        <span title="Time to First Audio: VAD end to first audio played">TTFA: Latencia ate primeiro audio</span>
        <span title="Time to First Token: ASR end to first LLM token">TTFT: Latencia ate primeiro token</span>
      </div>
    </div>
  );
}
