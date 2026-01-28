import { create } from 'zustand';

// Event types matching backend
export type EventType =
  | 'connected'
  | 'disconnected'
  | 'error'
  | 'vad_start'
  | 'vad_end'
  | 'vad_level'
  | 'asr_start'
  | 'asr_partial'
  | 'asr_final'
  | 'llm_start'
  | 'llm_token'
  | 'llm_end'
  | 'tts_start'
  | 'tts_chunk'
  | 'tts_end'
  | 'tool_call'
  | 'tool_result'
  | 'tool_feedback'
  | 'memory_recall'
  | 'memory_save'
  | 'permission_request'
  | 'permission_response'
  | 'mcp_connected'
  | 'mcp_disconnected'
  | 'mcp_tools'
  | 'agent_state'
  | 'agent_turn'
  | 'metrics';

export interface AgentEvent {
  type: EventType;
  data: Record<string, unknown>;
  timestamp: number;
  sequence?: number;
}

export type AgentState = 'idle' | 'listening' | 'processing' | 'speaking' | 'interrupted' | 'error' | 'ended';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  isStreaming?: boolean;
}

export interface ToolExecution {
  id: string;
  name: string;
  status: 'pending' | 'executing' | 'completed' | 'error';
  feedback?: string;
  result?: unknown;
  error?: string;
  startTime: number;
  endTime?: number;
}

export interface Episode {
  id: string;
  summary: string;
  timestamp: number;
}

export interface Metrics {
  turnCount: number;
  totalAudioDurationMs: number;
  latency: {
    ttfaMs: number | null;
    ttftMs: number | null;
    e2eMs: number | null;
  };
}

export interface PermissionRequest {
  id: string;
  toolName: string;
  level: string;
  reason: string;
  onApprove: () => void;
  onDeny: () => void;
}

interface AgentStore {
  // State
  agentState: AgentState;
  messages: Message[];
  currentTranscript: string;
  currentResponse: string;
  isStreaming: boolean;
  vadLevel: number;
  tools: ToolExecution[];
  episodes: Episode[];
  metrics: Metrics;
  permissionRequest: PermissionRequest | null;
  mcpServers: string[];
  mcpTools: string[];

  // Actions
  handleEvent: (event: AgentEvent) => void;
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void;
  updateLastMessage: (content: string) => void;
  clearMessages: () => void;
  setPermissionResponse: (approved: boolean) => void;
  reset: () => void;
}

const initialState = {
  agentState: 'idle' as AgentState,
  messages: [] as Message[],
  currentTranscript: '',
  currentResponse: '',
  isStreaming: false,
  vadLevel: 0,
  tools: [] as ToolExecution[],
  episodes: [] as Episode[],
  metrics: {
    turnCount: 0,
    totalAudioDurationMs: 0,
    latency: {
      ttfaMs: null,
      ttftMs: null,
      e2eMs: null,
    },
  },
  permissionRequest: null as PermissionRequest | null,
  mcpServers: [] as string[],
  mcpTools: [] as string[],
};

