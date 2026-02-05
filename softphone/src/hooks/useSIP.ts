import { useState, useRef, useCallback, useEffect } from 'react'
import {
  UserAgent,
  Registerer,
  Inviter,
  SessionState,
  RegistererState,
} from 'sip.js'

export type CallState = 'idle' | 'calling' | 'ringing' | 'connected' | 'ended'
export type RegisterState = 'unregistered' | 'registering' | 'registered' | 'error'

export interface SIPConfig {
  server: string
  username: string
  password: string
  displayName: string
}

export const DEFAULT_SIP_CONFIG: SIPConfig = {
  server: import.meta.env.VITE_SIP_SERVER || 'ws://localhost:8188/ws',
  username: import.meta.env.VITE_SIP_USER || '1004',
  password: import.meta.env.VITE_SIP_PASS || 'xe9JDXRiUeK2848Uvoz1',
  displayName: import.meta.env.VITE_SIP_DISPLAY || 'Ramal 1004',
}

export function useSIP() {
  const [config, setConfig] = useState<SIPConfig>(DEFAULT_SIP_CONFIG)
  const [registerState, setRegisterState] = useState<RegisterState>('unregistered')
  const [callState, setCallState] = useState<CallState>('idle')
  const [callerId, setCallerId] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [isMuted, setIsMuted] = useState(false)

  const userAgentRef = useRef<UserAgent | null>(null)
  const registererRef = useRef<Registerer | null>(null)
  const sessionRef = useRef<any>(null)
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null)

  const setAudioElement = useCallback((element: HTMLAudioElement | null) => {
    remoteAudioRef.current = element
  }, [])

  const addLog = useCallback((message: string) => {
    const timestamp = new Date().toLocaleTimeString('pt-BR')
    setLogs((prev) => [...prev.slice(-50), `[${timestamp}] ${message}`])
  }, [])

  const cleanupMedia = useCallback(() => {
    if (remoteAudioRef.current) {
      const stream = remoteAudioRef.current.srcObject as MediaStream | null
      if (stream) {
        stream.getTracks().forEach((track) => track.stop())
        remoteAudioRef.current.srcObject = null
      }
    }
  }, [])

  const setupRemoteMedia = useCallback(
    (session: any) => {
      cleanupMedia()
      const remoteStream = new MediaStream()

      session.sessionDescriptionHandler?.peerConnection
        ?.getReceivers()
        .forEach((receiver: RTCRtpReceiver) => {
          if (receiver.track) {
            remoteStream.addTrack(receiver.track)
          }
        })

      if (remoteAudioRef.current) {
        remoteAudioRef.current.srcObject = remoteStream
        remoteAudioRef.current
          .play()
          .catch((e) => addLog(`Erro ao reproduzir audio: ${e}`))
      }
    },
    [addLog, cleanupMedia]
  )

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

  const register = useCallback(async () => {
    if (userAgentRef.current) {
      await unregister()
    }

    try {
      setRegisterState('registering')
      addLog('Conectando ao servidor...')

      const uri = UserAgent.makeURI(
        `sip:${config.username}@${new URL(config.server).host.split(':')[0]}`
      )
      if (!uri) throw new Error('URI invalida')

      const userAgent = new UserAgent({
        uri,
        transportOptions: { server: config.server },
        authorizationUsername: config.username,
        authorizationPassword: config.password,
        displayName: config.displayName,
        sessionDescriptionHandlerFactoryOptions: {
          peerConnectionConfiguration: {
            iceServers: [
              {
                urls:
                  import.meta.env.VITE_STUN_URL || 'stun:stun.l.google.com:19302',
              },
              ...(import.meta.env.VITE_TURN_URL
                ? [
                    {
                      urls: import.meta.env.VITE_TURN_URL,
                      username: import.meta.env.VITE_TURN_USER || '',
                      credential: import.meta.env.VITE_TURN_PASS || '',
                    },
                  ]
                : []),
            ],
          },
        },
        delegate: {
          onInvite: (invitation) => {
            addLog(
              `Chamada recebida de: ${invitation.remoteIdentity.displayName || invitation.remoteIdentity.uri.user}`
            )
            setCallerId(
              invitation.remoteIdentity.displayName ||
                invitation.remoteIdentity.uri.user ||
                'Desconhecido'
            )
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
                  cleanupMedia()
                  addLog('Chamada encerrada')
                  break
              }
            })
          },
        },
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
  }, [config, addLog, setupRemoteMedia, unregister, cleanupMedia])

  const makeCall = useCallback(
    async (dialNumber: string) => {
      if (!userAgentRef.current || !dialNumber) return

      try {
        addLog(`Ligando para ${dialNumber}...`)
        setCallState('calling')

        const target = UserAgent.makeURI(
          `sip:${dialNumber}@${new URL(config.server).host.split(':')[0]}`
        )
        if (!target) throw new Error('Numero invalido')

        const inviter = new Inviter(userAgentRef.current, target, {
          sessionDescriptionHandlerOptions: {
            constraints: { audio: true, video: false },
          },
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
              cleanupMedia()
              addLog('Chamada encerrada')
              break
          }
        })

        await inviter.invite()
      } catch (error) {
        setCallState('idle')
        addLog(`Erro na chamada: ${error}`)
      }
    },
    [config.server, addLog, setupRemoteMedia, cleanupMedia]
  )

  const answerCall = useCallback(async () => {
    if (!sessionRef.current) return

    try {
      addLog('Atendendo chamada...')
      await sessionRef.current.accept({
        sessionDescriptionHandlerOptions: {
          constraints: { audio: true, video: false },
        },
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

  const sendDTMF = useCallback(
    (digit: string) => {
      if (sessionRef.current?.state === SessionState.Established) {
        sessionRef.current.sessionDescriptionHandler?.sendDtmf(digit)
        addLog(`DTMF: ${digit}`)
      }
    },
    [addLog]
  )

  const toggleMute = useCallback(() => {
    if (!sessionRef.current?.sessionDescriptionHandler?.peerConnection) {
      return
    }

    const pc = sessionRef.current.sessionDescriptionHandler
      .peerConnection as RTCPeerConnection
    const senders = pc.getSenders()

    senders.forEach((sender: RTCRtpSender) => {
      if (sender.track && sender.track.kind === 'audio') {
        sender.track.enabled = isMuted
      }
    })

    setIsMuted(!isMuted)
    addLog(isMuted ? 'Microfone ativado' : 'Microfone desativado')
  }, [isMuted, addLog])

  // Reset mute quando chamada termina
  useEffect(() => {
    if (callState === 'idle') {
      setIsMuted(false)
    }
  }, [callState])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      unregister()
    }
  }, [unregister])

  return {
    // Estado
    config,
    setConfig,
    registerState,
    callState,
    callerId,
    logs,
    isMuted,

    // Ações
    register,
    unregister,
    makeCall,
    answerCall,
    hangup,
    sendDTMF,
    toggleMute,
    setAudioElement,
    addLog,
  }
}
