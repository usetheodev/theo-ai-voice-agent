/**
 * Voice Agent Frontend Application
 *
 * Handles microphone capture, WebSocket communication,
 * and audio playback for real-time voice conversations.
 *
 * Features (Phase 7-9):
 * - Streaming Granularity display (clause/sentence/word)
 * - Turn-Taking strategy display
 * - Full-Duplex indicator (user + agent speaking)
 * - Backchannel detection feedback
 * - Interruption mode feedback (immediate/graceful)
 * - Real-time metrics (TTFA, TTFT, RTF)
 *
 * Optimizations:
 * - msgpack: Binary serialization ~10x faster than JSON
 * - PCM16: Direct binary audio (no encoding overhead)
 */

// Configuration
const CONFIG = {
    wsUrl: `ws://${window.location.host}/ws/voice`,
    sampleRate: 16000,
    bufferSize: 4096,
    channels: 1,
    useMsgpack: true,  // Usar msgpack para mensagens de controle
};

// ==============================================================================
// Browser Compatibility Check
// ==============================================================================

function checkBrowserSupport() {
    const issues = [];

    // Check for secure context (HTTPS or localhost)
    if (!window.isSecureContext) {
        issues.push(
            'Esta pagina precisa ser acessada via HTTPS ou localhost. ' +
            'Acesse: http://localhost:8000 ou http://127.0.0.1:8000'
        );
    }

    // Check for mediaDevices API
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        const getUserMedia = navigator.getUserMedia ||
            navigator.webkitGetUserMedia ||
            navigator.mozGetUserMedia ||
            navigator.msGetUserMedia;

        if (!getUserMedia) {
            issues.push(
                'Seu navegador nao suporta acesso ao microfone. ' +
                'Use Chrome, Firefox ou Edge atualizado.'
            );
        }
    }

    // Check for AudioContext
    if (!window.AudioContext && !window.webkitAudioContext) {
        issues.push('Seu navegador nao suporta Web Audio API.');
    }

    // Check for WebSocket
    if (!window.WebSocket) {
        issues.push('Seu navegador nao suporta WebSocket.');
    }

    return issues;
}

// State
let websocket = null;
let audioContext = null;
let mediaStream = null;
let audioProcessor = null;
let isListening = false;
let audioQueue = [];
let isPlayingAudio = false;
let isFullDuplex = false;
let backchannelTimeout = null;

// DOM Elements
const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const statusBadge = document.getElementById('statusBadge');
const chatContainer = document.getElementById('chatContainer');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const shortcutHint = document.getElementById('shortcutHint');
const visualizerBars = document.querySelectorAll('.visualizer-bar');
const strategyPanel = document.getElementById('strategyPanel');
const metricsBar = document.getElementById('metricsBar');

// ==============================================================================
// WebSocket Communication
// ==============================================================================

function connectWebSocket() {
    return new Promise((resolve, reject) => {
        updateStatus('connecting', 'Conectando...');

        websocket = new WebSocket(CONFIG.wsUrl);

        websocket.onopen = () => {
            console.log('WebSocket connected');
            updateStatus('connected', 'Conectado');

            // Send configuration
            websocket.send(JSON.stringify({
                type: 'config',
                sample_rate: CONFIG.sampleRate,
                language: 'pt'
            }));

            resolve();
        };

        websocket.onclose = () => {
            console.log('WebSocket disconnected');
            updateStatus('idle', 'Desconectado');
            stopConversation();
        };

        websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            updateStatus('error', 'Erro de conexao');
            reject(error);
        };

        websocket.onmessage = handleWebSocketMessage;
    });
}