export const useAgentStore = create<AgentStore>((set, get) => ({
  ...initialState,

  handleEvent: (event: AgentEvent) => {
    const { type, data } = event;

    switch (type) {
      case 'agent_state':
        set({ agentState: data.state as AgentState });
        break;

      case 'vad_start':
        set({ agentState: 'listening', currentTranscript: '' });
        break;

      case 'vad_end':
        set({ agentState: 'processing' });
        break;

      case 'vad_level':
        set({ vadLevel: data.level as number });
        break;

      case 'asr_start':
        set({ currentTranscript: '' });
        break;

      case 'asr_partial':
        set({ currentTranscript: data.text as string });
        break;

      case 'asr_final':
        const transcript = data.text as string;
        set({ currentTranscript: transcript });
        get().addMessage({ role: 'user', content: transcript });
        break;

      case 'llm_start':
        set({ isStreaming: true, currentResponse: '' });
        get().addMessage({ role: 'assistant', content: '', isStreaming: true });
        break;

      case 'llm_token':
        set(state => ({
          currentResponse: state.currentResponse + (data.token as string),
        }));
        get().updateLastMessage(get().currentResponse);
        break;

      case 'llm_end':
        set({ isStreaming: false });
        // Finalize the last message
        const { messages } = get();
        if (messages.length > 0) {
          const lastMsg = messages[messages.length - 1];
          if (lastMsg.isStreaming) {
            set({
              messages: messages.map((m, i) =>
                i === messages.length - 1 ? { ...m, isStreaming: false } : m
              ),
            });
          }
        }
        break;

      case 'tts_start':
        set({ agentState: 'speaking' });
        break;

      case 'tts_end':
        set({ agentState: 'listening' });
        break;

      case 'tool_call':
        const toolExecution: ToolExecution = {
          id: `tool-${Date.now()}`,
          name: data.name as string,
          status: 'executing',
          startTime: Date.now(),
        };
        set(state => ({ tools: [...state.tools, toolExecution] }));
        break;

      case 'tool_result':
        set(state => ({
          tools: state.tools.map(t =>
            t.name === data.name && t.status === 'executing'
              ? { ...t, status: 'completed', result: data.result, endTime: Date.now() }
              : t
          ),
        }));
        break;

      case 'tool_feedback':
        set(state => ({
          tools: state.tools.map(t =>
            t.name === data.tool && t.status === 'executing'
              ? { ...t, feedback: data.phrase as string }
              : t
          ),
        }));
        break;

      case 'memory_recall':
        const episodes = (data.episodes as Array<{id: string; summary: string; timestamp: number}>)
          .map(ep => ({
            id: ep.id,
            summary: ep.summary,
            timestamp: ep.timestamp,
          }));
        set({ episodes });
        break;

      case 'memory_save':
        // Could add notification or update episodes list
        break;

      case 'permission_request':
        set({
          permissionRequest: {
            id: `perm-${Date.now()}`,
            toolName: data.tool_name as string,
            level: data.level as string,
            reason: data.reason as string,
            onApprove: () => get().setPermissionResponse(true),
            onDeny: () => get().setPermissionResponse(false),
          },
        });
        break;

      case 'metrics':
        const metricsData = data as {
          turn_count?: number;
          total_audio_duration_ms?: number;
          latency?: {
            ttfa_ms?: number | null;
            ttft_ms?: number | null;
            e2e_ms?: number | null;
          };
        };
        set({
          metrics: {
            turnCount: metricsData.turn_count ?? 0,
            totalAudioDurationMs: metricsData.total_audio_duration_ms ?? 0,
            latency: {
              ttfaMs: metricsData.latency?.ttfa_ms ?? null,
              ttftMs: metricsData.latency?.ttft_ms ?? null,
              e2eMs: metricsData.latency?.e2e_ms ?? null,
            },
          },
        });
        break;

      case 'mcp_connected':
        set(state => ({
          mcpServers: [...state.mcpServers, data.server as string],
        }));
        break;

      case 'mcp_disconnected':
        set(state => ({
          mcpServers: state.mcpServers.filter(s => s !== data.server),
        }));
        break;

      case 'mcp_tools':
        set({ mcpTools: data.tools as string[] });
        break;

      case 'error':
        set({ agentState: 'error' });
        console.error('Agent error:', data.error);
        break;
    }
  },

  addMessage: (message) => {
    const newMessage: Message = {
      ...message,
      id: `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: Date.now(),
    };
    set(state => ({ messages: [...state.messages, newMessage] }));
  },

  updateLastMessage: (content) => {
    set(state => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        messages[messages.length - 1] = {
          ...messages[messages.length - 1],
          content,
        };
      }
      return { messages };
    });
  },

  clearMessages: () => {
    set({ messages: [], currentTranscript: '', currentResponse: '' });
  },

  setPermissionResponse: (approved) => {
    const { permissionRequest } = get();
    if (permissionRequest) {
      // Here we would send the response back to the backend
      // For now, just clear the request
      set({ permissionRequest: null });
    }
  },

  reset: () => {
    set(initialState);
  },
}));
