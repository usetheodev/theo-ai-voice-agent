"""
Endpoint SIP com PJSUA2
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

from config import SIP_CONFIG, SBC_CONFIG, LOG_CONFIG
from sip.account import MyAccount

if TYPE_CHECKING:
    from ports.audio_destination import IAudioDestination

logger = logging.getLogger("media-server.endpoint")


class SIPEndpoint:
    """Endpoint SIP"""

    def __init__(self, audio_destination: "IAudioDestination", loop):
        self.audio_destination = audio_destination
        self.loop = loop
        self.ep: Optional[pj.Endpoint] = None
        self.account: Optional[MyAccount] = None
        self.running = False

    def start(self):
        """Inicia o endpoint SIP"""
        logger.info("🚀 Iniciando Endpoint SIP...")

        if SBC_CONFIG["enabled"]:
            logger.info("📡 Modo SBC habilitado")
            logger.info(f"   SBC Host: {SBC_CONFIG['host']}:{SBC_CONFIG['port']}")
            logger.info(f"   Transporte: {SBC_CONFIG['transport'].upper()}")
        else:
            logger.info("📡 Modo local (Asterisk direto)")

        # Cria endpoint PJSIP
        self.ep = pj.Endpoint()
        self.ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.logConfig.level = LOG_CONFIG["pjsip_log_level"]
        ep_cfg.logConfig.consoleLevel = LOG_CONFIG["pjsip_log_level"]

        if SBC_CONFIG["enabled"]:
            ep_cfg.uaConfig.userAgent = "PABX-AI-Agent/1.0"
            if SBC_CONFIG["keep_alive_interval"] > 0:
                ep_cfg.uaConfig.natTypeInSdp = 1

        self.ep.libInit(ep_cfg)

        # Null audio device
        self.ep.audDevManager().setNullDev()
        logger.info("🔇 Null audio device configurado")

        # Configura transporte
        self._setup_transport()

        self.ep.libStart()
        logger.info("✅ Endpoint SIP iniciado")

        # Registra
        self._register()
        self.running = True

    def _setup_transport(self):
        """Configura transporte SIP"""
        tp_cfg = pj.TransportConfig()

        if SBC_CONFIG["enabled"]:
            transport_type = SBC_CONFIG["transport"].lower()

            if SBC_CONFIG["public_ip"]:
                tp_cfg.publicAddress = SBC_CONFIG["public_ip"]
                logger.info(f"   IP público: {SBC_CONFIG['public_ip']}")

            tp_cfg.port = 0

            if transport_type == "tcp":
                self.ep.transportCreate(pj.PJSIP_TRANSPORT_TCP, tp_cfg)
                logger.info("🔌 Transporte TCP configurado")
            elif transport_type == "tls":
                tp_cfg.tlsConfig.method = pj.PJSIP_TLSV1_2_METHOD
                self.ep.transportCreate(pj.PJSIP_TRANSPORT_TLS, tp_cfg)
                logger.info("🔒 Transporte TLS configurado")
            else:
                self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tp_cfg)
                logger.info("🔌 Transporte UDP configurado")
        else:
            tp_cfg.port = SIP_CONFIG["rtp_port_start"]
            self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tp_cfg)
            logger.info("🔌 Transporte UDP local configurado")

    def _register(self):
        """Registra no servidor SIP"""
        acc_cfg = pj.AccountConfig()

        if SBC_CONFIG["enabled"]:
            sbc_host = SBC_CONFIG["host"]
            sbc_port = SBC_CONFIG["port"]
            transport = SBC_CONFIG["transport"].lower()

            logger.info(f"📝 Registrando via SBC: {SIP_CONFIG['username']}@{sbc_host}:{sbc_port}")

            acc_cfg.idUri = f"sip:{SIP_CONFIG['username']}@{sbc_host}"

            transport_param = ""
            if transport == "tcp":
                transport_param = ";transport=tcp"
            elif transport == "tls":
                transport_param = ";transport=tls"

            if SBC_CONFIG["register"]:
                acc_cfg.regConfig.registrarUri = f"sip:{sbc_host}:{sbc_port}{transport_param}"
                acc_cfg.regConfig.timeoutSec = SBC_CONFIG["register_timeout"]
                acc_cfg.regConfig.retryIntervalSec = 30
            else:
                acc_cfg.regConfig.registrarUri = ""
                logger.info("   Modo sem registro")

            outbound_proxy = SBC_CONFIG["outbound_proxy"]
            if not outbound_proxy and sbc_host:
                outbound_proxy = f"sip:{sbc_host}:{sbc_port}{transport_param}"

            if outbound_proxy:
                acc_cfg.sipConfig.proxies.append(outbound_proxy)
                logger.info(f"   Outbound proxy: {outbound_proxy}")

            acc_cfg.natConfig.iceEnabled = False
            acc_cfg.natConfig.sipStunUse = pj.PJSUA_STUN_USE_DISABLED
            acc_cfg.natConfig.mediaStunUse = pj.PJSUA_STUN_USE_DISABLED

            if SBC_CONFIG["keep_alive_interval"] > 0:
                acc_cfg.natConfig.udpKaIntervalSec = SBC_CONFIG["keep_alive_interval"]
                acc_cfg.natConfig.contactRewriteUse = 1

            realm = SBC_CONFIG["realm"] if SBC_CONFIG["realm"] else "*"

        else:
            logger.info(f"📝 Registrando: {SIP_CONFIG['username']}@{SIP_CONFIG['domain']}:{SIP_CONFIG['port']}")
            acc_cfg.idUri = f"sip:{SIP_CONFIG['username']}@{SIP_CONFIG['domain']}"
            acc_cfg.regConfig.registrarUri = f"sip:{SIP_CONFIG['domain']}:{SIP_CONFIG['port']}"
            realm = "*"

        # Credenciais
        cred = pj.AuthCredInfo()
        cred.scheme = "digest"
        cred.realm = realm if SBC_CONFIG["enabled"] else "*"
        cred.username = SIP_CONFIG["username"]
        cred.dataType = 0
        cred.data = SIP_CONFIG["password"]
        acc_cfg.sipConfig.authCreds.append(cred)

        # Cria conta
        self.account = MyAccount(self.audio_destination, self.loop)
        self.account.create(acc_cfg)

    def stop(self):
        """Para o endpoint"""
        logger.info("🛑 Parando endpoint SIP...")
        self.running = False

        if self.account:
            if self.account.current_call:
                try:
                    self.account.current_call.hangup(pj.CallOpParam())
                except Exception:
                    pass
            self.account.shutdown()

        if self.ep:
            self.ep.libDestroy()

        logger.info("✅ Endpoint SIP parado")
