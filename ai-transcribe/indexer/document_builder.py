"""
Document Builder - Constroi documentos para indexacao no Elasticsearch
"""

import uuid
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List


@dataclass
class TranscriptionDocument:
    """
    Documento de transcricao para indexacao no Elasticsearch.

    Representa uma utterance transcrita com metadados.
    """
    utterance_id: str
    session_id: str
    call_id: str
    text: str
    timestamp: datetime
    audio_duration_ms: int
    transcription_latency_ms: int
    language: str = "pt"
    language_probability: float = 0.0
    speaker: str = "caller"
    caller_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Embedding fields
    text_embedding: Optional[List[float]] = None
    embedding_model: Optional[str] = None
    embedding_latency_ms: Optional[float] = None

    # Enrichment fields
    sentiment_label: Optional[str] = None      # positive, negative, neutral
    sentiment_score: Optional[float] = None    # -1.0 a 1.0
    topics: List[str] = field(default_factory=list)
    intent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionario para indexacao."""
        doc = asdict(self)
        # Converte datetime para ISO format
        doc["timestamp"] = self.timestamp.isoformat()

        # Remove campos None para evitar indexar valores vazios
        if doc.get("text_embedding") is None:
            del doc["text_embedding"]
        if doc.get("embedding_model") is None:
            del doc["embedding_model"]
        if doc.get("embedding_latency_ms") is None:
            del doc["embedding_latency_ms"]
        if doc.get("sentiment_label") is None:
            del doc["sentiment_label"]
        if doc.get("sentiment_score") is None:
            del doc["sentiment_score"]
        if not doc.get("topics"):
            del doc["topics"]
        if doc.get("intent") is None:
            del doc["intent"]

        return doc

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranscriptionDocument":
        """Cria documento a partir de dicionario."""
        # Converte timestamp string para datetime
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


class DocumentBuilder:
    """
    Builder para criar documentos de transcricao.

    Example:
        builder = DocumentBuilder()
        doc = builder.build(
            session_id="session-123",
            call_id="call-456",
            text="Ola, como posso ajudar?",
            audio_duration_ms=1500,
            transcription_latency_ms=200,
            language="pt",
            language_probability=0.95
        )
    """

    def __init__(self):
        pass

    def build(
        self,
        session_id: str,
        call_id: str,
        text: str,
        audio_duration_ms: int,
        transcription_latency_ms: int,
        language: str = "pt",
        language_probability: float = 0.0,
        speaker: str = "caller",
        caller_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        utterance_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        text_embedding: Optional[List[float]] = None,
        embedding_model: Optional[str] = None,
        embedding_latency_ms: Optional[float] = None,
        sentiment_label: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        topics: Optional[List[str]] = None,
        intent: Optional[str] = None,
    ) -> TranscriptionDocument:
        """
        Constroi um documento de transcricao.

        Args:
            session_id: ID da sessao WebSocket
            call_id: ID da chamada SIP
            text: Texto transcrito
            audio_duration_ms: Duracao do audio em ms
            transcription_latency_ms: Latencia da transcricao em ms
            language: Codigo do idioma (ISO-639-1)
            language_probability: Probabilidade do idioma detectado
            speaker: Identificador do falante (caller, agent)
            caller_id: Numero de telefone do chamador
            metadata: Metadados adicionais
            utterance_id: ID unico da utterance (gerado se nao fornecido)
            timestamp: Timestamp da transcricao (agora se nao fornecido)
            text_embedding: Vetor de embedding do texto (384 dims)
            embedding_model: Nome do modelo de embedding usado
            embedding_latency_ms: Latencia da geracao do embedding
            sentiment_label: Label de sentimento (positive, negative, neutral)
            sentiment_score: Score de sentimento (-1.0 a 1.0)
            topics: Lista de topicos detectados
            intent: Intencao detectada

        Returns:
            TranscriptionDocument pronto para indexacao
        """
        return TranscriptionDocument(
            utterance_id=utterance_id or str(uuid.uuid4()),
            session_id=session_id,
            call_id=call_id,
            text=text,
            timestamp=timestamp or datetime.utcnow(),
            audio_duration_ms=audio_duration_ms,
            transcription_latency_ms=transcription_latency_ms,
            language=language,
            language_probability=language_probability,
            speaker=speaker,
            caller_id=caller_id,
            metadata=metadata or {},
            text_embedding=text_embedding,
            embedding_model=embedding_model,
            embedding_latency_ms=embedding_latency_ms,
            sentiment_label=sentiment_label,
            sentiment_score=sentiment_score,
            topics=topics or [],
            intent=intent,
        )