function handleWebSocketMessage(event) {
    if (event.data instanceof Blob) {
        // Binary data: pode ser msgpack (controle) ou PCM16 (audio)
        event.data.arrayBuffer().then(buffer => {
            if (CONFIG.useMsgpack && typeof MessagePack !== 'undefined') {
                // Tentar decodificar como msgpack
                try {
                    const uint8 = new Uint8Array(buffer);
                    const data = MessagePack.decode(uint8);

                    // Se tem "type", eh mensagem de controle
                    if (data && typeof data === 'object' && data.type) {
                        handleControlMessage(data);
                        return;
                    }
                } catch (e) {
                    // Nao eh msgpack valido, eh audio PCM16
                }
            }

            // Fallback: tratar como audio
            handleAudioBuffer(buffer);
        });
    } else {
        // JSON control message (fallback para compatibilidade)
        try {
            const data = JSON.parse(event.data);
            handleControlMessage(data);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
    }
}

const AUDIO_QUEUE_MAX_SIZE = 50;

async function handleAudioBuffer(arrayBuffer) {
    // Limitar tamanho da fila para evitar consumo excessivo de memoria
    if (audioQueue.length >= AUDIO_QUEUE_MAX_SIZE) {
        audioQueue.shift();
        console.warn('Audio queue overflow: descartado chunk antigo');
    }

    audioQueue.push(arrayBuffer);

    if (!isPlayingAudio) {
        playNextAudio();
    }
}

function handleControlMessage(data) {
    console.log('Received:', data);

    switch (data.type) {
        case 'status':
            updateStatus(data.state, getStatusText(data.state));
            break;

        case 'vad':
            if (data.event === 'speech_start') {
                updateStatus('listening', 'Ouvindo...');
            } else if (data.event === 'speech_end') {
                updateStatus('processing', 'Processando...');
            }
            break;

        case 'transcript':
            addMessage('user', data.text);
            break;

        case 'response_chunk':
            updateAssistantMessage(data.text);
            break;

        case 'response':
            finalizeAssistantMessage(data.text);
            break;

        case 'error':
            console.error('Server error:', data.message);
            addSystemMessage('Erro: ' + data.message);
            break;

        case 'interrupted':
            addSystemMessage('Resposta interrompida');
            break;

        // === Phase 7-9: New event types ===

        case 'strategy_info':
            handleStrategyInfo(data);
            break;

        case 'full_duplex':
            handleFullDuplex(data);
            break;

        case 'backchannel':
            handleBackchannel(data);
            break;

        case 'interruption':
            handleInterruption(data);
            break;

        case 'metrics':
            handleMetrics(data);
            break;
    }
}

// ==============================================================================
// Phase 7-9: New Event Handlers
// ==============================================================================

function handleStrategyInfo(data) {
    // Display active strategies
    const panel = document.getElementById('strategyPanel');
    panel.classList.add('active');

    // Parse strategy names to friendly display
    document.getElementById('strategyStreaming').textContent = formatStrategyName(data.streaming);
    document.getElementById('strategyTurnTaking').textContent = formatStrategyName(data.turn_taking);
    document.getElementById('strategyInterruption').textContent = formatStrategyName(data.interruption);
}

function formatStrategyName(name) {
    if (!name) return '-';
    // "ClauseStreamingStrategy(clause)" -> "Clause"
    // "AdaptiveSilenceTurnTaking" -> "Adaptive"
    // "BackchannelAwareInterruption" -> "Backchannel"
    const mappings = {
        'ClauseStreamingStrategy': 'Clause',
        'SentenceStreamingStrategy': 'Sentence',
        'WordStreamingStrategy': 'Word',
        'AdaptiveStreamingStrategy': 'Adaptive',
        'AdaptiveSilenceTurnTaking': 'Adaptive',
        'FixedSilenceTurnTaking': 'Fixed',
        'SemanticTurnTaking': 'Semantic',
        'BackchannelAwareInterruption': 'Backchannel',
        'ImmediateInterruption': 'Immediate',
        'GracefulInterruption': 'Graceful',
    };

    for (const [key, value] of Object.entries(mappings)) {
        if (name.includes(key)) return value;
    }
    return name;
}

function handleFullDuplex(data) {
    if (data.event === 'start') {
        isFullDuplex = true;
        statusBadge.className = 'status-badge full-duplex';
        statusBadge.textContent = 'Full-Duplex';
        // Update indicator to full_duplex color
        statusIndicator.className = 'status-indicator full_duplex';
    } else if (data.event === 'end') {
        isFullDuplex = false;
        statusBadge.className = 'status-badge';
        statusBadge.textContent = '';
    }
}

function handleBackchannel(data) {
    // Show backchannel badge briefly
    statusBadge.className = 'status-badge backchannel';
    statusBadge.textContent = 'Backchannel #' + data.count;

    // Clear previous timeout
    if (backchannelTimeout) clearTimeout(backchannelTimeout);

    // Hide badge after 2 seconds
    backchannelTimeout = setTimeout(() => {
        if (!isFullDuplex) {
            statusBadge.className = 'status-badge';
            statusBadge.textContent = '';
        }
    }, 2000);

    console.log('Backchannel detectado #' + data.count);
}

function handleInterruption(data) {
    const modeText = data.mode === 'interrupt_graceful' ? 'graceful' : 'imediata';
    addSystemMessage('Interrupcao ' + modeText + ' #' + data.count);
}

function handleMetrics(data) {
    metricsBar.classList.add('active');

    if (data.ttfa != null) {
        document.getElementById('metricTTFA').textContent = (data.ttfa * 1000).toFixed(0) + 'ms';
    }
    if (data.ttft != null) {
        document.getElementById('metricTTFT').textContent = (data.ttft * 1000).toFixed(0) + 'ms';
    }
    if (data.sentences != null) {
        document.getElementById('metricChunks').textContent = data.sentences;
    }
    if (data.rtf != null) {
        document.getElementById('metricRTF').textContent = data.rtf.toFixed(2) + 'x';
    }
}

// ==============================================================================
// Audio Capture
// ==============================================================================

async function startAudioCapture() {
    try {
        // Check if mediaDevices is available
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw new Error(
                'Acesso ao microfone indisponivel. ' +
                'Certifique-se de acessar via http://localhost:8000 ou http://127.0.0.1:8000'
            );
        }

        // Request microphone access
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: CONFIG.sampleRate,
                channelCount: CONFIG.channels,
                echoCancellation: true,
                noiseSuppression: true,
            }
        });

        // Create audio context
        audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: CONFIG.sampleRate
        });

        // Create audio source
        const source = audioContext.createMediaStreamSource(mediaStream);

        // Create script processor for capturing audio
        audioProcessor = audioContext.createScriptProcessor(CONFIG.bufferSize, 1, 1);

        audioProcessor.onaudioprocess = (event) => {
            if (!isListening || isPlayingAudio || !websocket || websocket.readyState !== WebSocket.OPEN) {
                return;
            }

            const inputData = event.inputBuffer.getChannelData(0);

            // Convert to 16-bit PCM
            const pcmData = floatTo16BitPCM(inputData);

            // Send to server
            websocket.send(pcmData);

            // Update visualizer
            updateVisualizer(inputData);
        };

        // Connect nodes
        source.connect(audioProcessor);
        audioProcessor.connect(audioContext.destination);

        console.log('Audio capture started');

    } catch (error) {
        console.error('Failed to start audio capture:', error);
        throw error;
    }
}

