# ADR-006: RTP Integration Strategy

**Status:** Accepted  
**Date:** January 2026  
**Deciders:** Platform Architecture Team  
**Technical Story:** Define how the inference server integrates with telephony infrastructure via RTP

---

## Context

Real-time Transport Protocol (RTP) is the standard for voice media in telephony systems. Our inference server must integrate with existing PBX systems, SIP trunks, and contact center infrastructure.

### Integration Requirements

1. **Receive RTP audio**: From PBX/SBC
2. **Send RTP audio**: TTS output back to caller
3. **Handle signaling**: Coordinate with SIP for call setup/teardown
4. **Support standard codecs**: G.711, G.722, Opus
5. **Enable NAT traversal**: Work across network boundaries

### Stakeholders

- **Contact Center Teams**: Need seamless integration with existing infrastructure
- **Network Engineers**: Need predictable port usage and firewall rules
- **DevOps**: Need manageable deployment topology

---

## Decision Drivers

1. **Compatibility**: Must work with existing PBX systems
2. **Simplicity**: Minimize network complexity
3. **Scalability**: Support hundreds of concurrent sessions
4. **Reliability**: No dropped calls due to RTP issues

---

## Considered Options

### Option 1: Direct RTP

Inference server acts as direct RTP endpoint.

```
┌─────────┐         RTP/UDP          ┌──────────────────┐
│   PBX   │ ◀────────────────────▶  │ Inference Server │
│  (SBC)  │                          │   (RTP Endpoint) │
└─────────┘                          └──────────────────┘
     │                                        │
     │          SIP Signaling                 │
     └────────────────────────────────────────┘
```

**Pros:**
- Lowest latency (no intermediate hops)
- Simplest architecture
- Direct control over media

**Cons:**
- NAT traversal complexity
- Port management (one port pair per call)
- Firewall rules for wide port ranges
- Harder to scale horizontally

### Option 2: RTP Proxy (rtpengine/RTPProxy)

Dedicated RTP proxy handles media, forwards to inference server.

```
┌─────────┐      RTP       ┌───────────┐    Internal    ┌──────────────────┐
│   PBX   │ ◀────────────▶ │ rtpengine │ ◀────────────▶ │ Inference Server │
│  (SBC)  │                │  (proxy)  │   Unix Socket  │                  │
└─────────┘                └───────────┘                └──────────────────┘
```

**Pros:**
- NAT traversal handled by proxy
- SRTP termination at edge
- Media recording/forking capability
- Easier horizontal scaling
- Inference server on internal network only

**Cons:**
- Additional component to manage
- Slight latency increase (~1-2ms)
- More complex deployment

### Option 3: WebRTC Gateway

Use WebRTC for media, gateway converts to/from RTP.

```
┌─────────┐      RTP       ┌───────────┐   WebRTC   ┌──────────────────┐
│   PBX   │ ◀────────────▶ │  Janus/   │ ◀────────▶ │ Inference Server │
│  (SBC)  │                │ Osproxy   │            │                  │
└─────────┘                └───────────┘            └──────────────────┘
```

**Pros:**
- Modern WebRTC stack
- Built-in DTLS-SRTP
- Good browser integration

**Cons:**
- Transcoding overhead
- Higher complexity
- Not standard in telephony

### Option 4: FreeSWITCH Media Server

Use FreeSWITCH as media server with mod_unimrcp or custom module.

```
┌─────────┐      RTP       ┌───────────────┐   Event Socket   ┌──────────────────┐
│   PBX   │ ◀────────────▶ │  FreeSWITCH   │ ◀──────────────▶ │ Inference Server │
│  (SBC)  │                │               │                  │                  │
└─────────┘                └───────────────┘                  └──────────────────┘
```

**Pros:**
- Full-featured media server
- Extensive codec support
- Built-in recording, conferencing
- Large community

