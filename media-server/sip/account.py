"""
Gerenciamento de Conta SIP
"""

import logging
import asyncio
from typing import Optional, TYPE_CHECKING

try:
    import pjsua2 as pj
except ImportError:
    print("ERRO: pjsua2 não encontrado!")
    import sys
    sys.exit(1)

from config import SIP_CONFIG
from sip.call import MyCall
from metrics import (
    track_sip_registration,
    track_incoming_call,
    track_call_answered,
    track_call_rejected,
)

if TYPE_CHECKING:
    from ports.audio_destination import IAudioDestination

logger = logging.getLogger("media-server.account")


class MyAccount(pj.Account):
    """Gerencia a conta SIP"""

    def __init__(self, audio_destination: "IAudioDestination", loop):
        pj.Account.__init__(self)
        self.audio_destination = audio_destination
        self.loop = loop
        self.current_call: Optional[MyCall] = None

    def onRegState(self, prm):
        """Estado de registro mudou"""
        ai = self.getInfo()
        if ai.regStatus == 200:
            logger.info(f" Registrado! Ramal: {SIP_CONFIG['username']}")
            track_sip_registration(success=True)
        elif ai.regStatus >= 400:
            logger.error(f" Registro falhou: {ai.regStatus}")
            track_sip_registration(success=False, error_code=ai.regStatus)

    def onIncomingCall(self, prm):
        """Chamada recebida"""
        call = MyCall(self, self.audio_destination, self.loop, prm.callId)
        ci = call.getInfo()
        cid = call.unique_call_id

        # Registra métrica
        track_incoming_call()

        logger.info("=" * 50)
        logger.info(f"[{cid}]  CHAMADA RECEBIDA!")
        logger.info(f"[{cid}]    De: {ci.remoteUri}")
        logger.info("=" * 50)

        # Verifica se já há chamada em andamento
        if self.current_call is not None:
            logger.warning(f"[{cid}] ️ Rejeitando chamada - agente ocupado")
            track_call_rejected("busy")
            call_prm = pj.CallOpParam()
            call_prm.statusCode = 486  # Busy Here
            try:
                call.answer(call_prm)
            except Exception as e:
                logger.error(f"[{cid}] Erro ao rejeitar: {e}")
            return

        # Verifica se destino de áudio está conectado
        if not self.audio_destination or not self.audio_destination.is_connected:
            logger.warning(f"[{cid}] ️ Rejeitando chamada - destino de áudio não conectado")
            track_call_rejected("unavailable")
            call_prm = pj.CallOpParam()
            call_prm.statusCode = 503  # Service Unavailable
            try:
                call.answer(call_prm)
            except Exception as e:
                logger.error(f"[{cid}] Erro ao rejeitar: {e}")
            return

        # Atende
        logger.info(f"[{cid}]  Atendendo...")
        call_prm = pj.CallOpParam()
        call_prm.statusCode = 200

        try:
            call.answer(call_prm)
            self.current_call = call
            track_call_answered()
        except Exception as e:
            logger.error(f"[{cid}] Erro ao atender: {e}")
            track_call_rejected("error")
