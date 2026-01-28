import { useCallback, useState } from 'react';
import { Mic, MicOff, Phone, PhoneOff, Volume2, VolumeX, Settings } from 'lucide-react';
import { useWebRTC } from '../hooks/useWebRTC';
import { useAgentStore } from '../hooks/useAgentState';
import { AudioVisualizer } from './AudioVisualizer';
import { ChatPanel } from './ChatPanel';
import { ToolPanel } from './ToolPanel';
import { MemoryPanel } from './MemoryPanel';
import { MetricsBar } from './MetricsBar';
import { PermissionDialog } from './PermissionDialog';
import { MCPPanel } from './MCPPanel';

export function Dashboard() {
  const [micMuted, setMicMuted] = useState(false);
  const [speakerMuted, setSpeakerMuted] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const {
    connectionState,
    sessionId,
    error,
    connect,
    disconnect,
    setMicMuted: setMicMutedRTC,
    setSpeakerMuted: setSpeakerMutedRTC,
  } = useWebRTC();

  const { agentState, permissionRequest, reset } = useAgentStore();

  const handleConnect = useCallback(async () => {
    if (connectionState === 'connected') {
      disconnect();
      reset();
    } else {
      await connect();
    }
  }, [connectionState, connect, disconnect, reset]);

  const handleMicToggle = useCallback(() => {
    const newMuted = !micMuted;
    setMicMuted(newMuted);
    setMicMutedRTC(newMuted);
  }, [micMuted, setMicMutedRTC]);

  const handleSpeakerToggle = useCallback(() => {
    const newMuted = !speakerMuted;
    setSpeakerMuted(newMuted);
    setSpeakerMutedRTC(newMuted);
  }, [speakerMuted, setSpeakerMutedRTC]);

  const getStateColor = () => {
    switch (agentState) {
      case 'listening':
        return 'bg-yellow-500';
      case 'processing':
        return 'bg-blue-500';
      case 'speaking':
        return 'bg-green-500';
      case 'error':
        return 'bg-red-500';
      default:
        return 'bg-gray-500';
    }
  };

  const getStateText = () => {
    switch (agentState) {
      case 'idle':
        return 'Aguardando';
      case 'listening':
        return 'Ouvindo...';
      case 'processing':
        return 'Processando...';
      case 'speaking':
        return 'Falando...';
      case 'interrupted':
        return 'Interrompido';
      case 'error':
        return 'Erro';
      case 'ended':
        return 'Encerrado';
      default:
        return agentState;
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 flex flex-col">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700 px-6 py-4">
        <div className="flex items-center justify-between max-w-7xl mx-auto">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-semibold">Voice Pipeline Demo</h1>
            <div className="flex items-center gap-2">
              <div className={`status-dot ${connectionState === 'connected' ? 'connected' : 'disconnected'}`} />
              <span className="text-sm text-gray-400">
                {connectionState === 'connected' ? 'Conectado' : 'Desconectado'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Agent State */}
            {connectionState === 'connected' && (
              <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-gray-700">
                <div className={`w-2 h-2 rounded-full ${getStateColor()} animate-pulse`} />
                <span className="text-sm">{getStateText()}</span>
              </div>
            )}

            {/* Settings Button */}
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="btn btn-secondary p-2"
            >
              <Settings size={20} />
            </button>
          </div>
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-600 text-white px-4 py-2 text-center">
          {error}
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full">
        <div className="grid grid-cols-12 gap-6 h-[calc(100vh-180px)]">
          {/* Left Column - Chat */}
          <div className="col-span-6 flex flex-col gap-6">
            {/* Audio Visualizer */}
            <div className="panel h-32">
              <AudioVisualizer isActive={connectionState === 'connected'} />
            </div>

            {/* Chat Panel */}
            <div className="panel flex-1 overflow-hidden flex flex-col">
              <h2 className="panel-header">Conversa</h2>
              <ChatPanel />
            </div>
          </div>

          {/* Right Column - Tools & Memory */}
          <div className="col-span-6 flex flex-col gap-6">
            {/* Metrics Bar */}
            <MetricsBar />

            {/* Tool Panel */}
            <div className="panel flex-1 overflow-hidden">
              <h2 className="panel-header">Ferramentas</h2>
              <ToolPanel />
            </div>

            {/* Memory Panel */}
            <div className="panel flex-1 overflow-hidden">
              <h2 className="panel-header">Memoria</h2>
              <MemoryPanel />
            </div>

            {/* MCP Panel (collapsible) */}
            {showSettings && (
              <div className="panel">
                <h2 className="panel-header">MCP Servers</h2>
                <MCPPanel />
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Footer Controls */}
      <footer className="bg-gray-800 border-t border-gray-700 px-6 py-4">
        <div className="flex items-center justify-center gap-4 max-w-7xl mx-auto">
          {/* Mic Toggle */}
          <button
            onClick={handleMicToggle}
            disabled={connectionState !== 'connected'}
            className={`btn ${micMuted ? 'btn-danger' : 'btn-secondary'} p-3 rounded-full`}
            title={micMuted ? 'Ativar microfone' : 'Desativar microfone'}
          >
            {micMuted ? <MicOff size={24} /> : <Mic size={24} />}
          </button>

          {/* Connect/Disconnect */}
          <button
            onClick={handleConnect}
            disabled={connectionState === 'connecting'}
            className={`btn ${
              connectionState === 'connected' ? 'btn-danger' : 'btn-success'
            } px-8 py-3 rounded-full text-lg`}
          >
            {connectionState === 'connecting' ? (
              <>
                <span className="animate-spin">...</span>
                Conectando
              </>
            ) : connectionState === 'connected' ? (
              <>
                <PhoneOff size={24} />
                Desconectar
              </>
            ) : (
              <>
                <Phone size={24} />
                Conectar
              </>
            )}
          </button>

          {/* Speaker Toggle */}
          <button
            onClick={handleSpeakerToggle}
            disabled={connectionState !== 'connected'}
            className={`btn ${speakerMuted ? 'btn-danger' : 'btn-secondary'} p-3 rounded-full`}
            title={speakerMuted ? 'Ativar alto-falante' : 'Desativar alto-falante'}
          >
            {speakerMuted ? <VolumeX size={24} /> : <Volume2 size={24} />}
          </button>
        </div>

        {/* Session ID */}
        {sessionId && (
          <div className="text-center mt-2">
            <span className="text-xs text-gray-500">
              Sessao: {sessionId.slice(0, 8)}...
            </span>
          </div>
        )}
      </footer>

      {/* Permission Dialog */}
      {permissionRequest && <PermissionDialog request={permissionRequest} />}
    </div>
  );
}
