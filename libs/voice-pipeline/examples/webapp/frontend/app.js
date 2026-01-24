/**
 * Voice Agent Frontend Application
 *
 * Handles microphone capture, WebSocket communication,
 * and audio playback for real-time voice conversations.
 */

// Configuration
const CONFIG = {
    wsUrl: `ws://${window.location.hostname}:8000/ws/voice`,
    sampleRate: 16000,
    bufferSize: 4096,
    channels: 1,
};

// State
let websocket = null;
let audioContext = null;
let mediaStream = null;
let audioProcessor = null;
let isListening = false;
let audioQueue = [];
let isPlayingAudio = false;

// DOM Elements
const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const chatContainer = document.getElementById('chatContainer');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const visualizerBars = document.querySelectorAll('.visualizer-bar');

// ==============================================================================
// WebSocket Communication
// ==============================================================================

function connectWebSocket() {
    return new Promise((resolve, reject) => {
        updateStatus('connecting', 'Connecting...');

        websocket = new WebSocket(CONFIG.wsUrl);

        websocket.onopen = () => {
            console.log('WebSocket connected');
            updateStatus('connected', 'Connected');

            // Send configuration
            websocket.send(JSON.stringify({
                type: 'config',
                sample_rate: CONFIG.sampleRate,
                language: 'pt'  // Português brasileiro
            }));

            resolve();
        };

        websocket.onclose = () => {
            console.log('WebSocket disconnected');
            updateStatus('idle', 'Disconnected');
            stopConversation();
        };

        websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            updateStatus('error', 'Connection error');
            reject(error);
        };

        websocket.onmessage = handleWebSocketMessage;
    });
}

function handleWebSocketMessage(event) {
    if (event.data instanceof Blob) {
        // Binary audio data
        handleAudioData(event.data);
    } else {
        // JSON control message
        try {
            const data = JSON.parse(event.data);
            handleControlMessage(data);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
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
                updateStatus('listening', 'Listening...');
            } else if (data.event === 'speech_end') {
                updateStatus('processing', 'Processing...');
            }
            break;

        case 'transcript':
            addMessage('user', data.text);
            break;

        case 'response_chunk':
            // Update current assistant message
            updateAssistantMessage(data.text);
            break;

        case 'response':
            // Final response
            finalizeAssistantMessage(data.text);
            break;

        case 'error':
            console.error('Server error:', data.message);
            addSystemMessage(`Error: ${data.message}`);
            break;

        case 'interrupted':
            addSystemMessage('Response interrupted');
            break;
    }
}

async function handleAudioData(blob) {
    // Queue audio for playback
    const arrayBuffer = await blob.arrayBuffer();
    audioQueue.push(arrayBuffer);

    if (!isPlayingAudio) {
        playNextAudio();
    }
}

// ==============================================================================
// Audio Capture
// ==============================================================================

async function startAudioCapture() {
    try {
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
            if (!isListening || !websocket || websocket.readyState !== WebSocket.OPEN) {
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
    updateStatus('speaking', 'Speaking...');

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
    statusIndicator.className = `status-indicator ${state}`;
    statusText.textContent = text;
}

function getStatusText(state) {
    const texts = {
        'idle': 'Ready',
        'listening': 'Listening...',
        'processing': 'Thinking...',
        'speaking': 'Speaking...',
    };
    return texts[state] || state;
}

function addMessage(role, text) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `
        <div class="message-label">${role === 'user' ? 'You' : 'Assistant'}</div>
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
            <div class="message-label">Assistant</div>
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

    } catch (error) {
        console.error('Failed to start conversation:', error);
        addSystemMessage('Failed to start: ' + error.message);
        startBtn.disabled = false;
    }
}

function stopConversation() {
    isListening = false;

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
    updateStatus('idle', 'Disconnected');

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
