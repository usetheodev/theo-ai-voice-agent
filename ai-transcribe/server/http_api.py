"""
HTTP API Server - Endpoint de Busca Semantica

Fornece API REST para busca semantica nas transcricoes.

Endpoints:
    GET /api/search?q=texto&limit=10&speaker=caller
    GET /api/health
"""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from aiohttp import web

from config import HTTP_API_CONFIG

logger = logging.getLogger("ai-transcribe.http-api")


class SearchAPIServer:
    """
    Servidor HTTP para API de busca semantica.

    Usa aiohttp para servir endpoints REST que permitem
    busca semantica nas transcricoes indexadas.

    Example:
        server = SearchAPIServer(es_client, embedding_provider)
        await server.start()
    """

    def __init__(
        self,
        es_client,
        embedding_provider,
        config: Optional[dict] = None,
    ):
        self._config = config or HTTP_API_CONFIG
        self._es_client = es_client
        self._embedding_provider = embedding_provider
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def start(self) -> bool:
        """Inicia o servidor HTTP."""
        if not self._config.get("enabled", True):
            logger.info("HTTP API desabilitada")
            return False

        try:
            self._app = web.Application()
            self._setup_routes()

            self._runner = web.AppRunner(self._app)
            await self._runner.setup()

            host = self._config["host"]
            port = self._config["port"]

            self._site = web.TCPSite(self._runner, host, port)
            await self._site.start()

            logger.info(f"HTTP API iniciada em http://{host}:{port}")
            logger.info(f"  Busca: GET /api/search?q=texto")
            logger.info(f"  Health: GET /api/health")

            return True

        except Exception as e:
            logger.error(f"Erro ao iniciar HTTP API: {e}")
            return False

    async def stop(self) -> None:
        """Para o servidor HTTP."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        logger.info("HTTP API parada")

    def _setup_routes(self) -> None:
        """Configura rotas da API."""
        self._app.router.add_get("/api/search", self._handle_search)
        self._app.router.add_get("/api/health", self._handle_health)
        self._app.router.add_get("/", self._handle_root)

    async def _handle_root(self, request: web.Request) -> web.Response:
        """Handler para rota raiz - retorna info da API."""
        info = {
            "service": "AI Transcribe Search API",
            "version": "1.0.0",
            "endpoints": {
                "search": "GET /api/search?q=texto&limit=10&speaker=caller|agent&hybrid=true",
                "health": "GET /api/health",
            },
            "examples": [
                "/api/search?q=cliente reclamou do atendimento",
                "/api/search?q=problema com pagamento&limit=20",
                "/api/search?q=cancelar pedido&speaker=caller",
            ],
        }
        return web.json_response(info)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handler para health check."""
        health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "elasticsearch": self._es_client.is_connected if self._es_client else False,
                "embedding_provider": self._embedding_provider.is_connected if self._embedding_provider else False,
            },
        }

        status_code = 200 if all(health["components"].values()) else 503
        return web.json_response(health, status=status_code)

    async def _handle_search(self, request: web.Request) -> web.Response:
        """
        Handler para busca semantica.

        Query params:
            q: Texto da busca (obrigatorio)
            limit: Numero de resultados (default: 10, max: 100)
            speaker: Filtrar por speaker (caller|agent)
            hybrid: Usar busca hibrida (default: true)
            from_date: Data inicial (ISO format)
            to_date: Data final (ISO format)
        """
        # Valida query
        query_text = request.query.get("q", "").strip()
        if not query_text:
            return web.json_response(
                {"error": "Parametro 'q' obrigatorio", "example": "/api/search?q=texto"},
                status=400,
            )

        # Parametros opcionais
        limit = min(
            int(request.query.get("limit", self._config["default_results"])),
            self._config["max_results"],
        )
        speaker = request.query.get("speaker")
        hybrid = request.query.get("hybrid", "true").lower() == "true"
        from_date = request.query.get("from_date")
        to_date = request.query.get("to_date")

        # Verifica dependencias
        if not self._embedding_provider or not self._embedding_provider.is_connected:
            return web.json_response(
                {"error": "Embedding provider nao disponivel"},
                status=503,
            )

        if not self._es_client or not self._es_client.is_connected:
            return web.json_response(
                {"error": "Elasticsearch nao disponivel"},
                status=503,
            )

        try:
            # Gera embedding da query
            embedding_result = await self._embedding_provider.embed_query(query_text)

            # Monta filtros
            filters = self._build_filters(speaker, from_date, to_date)

            # Executa busca semantica
            search_result = await self._es_client.semantic_search(
                query_embedding=embedding_result.embedding,
                query_text=query_text if hybrid else None,
                k=limit,
                filters=filters,
                hybrid=hybrid,
            )

            # Formata resposta
            response = self._format_search_response(
                query_text=query_text,
                search_result=search_result,
                embedding_latency_ms=embedding_result.latency_ms,
            )

            return web.json_response(response)

        except Exception as e:
            logger.error(f"Erro na busca: {e}")
            return web.json_response(
                {"error": f"Erro na busca: {str(e)}"},
                status=500,
            )

    def _build_filters(
        self,
        speaker: Optional[str],
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Constroi filtros para a busca."""
        conditions = []

        if speaker:
            conditions.append({"term": {"speaker": speaker}})

        if from_date or to_date:
            date_range = {}
            if from_date:
                date_range["gte"] = from_date
            if to_date:
                date_range["lte"] = to_date
            conditions.append({"range": {"timestamp": date_range}})

        if not conditions:
            return None

        if len(conditions) == 1:
            return conditions[0]

        return {"bool": {"must": conditions}}

    def _format_search_response(
        self,
        query_text: str,
        search_result: Dict[str, Any],
        embedding_latency_ms: float,
    ) -> Dict[str, Any]:
        """Formata resposta da busca."""
        hits = search_result.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        results = []

        for hit in hits.get("hits", []):
            source = hit.get("_source", {})
            results.append({
                "id": hit.get("_id"),
                "score": hit.get("_score"),
                "text": source.get("text"),
                "timestamp": source.get("timestamp"),
                "speaker": source.get("speaker"),
                "session_id": source.get("session_id"),
                "call_id": source.get("call_id"),
                "audio_duration_ms": source.get("audio_duration_ms"),
            })

        return {
            "query": query_text,
            "total": total,
            "count": len(results),
            "embedding_latency_ms": round(embedding_latency_ms, 1),
            "results": results,
        }
