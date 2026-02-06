"""
Cliente AMI (Asterisk Manager Interface) assíncrono

Implementa conexão TCP com o Asterisk AMI para envio de ações
como Redirect (transferência de canal). Usa asyncio StreamReader/StreamWriter.

Protocolo AMI:
- Texto puro sobre TCP (porta padrão 5038)
- Ações enviadas como "Action: X\r\nKey: Value\r\n\r\n"
- Respostas terminadas por "\r\n\r\n"
- Cada ação usa ActionID (uuid4) para correlação
"""

import asyncio
import logging
import uuid
from typing import Optional

logger = logging.getLogger("media-server.ami")


class AMIClient:
    """Cliente AMI assíncrono para controle do Asterisk.

    Suporta apenas as ações necessárias: Login, Redirect e Logoff.
    Implementa auto-reconnect no Redirect (se conexão caiu).
    Não implementa subscription de eventos.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        secret: str,
        timeout: float = 5.0,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._secret = secret
        self._timeout = timeout

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Verifica se a conexão está ativa."""
        return self._connected

    async def connect(self) -> bool:
        """Abre conexão TCP com o AMI e faz login.

        Returns:
            True se conectou e logou com sucesso, False caso contrário.
        """
        try:
            logger.info(
                "Conectando ao AMI %s:%d (user=%s)",
                self._host,
                self._port,
                self._username,
            )

            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )

            # AMI envia banner na conexão (ex: "Asterisk Call Manager/6.0.0\r\n")
            banner = await self._read_line()
            if banner:
                logger.info("AMI banner: %s", banner.strip())
            else:
                logger.warning("Nenhum banner recebido do AMI")

            # Login
            if not await self.login():
                await self._close_transport()
                return False

            self._connected = True
            logger.info("AMI conectado e autenticado com sucesso")
            return True

        except asyncio.TimeoutError:
            logger.error(
                "Timeout ao conectar ao AMI %s:%d",
                self._host,
                self._port,
            )
            await self._close_transport()
            return False
        except OSError as exc:
            logger.error(
                "Erro de rede ao conectar ao AMI %s:%d: %s",
                self._host,
                self._port,
                exc,
            )
            await self._close_transport()
            return False
        except Exception as exc:
            logger.error("Erro inesperado ao conectar ao AMI: %s", exc)
            await self._close_transport()
            return False

    async def login(self) -> bool:
        """Envia ação Login ao AMI.

        Returns:
            True se login aceito (Response: Success).
        """
        action_id = str(uuid.uuid4())
        action = (
            "Action: Login\r\n"
            f"ActionID: {action_id}\r\n"
            f"Username: {self._username}\r\n"
            f"Secret: {self._secret}\r\n"
            "\r\n"
        )

        logger.debug("Enviando Login (ActionID=%s)", action_id)

        response = await self._send_action(action)
        if response is None:
            logger.error("Sem resposta para Login (ActionID=%s)", action_id)
            return False

        success = self._is_success(response)
        if success:
            logger.info("Login aceito (ActionID=%s)", action_id)
        else:
            message = self._extract_field(response, "Message")
            logger.error(
                "Login rejeitado (ActionID=%s): %s",
                action_id,
                message or response,
            )

        return success

    async def redirect(
        self,
        channel: str,
        context: str,
        exten: str,
        priority: int = 1,
    ) -> bool:
        """Envia ação Redirect para transferir um canal.

        Args:
            channel: Nome do canal SIP (ex: "PJSIP/1004-00000001")
            context: Contexto do dialplan destino
            exten: Extensão destino
            priority: Prioridade no dialplan (default 1)

        Returns:
            True se o Asterisk aceitou o Redirect.
        """
        # Auto-reconnect se conexao caiu (ex: Asterisk restart)
        if not self._connected:
            logger.warning("AMI desconectado - tentando reconectar antes do Redirect")
            if not await self.reconnect():
                logger.error("Redirect falhou: reconexao AMI falhou")
                return False

        action_id = str(uuid.uuid4())
        action = (
            "Action: Redirect\r\n"
            f"ActionID: {action_id}\r\n"
            f"Channel: {channel}\r\n"
            f"Context: {context}\r\n"
            f"Exten: {exten}\r\n"
            f"Priority: {priority}\r\n"
            "\r\n"
        )

        logger.info(
            "Redirect (ActionID=%s): channel=%s -> %s,%s,%d",
            action_id,
            channel,
            context,
            exten,
            priority,
        )

        response = await self._send_action(action)
        if response is None:
            logger.error("Sem resposta para Redirect (ActionID=%s)", action_id)
            self._connected = False
            return False

        success = self._is_success(response)
        if success:
            logger.info("Redirect aceito (ActionID=%s)", action_id)
        else:
            message = self._extract_field(response, "Message")
            logger.error(
                "Redirect rejeitado (ActionID=%s): %s",
                action_id,
                message or response,
            )

        return success

    async def close(self):
        """Envia Logoff e fecha a conexão TCP."""
        if not self._connected:
            return

        # Tenta enviar Logoff gracefully
        try:
            action_id = str(uuid.uuid4())
            logoff = (
                "Action: Logoff\r\n"
                f"ActionID: {action_id}\r\n"
                "\r\n"
            )
            logger.debug("Enviando Logoff (ActionID=%s)", action_id)
            await self._send_action(logoff)
        except Exception as exc:
            logger.debug("Erro ao enviar Logoff (ignorado): %s", exc)

        self._connected = False
        await self._close_transport()
        logger.info("AMI desconectado")

    async def reconnect(self) -> bool:
        """Fecha conexao existente e reconecta ao AMI.

        Returns:
            True se reconectou com sucesso.
        """
        logger.info("Tentando reconexao AMI...")
        await self._close_transport()
        return await self.connect()

    # -------------------------------------------------------------------------
    # Métodos internos
    # -------------------------------------------------------------------------

    async def _send_action(self, action: str) -> Optional[str]:
        """Envia uma ação AMI e aguarda a resposta.

        Serializado via lock para evitar interleaving de reads concorrentes.

        Args:
            action: String formatada da ação AMI (terminada em \\r\\n\\r\\n).

        Returns:
            Texto completo da resposta ou None se falhou.
        """
        async with self._lock:
            if self._writer is None or self._reader is None:
                return None

            try:
                self._writer.write(action.encode("utf-8"))
                await asyncio.wait_for(
                    self._writer.drain(),
                    timeout=self._timeout,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                logger.error("Erro ao enviar ação AMI: %s", exc)
                self._connected = False
                return None

            # Lê resposta (delimitada por \r\n\r\n)
            return await self._read_response()

    async def _read_response(self) -> Optional[str]:
        """Lê uma resposta AMI completa (delimitada por \\r\\n\\r\\n).

        Trata leituras parciais acumulando em buffer até encontrar
        o delimitador de fim de resposta.

        Returns:
            Texto da resposta ou None se timeout/erro.
        """
        if self._reader is None:
            return None

        buffer = ""

        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()

                chunk = await asyncio.wait_for(
                    self._reader.read(4096),
                    timeout=remaining,
                )
                if not chunk:
                    # Conexão fechada pelo peer
                    logger.warning("Conexão AMI fechada pelo servidor")
                    self._connected = False
                    return None

                buffer += chunk.decode("utf-8", errors="replace")

                # Resposta completa termina com \r\n\r\n
                if "\r\n\r\n" in buffer:
                    # Retorna apenas até o primeiro delimitador completo
                    end_idx = buffer.index("\r\n\r\n") + 4
                    return buffer[:end_idx]

        except asyncio.TimeoutError:
            logger.error("Timeout lendo resposta AMI (%.1fs)", self._timeout)
            return None
        except OSError as exc:
            logger.error("Erro de rede lendo resposta AMI: %s", exc)
            self._connected = False
            return None

    async def _read_line(self) -> Optional[str]:
        """Lê uma única linha do AMI (usado para o banner inicial).

        Returns:
            Linha lida ou None se falhou.
        """
        if self._reader is None:
            return None

        try:
            line = await asyncio.wait_for(
                self._reader.readline(),
                timeout=self._timeout,
            )
            return line.decode("utf-8", errors="replace") if line else None
        except (asyncio.TimeoutError, OSError) as exc:
            logger.warning("Erro lendo linha do AMI: %s", exc)
            return None

    async def _close_transport(self):
        """Fecha o writer/transport TCP."""
        self._connected = False

        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass

        self._writer = None
        self._reader = None

    @staticmethod
    def _is_success(response: str) -> bool:
        """Verifica se a resposta AMI indica sucesso.

        Args:
            response: Texto completo da resposta AMI.

        Returns:
            True se contém "Response: Success".
        """
        for line in response.split("\r\n"):
            if line.strip().lower() == "response: success":
                return True
        return False

    @staticmethod
    def _extract_field(response: str, field: str) -> Optional[str]:
        """Extrai o valor de um campo da resposta AMI.

        Args:
            response: Texto completo da resposta AMI.
            field: Nome do campo (ex: "Message").

        Returns:
            Valor do campo ou None se não encontrado.
        """
        prefix = f"{field}: "
        for line in response.split("\r\n"):
            stripped = line.strip()
            if stripped.lower().startswith(prefix.lower()):
                return stripped[len(prefix):]
        return None
