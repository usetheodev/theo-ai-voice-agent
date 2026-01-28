import { useCallback, useEffect, useRef, useState } from 'react';
import { decode, encode } from '@msgpack/msgpack';
import { useAgentStore, AgentEvent } from './useAgentState';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error';

interface SignalingMessage {
  type: string;
  data: Record<string, unknown>;
  session_id?: string;
}

interface UseWebRTCOptions {
  signalingUrl?: string;
  onEvent?: (event: AgentEvent) => void;
}

export function useWebRTC(options: UseWebRTCOptions = {}) {
  const { signalingUrl = `ws://${window.location.host}/ws/signaling` } = options;

  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null);

  const { handleEvent } = useAgentStore();

  // Process DataChannel message
  const processDataChannelMessage = useCallback((data: ArrayBuffer | string) => {
    try {
      let eventData: AgentEvent;

      if (typeof data === 'string') {
        eventData = JSON.parse(data);
      } else {
        eventData = decode(new Uint8Array(data)) as AgentEvent;
      }

      handleEvent(eventData);
      options.onEvent?.(eventData);
    } catch (err) {
      console.error('Error parsing DataChannel message:', err);
    }
  }, [handleEvent, options]);

  // Send message via DataChannel
  const sendEvent = useCallback((type: string, data: Record<string, unknown> = {}) => {
    if (dataChannelRef.current?.readyState === 'open') {
      const message = encode({ type, data, timestamp: Date.now() });
      dataChannelRef.current.send(message);
    }
  }, []);

  // Connect to WebRTC
  const connect = useCallback(async () => {
    if (connectionState !== 'disconnected') {
      console.warn('Already connecting or connected');
      return;
    }

    setConnectionState('connecting');
    setError(null);

    try {
      // Get user media
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      localStreamRef.current = stream;

      // Create WebSocket for signaling
      const ws = new WebSocket(signalingUrl);
      wsRef.current = ws;

      ws.onmessage = async (event) => {
        const message: SignalingMessage = JSON.parse(event.data);

        switch (message.type) {
          case 'session_created':
            setSessionId(message.data.session_id as string);
            await startPeerConnection(message.data.ice_servers as RTCIceServer[]);
            break;

          case 'offer_response':
            if (pcRef.current) {
              await pcRef.current.setRemoteDescription(
                new RTCSessionDescription(message.data as RTCSessionDescriptionInit)
              );
            }
            break;

          case 'ice_candidate':
            if (pcRef.current && message.data.candidate) {
              await pcRef.current.addIceCandidate(
                new RTCIceCandidate(message.data as RTCIceCandidateInit)
              );
            }
            break;

          case 'error':
            setError(message.data.error as string);
            setConnectionState('error');
            break;
        }
      };

      ws.onerror = () => {
        setError('WebSocket connection failed');
        setConnectionState('error');
      };

      ws.onclose = () => {
        if (connectionState === 'connected') {
          setConnectionState('disconnected');
        }
      };

    } catch (err) {
      console.error('Connection error:', err);
      setError(err instanceof Error ? err.message : 'Connection failed');
      setConnectionState('error');
    }
  }, [connectionState, signalingUrl]);

  // Start peer connection
  const startPeerConnection = useCallback(async (iceServers: RTCIceServer[]) => {
    const pc = new RTCPeerConnection({ iceServers });
    pcRef.current = pc;

    // Add local audio track
    if (localStreamRef.current) {
      localStreamRef.current.getAudioTracks().forEach(track => {
        pc.addTrack(track, localStreamRef.current!);
      });
    }

    // Create data channel
    const dataChannel = pc.createDataChannel('events', { ordered: true });
    dataChannelRef.current = dataChannel;

    dataChannel.onopen = () => {
      console.log('DataChannel open');
    };

    dataChannel.onmessage = (event) => {
      processDataChannelMessage(event.data);
    };

    // Handle remote track
    pc.ontrack = (event) => {
      console.log('Remote track received:', event.track.kind);
      if (event.track.kind === 'audio') {
        if (!remoteAudioRef.current) {
          remoteAudioRef.current = new Audio();
          remoteAudioRef.current.autoplay = true;
        }
        remoteAudioRef.current.srcObject = event.streams[0];
      }
    };

    // Handle ICE candidates
    pc.onicecandidate = (event) => {
      if (event.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'ice_candidate',
          data: event.candidate.toJSON(),
        }));
      }
    };

    // Handle connection state changes
    pc.onconnectionstatechange = () => {
      console.log('Connection state:', pc.connectionState);
      switch (pc.connectionState) {
        case 'connected':
          setConnectionState('connected');
          break;
        case 'disconnected':
        case 'failed':
          setConnectionState('disconnected');
          break;
      }
    };

    // Create and send offer
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'offer',
        data: { type: offer.type, sdp: offer.sdp },
      }));
    }
  }, [processDataChannelMessage]);

  // Disconnect
  const disconnect = useCallback(() => {
    // Close data channel
    if (dataChannelRef.current) {
      dataChannelRef.current.close();
      dataChannelRef.current = null;
    }

    // Close peer connection
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    // Close WebSocket
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    // Stop local stream
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => track.stop());
      localStreamRef.current = null;
    }

    // Stop remote audio
    if (remoteAudioRef.current) {
      remoteAudioRef.current.srcObject = null;
      remoteAudioRef.current = null;
    }

    setConnectionState('disconnected');
    setSessionId(null);
  }, []);

  // Mute/unmute microphone
  const setMicMuted = useCallback((muted: boolean) => {
    if (localStreamRef.current) {
      localStreamRef.current.getAudioTracks().forEach(track => {
        track.enabled = !muted;
      });
    }
  }, []);

  // Mute/unmute speaker
  const setSpeakerMuted = useCallback((muted: boolean) => {
    if (remoteAudioRef.current) {
      remoteAudioRef.current.muted = muted;
    }
  }, []);

  // Get audio levels
  const getInputLevel = useCallback((): number => {
    // Would need AudioContext with analyser for real implementation
    return 0;
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    connectionState,
    sessionId,
    error,
    connect,
    disconnect,
    sendEvent,
    setMicMuted,
    setSpeakerMuted,
    getInputLevel,
    localStream: localStreamRef.current,
  };
}
