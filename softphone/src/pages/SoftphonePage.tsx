import { useState, useRef, useEffect } from 'react'
import { Phone, PhoneOff, Mic, MicOff, Trash2, PhoneIncoming, ChevronDown, ChevronUp, Settings, FileText, Wifi, WifiOff } from 'lucide-react'
import { useSIP } from '../hooks/useSIP'

const DIALPAD = [
  { digit: '1', letters: '' },
  { digit: '2', letters: 'ABC' },
  { digit: '3', letters: 'DEF' },
  { digit: '4', letters: 'GHI' },
  { digit: '5', letters: 'JKL' },
  { digit: '6', letters: 'MNO' },
  { digit: '7', letters: 'PQRS' },
  { digit: '8', letters: 'TUV' },
  { digit: '9', letters: 'WXYZ' },
  { digit: '*', letters: '' },
  { digit: '0', letters: '+' },
  { digit: '#', letters: '' },
]

export function SoftphonePage() {
  const {
    config,
    setConfig,
    registerState,
    callState,
    callerId,
    logs,
    isMuted,
    register,
    unregister,
    makeCall,
    answerCall,
    hangup,
    sendDTMF,
    toggleMute,
    setAudioElement,
  } = useSIP()

  const [dialNumber, setDialNumber] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)

  useEffect(() => {
    if (audioRef.current) {
      setAudioElement(audioRef.current)
    }
  }, [setAudioElement])

  const handleDial = (digit: string) => {
    sendDTMF(digit)
    setDialNumber((prev) => prev + digit)
  }

  const handleCall = () => {
    if (dialNumber) {
      makeCall(dialNumber)
    }
  }

  const handleBackspace = () => {
    setDialNumber((prev) => prev.slice(0, -1))
  }

  const getCallStateText = () => {
    switch (callState) {
      case 'calling':
        return 'Chamando...'
      case 'ringing':
        return 'Tocando...'
      case 'connected':
        return 'Em chamada'
      default:
        return null
    }
  }

  return (
    <div className="page softphone-page-v2">
      {/* Smartphone Frame */}
      <div className="smartphone-container">
        <div className="smartphone-frame">
          {/* Status Bar */}
          <div className="phone-status-bar">
            <span className="phone-time">
              {new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
            </span>
            <div className="phone-status-icons">
              {registerState === 'registered' ? (
                <Wifi size={14} className="status-connected" />
              ) : (
                <WifiOff size={14} className="status-disconnected" />
              )}
            </div>
          </div>

          {/* Notch */}
          <div className="phone-notch"></div>

          {/* Phone Content */}
          <div className="phone-content">
            {/* Incoming Call Overlay */}
            {callState === 'ringing' && (
              <div className="incoming-call-overlay">
                <div className="incoming-avatar">
                  <PhoneIncoming size={40} className="pulse" />
                </div>
                <p className="incoming-label">Chamada recebida</p>
                <p className="incoming-number">{callerId}</p>
                <div className="incoming-actions">
                  <button onClick={hangup} className="call-btn call-btn-reject">
                    <PhoneOff size={24} />
                  </button>
                  <button onClick={answerCall} className="call-btn call-btn-answer">
                    <Phone size={24} />
                  </button>
                </div>
              </div>
            )}

            {/* Connection Banner */}
            {registerState !== 'registered' && (
              <div className="connection-banner">
                <button
                  onClick={register}
                  disabled={registerState === 'registering'}
                  className="connect-btn"
                >
                  {registerState === 'registering' ? (
                    <>
                      <Wifi size={18} className="spin" />
                      <span>Conectando...</span>
                    </>
                  ) : (
                    <>
                      <Wifi size={18} />
                      <span>Conectar ao Servidor SIP</span>
                    </>
                  )}
                </button>
              </div>
            )}

            {/* Display */}
            <div className="phone-display">
              <input
                type="text"
                value={dialNumber}
                onChange={(e) => setDialNumber(e.target.value)}
                placeholder={registerState === 'registered' ? 'Digite o numero' : 'Desconectado'}
                className="dial-display"
                disabled={registerState !== 'registered'}
              />
              {getCallStateText() && (
                <span className="call-state-indicator">{getCallStateText()}</span>
              )}
            </div>

            {/* Dialpad */}
            <div className="phone-dialpad">
              {DIALPAD.map(({ digit, letters }) => (
                <button
                  key={digit}
                  onClick={() => handleDial(digit)}
                  className="dialpad-key"
                  disabled={registerState !== 'registered'}
                >
                  <span className="key-digit">{digit}</span>
                  {letters && <span className="key-letters">{letters}</span>}
                </button>
              ))}
            </div>

            {/* Call Actions */}
            <div className="phone-actions">
              {callState === 'idle' ? (
                <>
                  <button
                    onClick={handleBackspace}
                    className="action-btn action-secondary"
                    disabled={!dialNumber}
                  >
                    <Trash2 size={20} />
                  </button>
                  <button
                    onClick={handleCall}
                    disabled={!dialNumber || registerState !== 'registered'}
                    className="action-btn action-call"
                  >
                    <Phone size={24} />
                  </button>
                  <button
                    onClick={toggleMute}
                    className="action-btn action-secondary"
                    disabled
                  >
                    <Mic size={20} />
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={toggleMute}
                    className={`action-btn ${isMuted ? 'action-muted' : 'action-secondary'}`}
                  >
                    {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
                  </button>
                  <button onClick={hangup} className="action-btn action-hangup">
                    <PhoneOff size={24} />
                  </button>
                  <button className="action-btn action-secondary" disabled>
                    <Settings size={20} />
                  </button>
                </>
              )}
            </div>

            {/* Connection Status */}
            <div className="phone-connection-status">
              <span className={`connection-dot ${registerState}`}></span>
              <span className="connection-text">
                {registerState === 'registered'
                  ? config.username
                  : registerState === 'registering'
                    ? 'Conectando...'
                    : 'Desconectado'}
              </span>
              <button
                onClick={registerState === 'registered' ? unregister : register}
                className="connection-toggle"
              >
                {registerState === 'registered' ? 'Desconectar' : 'Conectar'}
              </button>
            </div>
          </div>

          {/* Home Indicator */}
          <div className="phone-home-indicator"></div>
        </div>
      </div>

      {/* Advanced Settings (Accordions) */}
      <div className="advanced-settings">
        {/* SIP Configuration Accordion */}
        <div className="accordion">
          <button
            className={`accordion-header ${showAdvanced ? 'open' : ''}`}
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            <div className="accordion-title">
              <Settings size={18} />
              <span>Configuracoes Avancadas</span>
            </div>
            {showAdvanced ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          {showAdvanced && (
            <div className="accordion-content">
              <div className="form-group">
                <label>Servidor WebSocket</label>
                <input
                  type="text"
                  value={config.server}
                  onChange={(e) => setConfig((prev) => ({ ...prev, server: e.target.value }))}
                  disabled={registerState === 'registered'}
                  placeholder="wss://servidor:porta/ws"
                />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Ramal</label>
                  <input
                    type="text"
                    value={config.username}
                    onChange={(e) => setConfig((prev) => ({ ...prev, username: e.target.value }))}
                    disabled={registerState === 'registered'}
                  />
                </div>
                <div className="form-group">
                  <label>Senha</label>
                  <input
                    type="password"
                    value={config.password}
                    onChange={(e) => setConfig((prev) => ({ ...prev, password: e.target.value }))}
                    disabled={registerState === 'registered'}
                  />
                </div>
              </div>
              <div className="form-group">
                <label>Nome de Exibicao</label>
                <input
                  type="text"
                  value={config.displayName}
                  onChange={(e) => setConfig((prev) => ({ ...prev, displayName: e.target.value }))}
                  disabled={registerState === 'registered'}
                  placeholder="Seu nome"
                />
              </div>
            </div>
          )}
        </div>

        {/* Logs Accordion */}
        <div className="accordion">
          <button
            className={`accordion-header ${showLogs ? 'open' : ''}`}
            onClick={() => setShowLogs(!showLogs)}
          >
            <div className="accordion-title">
              <FileText size={18} />
              <span>Logs do Sistema</span>
              {logs.length > 0 && <span className="log-count">{logs.length}</span>}
            </div>
            {showLogs ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          {showLogs && (
            <div className="accordion-content">
              <div className="logs-container">
                {logs.length === 0 ? (
                  <p className="logs-empty">Nenhum evento registrado</p>
                ) : (
                  logs.map((log, i) => (
                    <div key={i} className="log-entry">
                      {log}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Audio element (hidden) */}
      <audio ref={audioRef} autoPlay />
    </div>
  )
}
