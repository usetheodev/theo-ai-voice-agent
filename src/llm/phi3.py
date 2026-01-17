"""
Phi-3 LLM Integration using llama.cpp

Uses llama-cpp-python for fast CPU inference.
Phi-3 is a small, efficient language model optimized for conversational AI.
"""

import logging
from typing import Optional, List, Dict
from llama_cpp import Llama


class Phi3LLM:
    """
    Phi-3 LLM wrapper using llama.cpp

    Usage:
        llm = Phi3LLM(
            model_path="/app/models/llm/phi-3-mini.gguf",
            system_prompt="Você é um assistente virtual útil e amigável."
        )

        response = llm.generate("Olá, como você está?")
        # Output: "Olá! Estou bem, obrigado por perguntar. Como posso ajudá-lo hoje?"
    """

    def __init__(self,
                 model_path: str,
                 system_prompt: str = "Você é um assistente virtual útil e amigável.",
                 n_ctx: int = 2048,
                 n_threads: int = 4,
                 temperature: float = 0.7,
                 max_tokens: int = 150):
        """
        Initialize Phi-3 LLM

        Args:
            model_path: Path to Phi-3 GGUF model file
            system_prompt: System prompt defining assistant behavior
            n_ctx: Context window size (tokens)
            n_threads: Number of CPU threads
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
            max_tokens: Maximum tokens in response
        """
        self.model_path = model_path
        self.system_prompt = system_prompt
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.logger = logging.getLogger("ai-voice-agent.llm.phi3")

        # Initialize the model
        try:
            self.llm = Llama(
                model_path=model_path,
                n_ctx=n_ctx,
                n_threads=n_threads,
                verbose=False
            )
            self.logger.info(f"Phi-3 LLM initialized: {model_path} (ctx={n_ctx}, threads={n_threads})")
            self.logger.info(f"LLM config: max_tokens={max_tokens}, temperature={temperature}")
            self.logger.info(f"System prompt: {system_prompt[:80]}...")
        except Exception as e:
            self.logger.error(f"Failed to initialize Phi-3 model: {e}")
            raise

        # Conversation history
        self.conversation_history: List[Dict[str, str]] = []

        # Statistics
        self.responses_count = 0
        self.total_tokens_generated = 0

    def generate(self, user_message: str, reset_history: bool = False) -> Optional[str]:
        """
        Generate response to user message

        Args:
            user_message: User's input text
            reset_history: If True, clear conversation history before generating

        Returns:
            Generated response or None on error
        """
        try:
            if reset_history:
                self.conversation_history = []

            # Add user message to history
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            # Build prompt with conversation history
            prompt = self._build_prompt()

            self.logger.debug(f"Generating response for: {user_message}")

            # Generate response
            response = self.llm(
                prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stop=[
                    "<|end|>",
                    "<|user|>",
                    "\n\nUser:",
                    "\n\nHuman:",
                    "Instrucción",  # Stop Spanish contamination
                    "Instrução",    # Stop Portuguese formal instructions
                    "Pregunta",     # Stop Spanish questions
                    "\n\n\n",       # Stop multiple newlines
                    "\n\nExemplo:", # Stop examples
                ],
                echo=False
            )

            # Extract generated text
            if response and 'choices' in response and len(response['choices']) > 0:
                generated_text = response['choices'][0]['text'].strip()

                # Clean up common artifacts
                generated_text = self._clean_response(generated_text)

                if generated_text:
                    # Add assistant response to history
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": generated_text
                    })

                    # Update statistics
                    self.responses_count += 1
                    if 'usage' in response:
                        self.total_tokens_generated += response['usage'].get('completion_tokens', 0)

                    self.logger.info(f"✅ Response #{self.responses_count}: {generated_text}")
                    return generated_text

            self.logger.warning("LLM returned empty response")
            return None

        except Exception as e:
            self.logger.error(f"Error generating response: {e}", exc_info=True)
            return None

    def _build_prompt(self) -> str:
        """
        Build prompt from conversation history

        Format for Phi-3:
        <|system|>
        System prompt here
        <|end|>
        <|user|>
        User message
        <|end|>
        <|assistant|>
        """
        # Start with system prompt
        prompt_parts = [
            "<|system|>",
            self.system_prompt,
            "<|end|>"
        ]

        # Add conversation history
        for msg in self.conversation_history:
            role = msg['role']
            content = msg['content']

            if role == "user":
                prompt_parts.append(f"<|user|>\n{content}<|end|>")
            elif role == "assistant":
                prompt_parts.append(f"<|assistant|>\n{content}<|end|>")

        # Add assistant prompt to start generation
        prompt_parts.append("<|assistant|>")

        return "\n".join(prompt_parts)

    def _clean_response(self, text: str) -> str:
        """Clean up generated response"""
        # Remove special tokens
        text = text.replace("<|end|>", "")
        text = text.replace("<|assistant|>", "")
        text = text.replace("<|user|>", "")
        text = text.replace("<|system|>", "")

        # Remove leading/trailing whitespace
        text = text.strip()

        # Remove duplicate punctuation
        while "  " in text:
            text = text.replace("  ", " ")

        return text

    def reset_conversation(self):
        """Clear conversation history"""
        self.conversation_history = []
        self.logger.info("Conversation history cleared")

    def get_stats(self) -> dict:
        """Get LLM statistics"""
        return {
            'responses_count': self.responses_count,
            'total_tokens_generated': self.total_tokens_generated,
            'conversation_turns': len(self.conversation_history),
            'model': self.model_path,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens
        }


def test_phi3_llm():
    """Test Phi-3 LLM with sample prompts"""
    llm = Phi3LLM(
        model_path="/app/models/llm/phi-3-mini.gguf",
        system_prompt="Você é um assistente virtual brasileiro, útil e amigável.",
        max_tokens=100
    )

    # Test conversation
    prompts = [
        "Olá, tudo bem?",
        "Qual é a capital do Brasil?",
        "Obrigado pela ajuda!"
    ]

    for prompt in prompts:
        print(f"\nUser: {prompt}")
        response = llm.generate(prompt)
        print(f"Assistant: {response}")

    print(f"\nStats: {llm.get_stats()}")


if __name__ == '__main__':
    test_phi3_llm()