function stopAudioCapture() {
    if (audioProcessor) {
        audioProcessor.disconnect();
        audioProcessor = null;
    }

    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }

    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }

    console.log('Audio capture stopped');
}

function floatTo16BitPCM(float32Array) {
    const buffer = new ArrayBuffer(float32Array.length * 2);
    const view = new DataView(buffer);

    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return buffer;
}

// ==============================================================================
// Audio Playback
// ==============================================================================

async function playNextAudio() {
    if (audioQueue.length === 0) {
        isPlayingAudio = false;
        return;
    }

    isPlayingAudio = true;
    updateStatus('speaking', 'Falando...');

    const arrayBuffer = audioQueue.shift();

    try {
        // Create playback context if needed
        if (!audioContext || audioContext.state === 'closed') {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }

        // Convert PCM16 to AudioBuffer
        const audioBuffer = pcm16ToAudioBuffer(arrayBuffer, 24000); // Server sends 24kHz

        // Play audio
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);

        source.onended = () => {
            playNextAudio();
        };

        source.start();

    } catch (error) {
        console.error('Failed to play audio:', error);
        playNextAudio();
    }
}

function pcm16ToAudioBuffer(arrayBuffer, sampleRate) {
    const dataView = new DataView(arrayBuffer);
    const numSamples = arrayBuffer.byteLength / 2;

    const audioBuffer = audioContext.createBuffer(1, numSamples, sampleRate);
    const channelData = audioBuffer.getChannelData(0);

    for (let i = 0; i < numSamples; i++) {
        const sample = dataView.getInt16(i * 2, true);
        channelData[i] = sample / 32768;
    }

    return audioBuffer;
}

// ==============================================================================
// UI Updates
// ==============================================================================

function updateStatus(state, text) {
    // Don't override full_duplex indicator while it's active
    if (isFullDuplex && state === 'speaking') {
        statusIndicator.className = 'status-indicator full_duplex';
    } else {
        statusIndicator.className = `status-indicator ${state}`;
    }
    statusText.textContent = text;
}

function getStatusText(state) {
    const texts = {
        'idle': 'Pronto',
        'listening': 'Ouvindo...',
        'processing': 'Pensando...',
        'speaking': 'Falando...',
    };
    return texts[state] || state;
}

