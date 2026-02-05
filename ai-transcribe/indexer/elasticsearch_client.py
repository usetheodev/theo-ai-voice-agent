"""
Elasticsearch Client - Cliente async para Elasticsearch
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from elasticsearch import AsyncElasticsearch
from elasticsearch.exceptions import ConnectionError as ESConnectionError

from config import ES_CONFIG

logger = logging.getLogger("ai-transcribe.elasticsearch")


# Mapeamento do indice de transcricoes
INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "portuguese_analyzer": {
                    "type": "standard",
                    "stopwords": "_portuguese_"
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "utterance_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "call_id": {"type": "keyword"},
            "text": {
                "type": "text",
                "analyzer": "portuguese_analyzer",
                "fields": {
                    "raw": {"type": "keyword"}
                }
            },
            "timestamp": {"type": "date"},
            "audio_duration_ms": {"type": "integer"},
            "transcription_latency_ms": {"type": "integer"},
            "language": {"type": "keyword"},
            "language_probability": {"type": "float"},
            "speaker": {"type": "keyword"},
            "caller_id": {"type": "keyword"},
            "metadata": {"type": "object", "enabled": True}
        }
    }
}


class ElasticsearchClient:
    """
    Cliente async para Elasticsearch.

    Gerencia conexao, criacao de indices e operacoes CRUD.

    Example:
        client = ElasticsearchClient()
        await client.connect()
        await client.index_document(doc)
        await client.disconnect()
    """

    def __init__(self):
        self._client: Optional[AsyncElasticsearch] = None
        self._connected = False
        self._index_prefix = ES_CONFIG["index_prefix"]

    @property
    def is_connected(self) -> bool:
        """Verifica se esta conectado."""
        return self._connected

    def _get_index_name(self, timestamp: Optional[datetime] = None) -> str:
        """
        Gera nome do indice com sufixo de mes.

        Args:
            timestamp: Timestamp para determinar o mes (agora se nao fornecido)

        Returns:
            Nome do indice (ex: voice-transcriptions-2024.01)
        """
        ts = timestamp or datetime.utcnow()
        return f"{self._index_prefix}-{ts.strftime('%Y.%m')}"

    async def connect(self) -> bool:
        """
        Conecta ao Elasticsearch.

        Returns:
            True se conectou com sucesso
        """
        if self._connected:
            return True

        try:
            hosts = ES_CONFIG["hosts"]
            if isinstance(hosts, str):
                hosts = [hosts]

            self._client = AsyncElasticsearch(
                hosts=hosts,
                max_retries=ES_CONFIG["max_retries"],
                retry_on_timeout=ES_CONFIG["retry_on_timeout"],
                request_timeout=ES_CONFIG["request_timeout"],
            )

            # Testa conexao
            info = await self._client.info()
            logger.info(f"Conectado ao Elasticsearch: {info['version']['number']}")

            # Cria indice se nao existir
            await self._ensure_index()

            self._connected = True
            return True

        except ESConnectionError as e:
            logger.error(f"Falha ao conectar ao Elasticsearch: {e}")
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"Erro ao conectar ao Elasticsearch: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Desconecta do Elasticsearch."""
        if self._client:
            await self._client.close()
            self._client = None
        self._connected = False
        logger.info("Desconectado do Elasticsearch")

    async def _ensure_index(self) -> None:
        """Cria indice se nao existir."""
        index_name = self._get_index_name()

        try:
            exists = await self._client.indices.exists(index=index_name)
            if not exists:
                await self._client.indices.create(
                    index=index_name,
                    body=INDEX_MAPPING
                )
                logger.info(f"Indice criado: {index_name}")
            else:
                logger.debug(f"Indice ja existe: {index_name}")
        except Exception as e:
            logger.error(f"Erro ao criar indice: {e}")

    async def index_document(
        self,
        document: Dict[str, Any],
        doc_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Indexa um documento.

        Args:
            document: Documento a ser indexado
            doc_id: ID do documento (gerado se nao fornecido)
            timestamp: Timestamp para determinar o indice

        Returns:
            True se indexou com sucesso
        """
        if not self._connected:
            logger.warning("Tentando indexar sem conexao")
            return False

        try:
            # Garante que indice do mes existe
            await self._ensure_index()

            index_name = self._get_index_name(timestamp)

            result = await self._client.index(
                index=index_name,
                id=doc_id,
                document=document,
            )

            logger.debug(f"Documento indexado: {result['_id']} em {index_name}")
            return True

        except Exception as e:
            logger.error(f"Erro ao indexar documento: {e}")
            return False

    async def bulk_index(
        self,
        documents: List[Dict[str, Any]],
    ) -> int:
        """
        Indexa multiplos documentos em bulk.

        Args:
            documents: Lista de documentos a serem indexados

        Returns:
            Numero de documentos indexados com sucesso
        """
        if not self._connected:
            logger.warning("Tentando bulk index sem conexao")
            return 0

        if not documents:
            return 0

        try:
            # Garante que indice existe
            await self._ensure_index()

            # Prepara operacoes bulk
            operations = []
            for doc in documents:
                index_name = self._get_index_name(
                    datetime.fromisoformat(doc["timestamp"])
                    if isinstance(doc.get("timestamp"), str)
                    else doc.get("timestamp")
                )

                operations.append({"index": {"_index": index_name}})
                operations.append(doc)

            # Executa bulk
            result = await self._client.bulk(operations=operations)

            # Conta sucessos
            success_count = sum(
                1 for item in result["items"]
                if item["index"]["status"] in (200, 201)
            )

            if result.get("errors"):
                error_count = len(documents) - success_count
                logger.warning(f"Bulk index com {error_count} erros")

            logger.debug(f"Bulk index: {success_count}/{len(documents)} documentos")
            return success_count

        except Exception as e:
            logger.error(f"Erro no bulk index: {e}")
            return 0

    async def search(
        self,
        query: Dict[str, Any],
        size: int = 10,
        from_: int = 0,
    ) -> Dict[str, Any]:
        """
        Busca documentos.

        Args:
            query: Query Elasticsearch
            size: Numero maximo de resultados
            from_: Offset para paginacao

        Returns:
            Resultado da busca
        """
        if not self._connected:
            logger.warning("Tentando buscar sem conexao")
            return {"hits": {"total": {"value": 0}, "hits": []}}

        try:
            result = await self._client.search(
                index=f"{self._index_prefix}-*",
                query=query,
                size=size,
                from_=from_,
            )
            return result

        except Exception as e:
            logger.error(f"Erro na busca: {e}")
            return {"hits": {"total": {"value": 0}, "hits": []}}

    async def health_check(self) -> Dict[str, Any]:
        """
        Verifica saude do cluster.

        Returns:
            Status de saude do cluster
        """
        if not self._connected:
            return {"status": "disconnected"}

        try:
            health = await self._client.cluster.health()
            return {
                "status": health["status"],
                "cluster_name": health["cluster_name"],
                "number_of_nodes": health["number_of_nodes"],
            }
        except Exception as e:
            logger.error(f"Erro no health check: {e}")
            return {"status": "error", "error": str(e)}
