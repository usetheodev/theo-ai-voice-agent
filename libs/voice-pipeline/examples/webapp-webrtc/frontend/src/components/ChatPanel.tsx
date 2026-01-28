import { useEffect, useRef } from 'react';
import { User, Bot } from 'lucide-react';
import { useAgentStore } from '../hooks/useAgentState';

export function ChatPanel() {
  const { messages, currentTranscript, isStreaming } = useAgentStore();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, currentTranscript]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto space-y-4 pr-2"
    >
      {messages.length === 0 && !currentTranscript ? (
        <div className="h-full flex items-center justify-center">
          <p className="text-gray-500 text-center">
            Conecte e comece a falar para iniciar a conversa
          </p>
        </div>
      ) : (
        <>
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex gap-3 ${
                message.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {message.role === 'assistant' && (
                <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center flex-shrink-0">
                  <Bot size={18} />
                </div>
              )}

              <div
                className={`max-w-[80%] rounded-lg px-4 py-2 ${
                  message.role === 'user'
                    ? 'bg-primary-600 text-white'
                    : 'bg-gray-700 text-gray-100'
                }`}
              >
                <p className="whitespace-pre-wrap">
                  {message.content}
                  {message.isStreaming && (
                    <span className="streaming-cursor" />
                  )}
                </p>
                <span className="text-xs opacity-50 mt-1 block">
                  {new Date(message.timestamp).toLocaleTimeString('pt-BR')}
                </span>
              </div>

              {message.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center flex-shrink-0">
                  <User size={18} />
                </div>
              )}
            </div>
          ))}

          {/* Current transcript (while user is speaking) */}
          {currentTranscript && !messages.some(m => m.content === currentTranscript) && (
            <div className="flex gap-3 justify-end opacity-70">
              <div className="max-w-[80%] rounded-lg px-4 py-2 bg-primary-600/50 text-white border border-primary-500 border-dashed">
                <p className="whitespace-pre-wrap italic">
                  {currentTranscript}
                  <span className="streaming-cursor" />
                </p>
              </div>
              <div className="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center flex-shrink-0">
                <User size={18} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
