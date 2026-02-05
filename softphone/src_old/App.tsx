import { useState, useRef, useCallback, useEffect } from 'react'
import {
  UserAgent,
  Registerer,
  Inviter,
  SessionState,
  RegistererState,
  Web
} from 'sip.js'

type CallState = 'idle' | 'calling' | 'ringing' | 'connected' | 'ended'
type RegisterState = 'unregistered' | 'registering' | 'registered' | 'error'

interface Config {
  server: string
  username: string
  password: string
  displayName: string
}

const DEFAULT_CONFIG: Config = {
  // Use ws:// para dev local (sem TLS), wss:// para produção
  server: import.meta.env.VITE_SIP_SERVER || 'ws://localhost:8188/ws',
  username: import.meta.env.VITE_SIP_USER || '1004',
  password: import.meta.env.VITE_SIP_PASS || 'xe9JDXRiUeK2848Uvoz1',
  displayName: import.meta.env.VITE_SIP_DISPLAY || 'Ramal 1004'
}

function App() {
  const [config, setConfig] = useState<Config>(DEFAULT_CONFIG)
  const [registerState, setRegisterState] = useState<RegisterState>('unregistered')
  const [callState, setCallState] = useState<CallState>('idle')
  const [dialNumber, setDialNumber] = useState('')
  const [callerId, setCallerId] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [isMuted, setIsMuted] = useState(false)

  const userAgentRef = useRef<UserAgent | null>(null)
  const registererRef = useRef<Registerer | null>(null)
  const sessionRef = useRef<any>(null)
  const remoteAudioRef = useRef<HTMLAudioElement>(null)

  const addLog = useCallback((message: string) => {
    const timestamp = new Date().toLocaleTimeString('pt-BR')
    setLogs(prev => [...prev.slice(-50), `[${timestamp}] ${message}`])
  }, [])

  const cleanupMedia = useCallback(() => {
    if (remoteAudioRef.current) {
      const stream = remoteAudioRef.current.srcObject as MediaStream | null
      if (stream) {
        stream.getTracks().forEach(track => track.stop())
        remoteAudioRef.current.srcObject = null
      }
    }
  }, [])

  const setupRemoteMedia = useCallback((session: any) => {
    // Limpa stream anterior, se houver
    cleanupMedia()

    const remoteStream = new MediaStream()

    session.sessionDescriptionHandler?.peerConnection?.getReceivers().forEach((receiver: RTCRtpReceiver) => {
      if (receiver.track) {
        remoteStream.addTrack(receiver.track)
      }
    })

    if (remoteAudioRef.current) {
      remoteAudioRef.current.srcObject = remoteStream
      remoteAudioRef.current.play().catch(e => addLog(`Erro ao reproduzir áudio: ${e}`))
    }
  }, [addLog, cleanupMedia])

  const register = useCallback(async () => {
    if (userAgentRef.current) {
      await unregister()
    }

    try {
      setRegisterState('registering')
      addLog('Conectando ao servidor...')

      const uri = UserAgent.makeURI(`sip:${config.username}@${new URL(config.server).host.split(':')[0]}`)
      if (!uri) throw new Error('URI inválida')

      const userAgent = new UserAgent({
        uri,
        transportOptions: {
          server: config.server
        },
        authorizationUsername: config.username,
        authorizationPassword: config.password,
        displayName: config.displayName,
        sessionDescriptionHandlerFactoryOptions: {
          peerConnectionConfiguration: {
            iceServers: [
              { urls: import.meta.env.VITE_STUN_URL || 'stun:stun.l.google.com:19302' },
              ...(import.meta.env.VITE_TURN_URL ? [{
                urls: import.meta.env.VITE_TURN_URL,
                username: import.meta.env.VITE_TURN_USER || '',
                credential: import.meta.env.VITE_TURN_PASS || ''
              }] : [])
            ]
          }
        },
        delegate: {
          onInvite: (invitation) => {
            addLog(`Chamada recebida de: ${invitation.remoteIdentity.displayName || invitation.remoteIdentity.uri.user}`)
            setCallerId(invitation.remoteIdentity.displayName || invitation.remoteIdentity.uri.user || 'Desconhecido')
            setCallState('ringing')
            sessionRef.current = invitation

            invitation.stateChange.addListener((state) => {
              switch (state) {
                case SessionState.Establishing:
                  setCallState('calling')
                  break
                case SessionState.Established:
                  setCallState('connected')
                  setupRemoteMedia(invitation)
                  addLog('Chamada conectada')
                  break
                case SessionState.Terminated:
                  setCallState('idle')
                  setCallerId('')
                  sessionRef.current = null
                  // Limpa recursos de mídia
                  if (remoteAudioRef.current?.srcObject) {
                    const stream = remoteAudioRef.current.srcObject as MediaStream
                    stream.getTracks().forEach(track => track.stop())
                    remoteAudioRef.current.srcObject = null
                  }
                  addLog('Chamada encerrada')
                  break
              }
            })
          }
        }
      })

      await userAgent.start()
      userAgentRef.current = userAgent

      const registerer = new Registerer(userAgent)
      registererRef.current = registerer

      registerer.stateChange.addListener((state) => {
        switch (state) {
          case RegistererState.Registered:
            setRegisterState('registered')
            addLog('Registrado com sucesso!')
            break
          case RegistererState.Unregistered:
            setRegisterState('unregistered')
            addLog('Desregistrado')
            break
        }
      })

      await registerer.register()
    } catch (error) {
      setRegisterState('error')
      addLog(`Erro: ${error}`)
    }
  }, [config, addLog, setupRemoteMedia])

  const unregister = useCallback(async () => {
    try {
      if (registererRef.current) {
        await registererRef.current.unregister()
        registererRef.current = null
      }
      if (userAgentRef.current) {
        await userAgentRef.current.stop()
        userAgentRef.current = null
      }
      setRegisterState('unregistered')
    } catch (error) {
      addLog(`Erro ao desregistrar: ${error}`)
    }
  }, [addLog])

  const makeCall = useCallback(async () => {
    if (!userAgentRef.current || !dialNumber) return

    try {
      addLog(`Ligando para ${dialNumber}...`)
      setCallState('calling')

      const target = UserAgent.makeURI(`sip:${dialNumber}@${new URL(config.server).host.split(':')[0]}`)
      if (!target) throw new Error('Número inválido')

      const inviter = new Inviter(userAgentRef.current, target, {
        sessionDescriptionHandlerOptions: {
          constraints: { audio: true, video: false }
        }
      })

      sessionRef.current = inviter

      inviter.stateChange.addListener((state) => {
        switch (state) {
          case SessionState.Establishing:
            setCallState('calling')
            addLog('Chamando...')
            break
          case SessionState.Established:
            setCallState('connected')
            setupRemoteMedia(inviter)
            addLog('Chamada conectada')
            break
          case SessionState.Terminated:
            setCallState('idle')
            sessionRef.current = null
            // Limpa recursos de mídia
            if (remoteAudioRef.current?.srcObject) {
              const stream = remoteAudioRef.current.srcObject as MediaStream
              stream.getTracks().forEach(track => track.stop())
              remoteAudioRef.current.srcObject = null
            }
            addLog('Chamada encerrada')
            break
        }
      })

      await inviter.invite()
    } catch (error) {
      setCallState('idle')
      addLog(`Erro na chamada: ${error}`)
    }
  }, [dialNumber, config.server, addLog, setupRemoteMedia])

  const answerCall = useCallback(async () => {
    if (!sessionRef.current) return

    try {
      addLog('Atendendo chamada...')
      await sessionRef.current.accept({
        sessionDescriptionHandlerOptions: {
          constraints: { audio: true, video: false }
        }
      })
    } catch (error) {
      addLog(`Erro ao atender: ${error}`)
    }
  }, [addLog])

  const hangup = useCallback(async () => {
    if (!sessionRef.current) return

    try {
      addLog('Encerrando chamada...')
      if (sessionRef.current.state === SessionState.Established) {
        sessionRef.current.bye()
      } else {
        sessionRef.current.cancel?.() || sessionRef.current.reject?.()
      }
    } catch (error) {
      addLog(`Erro ao encerrar: ${error}`)
    }
  }, [addLog])

  const sendDTMF = useCallback((digit: string) => {
    if (sessionRef.current?.state === SessionState.Established) {
      sessionRef.current.sessionDescriptionHandler?.sendDtmf(digit)
      addLog(`DTMF: ${digit}`)
    }
    setDialNumber(prev => prev + digit)
  }, [addLog])

  const toggleMute = useCallback(() => {
    if (!sessionRef.current?.sessionDescriptionHandler?.peerConnection) {
      return
    }

    const pc = sessionRef.current.sessionDescriptionHandler.peerConnection as RTCPeerConnection
    const senders = pc.getSenders()

    senders.forEach((sender: RTCRtpSender) => {
      if (sender.track && sender.track.kind === 'audio') {
        sender.track.enabled = isMuted  // Se está muted, habilita; se não, desabilita
      }
    })

    setIsMuted(!isMuted)
    addLog(isMuted ? '🎤 Microfone ativado' : '🔇 Microfone desativado')
  }, [isMuted, addLog])

  useEffect(() => {
    return () => {
      unregister()
    }
  }, [unregister])

  // Reset mute quando chamada termina
  useEffect(() => {
    if (callState === 'idle') {
      setIsMuted(false)
    }
  }, [callState])

  const dialpad = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#']

  return (
    <div className="app">
      <h1>SoftPhone PABX</h1>

      {/* Configuração */}
      <div className="config-section">
        <h2>Configuração</h2>
        <div className="form-group">
          <label>Servidor WebSocket:</label>
          <input
            type="text"
            value={config.server}
            onChange={(e) => setConfig(prev => ({ ...prev, server: e.target.value }))}
            disabled={registerState === 'registered'}
          />
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>Ramal:</label>
            <input
              type="text"
              value={config.username}
              onChange={(e) => setConfig(prev => ({ ...prev, username: e.target.value }))}
              disabled={registerState === 'registered'}
            />
          </div>
          <div className="form-group">
            <label>Senha:</label>
            <input
              type="password"
              value={config.password}
              onChange={(e) => setConfig(prev => ({ ...prev, password: e.target.value }))}
              disabled={registerState === 'registered'}
            />
          </div>
        </div>
        <button
          onClick={registerState === 'registered' ? unregister : register}
          className={registerState === 'registered' ? 'btn-danger' : 'btn-primary'}
        >
          {registerState === 'registering' ? 'Conectando...' :
           registerState === 'registered' ? 'Desconectar' : 'Conectar'}
        </button>
        <span className={`status status-${registerState}`}>
          {registerState === 'registered' ? 'Conectado' :
           registerState === 'registering' ? 'Conectando...' :
           registerState === 'error' ? 'Erro' : 'Desconectado'}
        </span>
      </div>

      {/* Discador */}
      <div className="dialer-section">
        <h2>Discador</h2>

        {callState === 'ringing' && (
          <div className="incoming-call">
            <p>Chamada de: <strong>{callerId}</strong></p>
            <button onClick={answerCall} className="btn-success">Atender</button>
            <button onClick={hangup} className="btn-danger">Rejeitar</button>
          </div>
        )}

        <input
          type="text"
          value={dialNumber}
          onChange={(e) => setDialNumber(e.target.value)}
          placeholder="Digite o ramal..."
          className="dial-input"
        />

        <div className="dialpad">
          {dialpad.map(digit => (
            <button key={digit} onClick={() => sendDTMF(digit)} className="dialpad-btn">
              {digit}
            </button>
          ))}
        </div>

        <div className="call-actions">
          {callState === 'idle' ? (
            <button
              onClick={makeCall}
              disabled={!dialNumber || registerState !== 'registered'}
              className="btn-success btn-large"
            >
              Ligar
            </button>
          ) : (
            <>
              <button onClick={hangup} className="btn-danger btn-large">
                {callState === 'connected' ? 'Desligar' : 'Cancelar'}
              </button>
              {callState === 'connected' && (
                <button
                  onClick={toggleMute}
                  className={isMuted ? 'btn-warning' : 'btn-secondary'}
                >
                  {isMuted ? '🔇 Mudo' : '🎤 Mute'}
                </button>
              )}
            </>
          )}
          <button onClick={() => setDialNumber('')} className="btn-secondary">
            Limpar
          </button>
        </div>

        <p className="call-status">
          Status: {callState === 'idle' ? 'Pronto' :
                   callState === 'calling' ? 'Chamando...' :
                   callState === 'ringing' ? 'Tocando...' :
                   callState === 'connected' ? 'Em chamada' : 'Encerrado'}
        </p>
      </div>

      {/* Logs */}
      <div className="logs-section">
        <h2>Logs</h2>
        <div className="logs">
          {logs.map((log, i) => (
            <div key={i} className="log-entry">{log}</div>
          ))}
        </div>
      </div>

      {/* Áudio remoto */}
      <audio ref={remoteAudioRef} autoPlay />
    </div>
  )
}

export default App