function addMessage(role, text) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    const label = role === 'user' ? 'Voce' : 'Assistente';
    messageDiv.innerHTML = `
        <div class="message-label">${label}</div>
        <div class="message-bubble">${escapeHtml(text)}</div>
    `;
    chatContainer.appendChild(messageDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

let currentAssistantMessage = null;
let currentAssistantText = '';

function updateAssistantMessage(chunk) {
    if (!currentAssistantMessage) {
        currentAssistantMessage = document.createElement('div');
        currentAssistantMessage.className = 'message assistant';
        currentAssistantMessage.innerHTML = `
            <div class="message-label">Assistente</div>
            <div class="message-bubble"></div>
        `;
        chatContainer.appendChild(currentAssistantMessage);
        currentAssistantText = '';
    }

    currentAssistantText += chunk;
    const bubble = currentAssistantMessage.querySelector('.message-bubble');
    bubble.textContent = currentAssistantText;
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function finalizeAssistantMessage(fullText) {
    if (currentAssistantMessage) {
        const bubble = currentAssistantMessage.querySelector('.message-bubble');
        bubble.textContent = fullText;
    }
    currentAssistantMessage = null;
    currentAssistantText = '';
}

function addSystemMessage(text) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message system';
    messageDiv.innerHTML = `
        <div class="message-bubble" style="background: rgba(255,255,255,0.05); color: #888; text-align: center;">
            ${escapeHtml(text)}
        </div>
    `;
    chatContainer.appendChild(messageDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function updateVisualizer(audioData) {
    const bars = visualizerBars;
    const step = Math.floor(audioData.length / bars.length);

    for (let i = 0; i < bars.length; i++) {
        let sum = 0;
        for (let j = 0; j < step; j++) {
            sum += Math.abs(audioData[i * step + j]);
        }
        const average = sum / step;
        const height = Math.max(10, Math.min(40, average * 500));
        bars[i].style.height = `${height}px`;
    }
}

// ==============================================================================
// Main Controls
// ==============================================================================

async function startConversation() {
    try {
        startBtn.disabled = true;

        // Check browser support first
        const issues = checkBrowserSupport();
        if (issues.length > 0) {
            throw new Error(issues.join('\n'));
        }

        // Connect WebSocket
        await connectWebSocket();

        // Start audio capture
        await startAudioCapture();

        // Tell server to start listening
        websocket.send(JSON.stringify({ type: 'start' }));

        isListening = true;

        // Update UI
        startBtn.style.display = 'none';
        stopBtn.style.display = 'block';
        shortcutHint.style.display = 'block';

    } catch (error) {
        console.error('Failed to start conversation:', error);
        addSystemMessage('Falha ao iniciar: ' + error.message);
        startBtn.disabled = false;
    }
}

function stopConversation() {
    isListening = false;
    isFullDuplex = false;

    // Stop audio
    stopAudioCapture();

    // Close WebSocket
    if (websocket) {
        websocket.send(JSON.stringify({ type: 'stop' }));
        websocket.close();
        websocket = null;
    }

    // Clear audio queue
    audioQueue = [];
    isPlayingAudio = false;

    // Update UI
    startBtn.style.display = 'block';
    startBtn.disabled = false;
    stopBtn.style.display = 'none';
    shortcutHint.style.display = 'none';
    updateStatus('idle', 'Desconectado');

    // Hide strategy panel and metrics
    strategyPanel.classList.remove('active');
    metricsBar.classList.remove('active');
    statusBadge.className = 'status-badge';
    statusBadge.textContent = '';

    // Reset visualizer
    visualizerBars.forEach(bar => bar.style.height = '10px');
}

function interruptResponse() {
    if (websocket && websocket.readyState === WebSocket.OPEN) {
        websocket.send(JSON.stringify({ type: 'interrupt' }));

        // Clear audio queue
        audioQueue = [];
        isPlayingAudio = false;
    }
}

// Keyboard shortcut: Space to interrupt
document.addEventListener('keydown', (event) => {
    if (event.code === 'Space' && isListening) {
        event.preventDefault();
        interruptResponse();
    }
});

// Initialize
console.log('Voice Agent Frontend loaded');

// Check browser support on load
document.addEventListener('DOMContentLoaded', () => {
    const issues = checkBrowserSupport();
    if (issues.length > 0) {
        console.warn('Browser compatibility issues:', issues);
        addSystemMessage('Aviso: ' + issues.join(' '));
        startBtn.disabled = true;
        startBtn.title = issues.join('\n');
    }
});