**Cons:**
- Heavy (full PBX capabilities we don't need)
- Complex configuration
- Event Socket adds latency

---

## Decision

**Primary: Option 2 (RTP Proxy with rtpengine)**  
**Simple Deployments: Option 1 (Direct RTP)**

### Rationale

1. **RTP Proxy for production**
   - Handles NAT traversal automatically
   - SRTP termination at network edge
   - Inference server stays on internal network (security)
   - Proven at scale (used by Ooma, Twilio, many others)
   - Media forking for recording/monitoring

2. **Direct RTP for simple deployments**
   - Single-server deployments
   - Internal network only (no NAT)
   - Development/testing
   - Lowest latency when topology allows

3. **Rejected options:**
   - **WebRTC Gateway**: Unnecessary complexity for telephony use case
   - **FreeSWITCH**: Overkill, we don't need PBX features

---

## Implementation

### Direct RTP Mode

```typescript
interface DirectRTPConfig {
  // Network binding
  bindAddress: string;           // '0.0.0.0' for all interfaces
  portRangeStart: number;        // 10000
  portRangeEnd: number;          // 20000
  externalIP?: string;           // For NAT, advertise this IP in SDP
  
  // Security
  srtpEnabled: boolean;
  srtpCryptoSuites: string[];    // ['AES_CM_128_HMAC_SHA1_80']
  
  // Codecs (in preference order)
  codecs: ('PCMU' | 'PCMA' | 'G722' | 'opus')[];
}

class DirectRTPEndpoint {
  private sockets: Map<string, dgram.Socket> = new Map();
  private portAllocator: PortAllocator;
  
  async allocateSession(sessionId: string): Promise<RTPSession> {
    const port = await this.portAllocator.allocate();
    const socket = dgram.createSocket('udp4');
    
    socket.bind(port, this.config.bindAddress);
    
    this.sockets.set(sessionId, socket);
    
    return {
      localPort: port,
      localIP: this.config.externalIP || this.getLocalIP(),
      onPacket: (callback) => {
        socket.on('message', (msg, rinfo) => {
          callback(this.parseRTP(msg), rinfo);
        });
      },
      send: (packet, remoteIP, remotePort) => {
        socket.send(this.serializeRTP(packet), remotePort, remoteIP);
      },
    };
  }
}
```

### RTP Proxy Mode (rtpengine)

```typescript
interface RTPProxyConfig {
  // rtpengine connection
  controlSocket: string;         // '127.0.0.1:2223'
  protocol: 'ng';                // rtpengine NG protocol
  
  // Internal transport
  internalTransport: 'udp' | 'unix';
  internalEndpoint: string;      // '/var/run/inference.sock' or '127.0.0.1:30000'
}

class RTPProxyClient {
  private socket: dgram.Socket;
  
  async createOffer(
    sessionId: string,
    sdpOffer: string
  ): Promise<{ sdpAnswer: string; internalPort: number }> {
    const command = {
      command: 'offer',
      'call-id': sessionId,
      'from-tag': 'external',
      sdp: sdpOffer,
      direction: ['external', 'internal'],
      flags: ['trust-address'],
      'transport-protocol': 'RTP/AVP',
      'media-address': this.config.internalEndpoint,
    };
    
    const response = await this.sendCommand(command);
    
    return {
      sdpAnswer: response.sdp,
      internalPort: response['media-address'].port,
    };
  }
  
  async deleteSession(sessionId: string): Promise<void> {
    await this.sendCommand({
      command: 'delete',
      'call-id': sessionId,
    });
  }
}
```

### SIP Integration

```typescript
interface SIPConfig {
  // SIP server binding
  listenPort: number;            // 5060
  transports: ('udp' | 'tcp' | 'tls')[];
  tlsCert?: string;
  tlsKey?: string;
  
  // Authentication
  realm: string;
  users?: Map<string, string>;   // username -> password (optional)
}

class SIPHandler {
  private server: SIPServer;
  
  async handleInvite(request: SIPRequest): Promise<void> {
    const sessionId = generateSessionId();
    const sdpOffer = request.body;
    
    // Parse SDP to get codec preferences
    const offer = parseSDP(sdpOffer);
    const selectedCodec = this.selectCodec(offer.codecs);
    
    // Allocate RTP resources
    let rtpSession: RTPSession;
    if (this.useProxy) {
      const proxyResult = await this.rtpProxy.createOffer(sessionId, sdpOffer);
      rtpSession = await this.connectToProxy(proxyResult.internalPort);
    } else {
      rtpSession = await this.directRTP.allocateSession(sessionId);
    }
    
    // Generate SDP answer
    const sdpAnswer = this.generateSDP({
      ip: rtpSession.localIP,
      port: rtpSession.localPort,
      codec: selectedCodec,
    });
    
    // Send 200 OK
    await this.server.send200OK(request, sdpAnswer);
    
    // Start inference session
    await this.startInferenceSession(sessionId, rtpSession, selectedCodec);
  }
  
  async handleBye(request: SIPRequest): Promise<void> {
    const sessionId = request.headers['Call-ID'];
    
    await this.stopInferenceSession(sessionId);
    
    if (this.useProxy) {
      await this.rtpProxy.deleteSession(sessionId);
    } else {
      await this.directRTP.releaseSession(sessionId);
    }
    
    await this.server.send200OK(request);
  }
}
```

### Codec Implementation

```typescript
// G.711 μ-law decoder
function decodeUlaw(encoded: Uint8Array): Int16Array {
  const decoded = new Int16Array(encoded.length);
  
  for (let i = 0; i < encoded.length; i++) {
    let byte = encoded[i];
    byte = ~byte;
    
    const sign = byte & 0x80;
    const exponent = (byte >> 4) & 0x07;
    const mantissa = byte & 0x0F;
    
    let sample = (mantissa << 3) + 0x84;
    sample <<= exponent;
    sample -= 0x84;
    
    decoded[i] = sign ? -sample : sample;
  }
  
  return decoded;
}

// G.711 μ-law encoder
function encodeUlaw(samples: Int16Array): Uint8Array {
  const encoded = new Uint8Array(samples.length);
  
  for (let i = 0; i < samples.length; i++) {
    let sample = samples[i];
    const sign = sample < 0 ? 0x80 : 0;
    
    if (sign) sample = -sample;
    sample = Math.min(sample, 32635);
    sample += 0x84;
    
    let exponent = 7;
    for (let expMask = 0x4000; (sample & expMask) === 0 && exponent > 0; exponent--) {
      expMask >>= 1;
    }
    
    const mantissa = (sample >> (exponent + 3)) & 0x0F;
    encoded[i] = ~(sign | (exponent << 4) | mantissa);
  }
  
  return encoded;
}

// Codec factory
function getCodec(name: string): Codec {
  switch (name) {
    case 'PCMU': return { decode: decodeUlaw, encode: encodeUlaw, sampleRate: 8000 };
    case 'PCMA': return { decode: decodeAlaw, encode: encodeAlaw, sampleRate: 8000 };
    case 'G722': return { decode: decodeG722, encode: encodeG722, sampleRate: 16000 };
    case 'opus': return new OpusCodec();
    default: throw new Error(`Unknown codec: ${name}`);
  }
}
```

### rtpengine Deployment

```yaml
# docker-compose.yml for rtpengine
version: '3.8'
services:
  rtpengine:
    image: drachtio/rtpengine:latest
    network_mode: host
    environment:
      - CLOUD=1
    volumes:
      - ./rtpengine.conf:/etc/rtpengine/rtpengine.conf
    command: >
      --interface=external/${PUBLIC_IP}
      --interface=internal/127.0.0.1
      --listen-ng=127.0.0.1:2223
      --port-min=30000
      --port-max=40000
      --log-level=6
```

```ini
# rtpengine.conf
[rtpengine]
table = 0
no-fallback = false
timeout = 60
silent-timeout = 3600
tos = 184
delete-delay = 30
```

---

## Consequences

### Positive

- **NAT traversal solved**: rtpengine handles all complexity
- **Security improved**: Inference server not exposed to internet
- **Scalability enabled**: Add inference nodes behind proxy
- **Recording capability**: Media forking for QA/compliance

### Negative

- **Additional component**: rtpengine needs deployment and monitoring
- **Slight latency**: ~1-2ms added (negligible in practice)
- **Learning curve**: rtpengine NG protocol

### Mitigations

1. **rtpengine monitoring**: Prometheus metrics via rtpengine-exporter
2. **High availability**: rtpengine cluster with VRRP
3. **Documentation**: Internal runbook for common operations

---

## Validation

### Test Plan

```yaml
test_scenarios:
  - name: "Basic call flow"
    steps:
      - SIP INVITE from test client
      - Verify RTP session established
      - Send audio via RTP
      - Verify transcription received
      - Verify TTS audio returned
      - SIP BYE
    expected:
      - Call duration > 10s
      - No packet loss
      - Latency < 50ms (RTP path only)
      
  - name: "NAT traversal"
    topology: "Client behind NAT"
    steps:
      - SIP INVITE with private IP in SDP
      - Verify rtpengine handles NAT
      - Audio flows bidirectionally
    expected:
      - Successful media path
      
  - name: "Concurrent calls"
    concurrent: 100
    duration: 300s
    metrics: [success_rate, packet_loss, latency]
    expected:
      success_rate: > 0.99
      packet_loss: < 0.001
      latency_p99: < 100ms
```

---

## References

1. RFC 3550 - RTP: A Transport Protocol for Real-Time Applications
2. RFC 3711 - The Secure Real-time Transport Protocol (SRTP)
3. rtpengine Documentation: https://github.com/sipwise/rtpengine
4. Ooma's RTPengine Usage: https://www.ooma.com/blog/engineering/
5. Osproxy (WebRTC-SIP): https://github.com/nicknisi/osproxy
