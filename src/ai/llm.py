"""
LLM Integration using Qwen2.5 Models

Provides async inference for conversational AI responses
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional
import torch
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    pipeline
)

from ..common.logging import get_logger
from ..common.config import AppConfig
from .prompts import PromptTemplate

logger = get_logger(__name__)


class QwenLLM:
    """Async LLM inference using Qwen2.5 models"""

    def __init__(self, config: AppConfig):
        """
        Initialize LLM.

        Args:
            config: Application configuration
        """
        self.config = config
        self.model_name = config.ai.llm_model
        self.max_tokens = config.ai.llm_max_tokens
        self.temperature = config.ai.llm_temperature
        self.system_prompt = config.ai.system_prompt

        # Model components (initialized in async initialize())
        self.model = None
        self.tokenizer = None
        self.text_generator = None

        # Async execution
        max_workers = getattr(config, 'performance', None)
        if max_workers and hasattr(max_workers, 'ai_worker_pool_size'):
            max_workers = max_workers.ai_worker_pool_size
        else:
            max_workers = 2  # Default to 2 workers

        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="llm-worker"
        )

        # Concurrency control
        max_concurrent = getattr(config, 'performance', None)
        if max_concurrent and hasattr(max_concurrent, 'max_concurrent_ai_pipelines'):
            max_concurrent = max_concurrent.max_concurrent_ai_pipelines
        else:
            max_concurrent = 2  # Default to 2 concurrent

        self.inference_semaphore = asyncio.Semaphore(max_concurrent)

        logger.info("QwenLLM created",
                   model=self.model_name,
                   max_tokens=self.max_tokens,
                   temperature=self.temperature)

    async def initialize(self):
        """Load model (blocking operation, run once at startup)"""
        logger.info("Initializing LLM",
                   model=self.model_name,
                   gpu_enabled=self.config.gpu.enabled if hasattr(self.config, 'gpu') else False)

        loop = asyncio.get_event_loop()

        try:
            # Run blocking model loading in thread pool
            await loop.run_in_executor(
                self.executor,
                self._load_model
            )

            logger.info("LLM initialized successfully",
                       model=self.model_name,
                       device=str(self.model.device) if hasattr(self.model, 'device') else 'unknown')

        except Exception as e:
            logger.error("Failed to initialize LLM",
                        model=self.model_name,
                        error=str(e),
                        exc_info=True)
            raise

    def _load_model(self):
        """Synchronous model loading (runs in thread pool)"""

        # Determine device configuration
        device_config = self._build_device_config()

        # Load tokenizer
        logger.info("Loading tokenizer", model=self.model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True
        )

        # Load model
        logger.info("Loading model (this may take 30-120 seconds)",
                   model=self.model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            trust_remote_code=True,
            **device_config
        )

        # Create text generation pipeline
        self.text_generator = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            torch_dtype=device_config.get("torch_dtype", torch.float32)
        )

        logger.info("Model loaded successfully",
                   model_size_mb=f"{self.model.get_memory_footprint() / 1024 / 1024:.2f}" if hasattr(self.model, 'get_memory_footprint') else 'unknown')

    def _build_device_config(self) -> dict:
        """Build device/dtype configuration"""
        # Check if GPU is available and enabled in config
        gpu_available = torch.cuda.is_available()
        gpu_enabled = hasattr(self.config, 'gpu') and self.config.gpu.enabled

        if gpu_available and gpu_enabled:
            logger.info("Using GPU for inference")
            device_map = getattr(self.config.gpu, 'device_map', 'auto')
            return {
                "device_map": device_map,
                "torch_dtype": torch.bfloat16
            }
        else:
            if gpu_enabled and not gpu_available:
                logger.warning("GPU enabled in config but CUDA not available, falling back to CPU")
            else:
                logger.info("Using CPU for inference")

            return {
                "device_map": None,
                "torch_dtype": torch.float32,
                "low_cpu_mem_usage": True
            }

    async def generate_response(
        self,
        user_text: str,
        conversation_history: List[Dict[str, str]]
    ) -> str:
        """
        Generate LLM response asynchronously.

        Args:
            user_text: Current user utterance
            conversation_history: Previous messages [{role, content}]

        Returns:
            Generated response text

        Raises:
            RuntimeError: If LLM not initialized
            Exception: On inference failure
        """
        if not self.text_generator:
            raise RuntimeError("LLM not initialized. Call initialize() first.")

        # Apply concurrency limit
        async with self.inference_semaphore:
            logger.debug("Generating LLM response",
                        user_text=user_text[:50],  # Log first 50 chars
                        history_length=len(conversation_history))

            loop = asyncio.get_event_loop()

            try:
                # Add timeout to inference
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        self.executor,
                        self._blocking_generate,
                        user_text,
                        conversation_history
                    ),
                    timeout=30.0  # 30 second timeout for CPU inference
                )

                logger.info("LLM response generated",
                           response_length=len(response))

                return response

            except asyncio.TimeoutError:
                logger.error("LLM inference timeout",
                            user_text=user_text[:50])
                return "Desculpe, não consegui processar sua mensagem a tempo."

            except Exception as e:
                logger.error("LLM inference failed",
                            error=str(e),
                            user_text=user_text[:50],
                            exc_info=True)
                return "Desculpe, ocorreu um erro ao processar sua mensagem."

    def _blocking_generate(
        self,
        user_text: str,
        conversation_history: List[Dict[str, str]]
    ) -> str:
        """Synchronous inference (runs in thread pool)"""

        # Format messages using Qwen chat template
        messages = PromptTemplate.format_for_qwen(
            system_prompt=self.system_prompt,
            conversation_history=conversation_history,
            user_text=user_text
        )

        # Apply chat template to get prompt
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        # Generate response
        outputs = self.text_generator(
            prompt,
            max_new_tokens=self.max_tokens,
            temperature=self.temperature,
            do_sample=True,
            top_p=0.9,
            repetition_penalty=1.1,
            return_full_text=False  # Return only generated text
        )

        # Extract generated text
        response_text = outputs[0]['generated_text'].strip()

        # Ensure concise response (1-3 sentences)
        response_text = PromptTemplate.truncate_response(response_text, max_sentences=3)

        return response_text

    async def shutdown(self):
        """Cleanup resources"""
        logger.info("Shutting down LLM")

        # Shutdown thread pool
        self.executor.shutdown(wait=True)

        # Clear GPU memory if using CUDA
        if self.model:
            if hasattr(self.model, 'device') and 'cuda' in str(self.model.device):
                import gc
                del self.model
                del self.tokenizer
                del self.text_generator
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("GPU memory cleared")
            else:
                # CPU cleanup
                del self.model
                del self.tokenizer
                del self.text_generator

        logger.info("LLM shutdown complete")

    def get_stats(self) -> dict:
        """
        Get LLM statistics.

        Returns:
            Dictionary with stats
        """
        stats = {
            'model_name': self.model_name,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'initialized': self.text_generator is not None
        }

        if self.model:
            stats['device'] = str(self.model.device) if hasattr(self.model, 'device') else 'unknown'

            if hasattr(self.model, 'get_memory_footprint'):
                stats['memory_mb'] = f"{self.model.get_memory_footprint() / 1024 / 1024:.2f}"

        return stats
