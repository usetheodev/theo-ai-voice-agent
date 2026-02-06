"""
Endpoint SIP com PJSUA2
"""

import logging
import asyncio
import time
import threading
from typing import Optional, Callable, TYPE_CHECKING

try:
    import pjsua2 as pj
except ImportError:
    print("ERRO: pjsua2 não encontrado!")
    import sys
    sys.exit(1)

from config import SIP_CONFIG, SBC_CONFIG, LOG_CONFIG
from sip.account import MyAccount
from metrics import track_sip_registration

if TYPE_CHECKING:
    from ports.audio_destination import IAudioDestination
    from core.media_fork_manager import MediaForkManager

logger = logging.getLogger("media-server.endpoint")

# Intervalo de health check em segundos
HEALTH_CHECK_INTERVAL = 15

# Máximo de falhas consecutivas antes de recriar endpoint
MAX_CONSECUTIVE_FAILURES = 3


class SIPEndpoint:
    """Endpoint SIP"""

    def __init__(
        self,
        audio_destination: "IAudioDestination",
        loop,
        fork_manager: Optional["MediaForkManager"] = None,
        ami_client=None,
    ):
        self.audio_destination = audio_destination
        self.loop = loop
        self.fork_manager = fork_manager
        self.ami_client = ami_client
        self.ep: Optional[pj.Endpoint] = None
        self.account: Optional[MyAccount] = None
        self.running = False

        # Health check state
        self._consecutive_failures = 0
        self._health_check_thread: Optional[threading.Thread] = None
        self._on_sip_state_change: Optional[Callable[[str], None]] = None

    def set_on_sip_state_change(self, callback: Callable[[str], None]):
        """Define callback para mudança de estado SIP.

        Args:
            callback: função(state: str) chamada quando estado muda.
                      States: 'registered', 'unregistered', 'failed', 'recreated'
        """
        self._on_sip_state_change = callback

    def _notify_state_change(self, state: str):
        """Notifica callback de mudança de estado (thread-safe para asyncio)"""
        if self._on_sip_state_change and self.loop:
            try:
                self.loop.call_soon_threadsafe(self._on_sip_state_change, state)
            except RuntimeError:
                pass  # Loop já fechado

    def start(self):
        """Inicia o endpoint SIP"""
        logger.info(" Iniciando Endpoint SIP...")

        if SBC_CONFIG["enabled"]:
            logger.info(" Modo SBC habilitado")
            logger.info(f"   SBC Host: {SBC_CONFIG['host']}:{SBC_CONFIG['port']}")
            logger.info(f"   Transporte: {SBC_CONFIG['transport'].upper()}")
        else:
            logger.info(" Modo local (Asterisk direto)")

        self._create_and_start_endpoint()
        self.running = True

        # Inicia health check em thread separada
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop, daemon=True
        )
        self._health_check_thread.start()
        logger.info(f" SIP health check iniciado (intervalo={HEALTH_CHECK_INTERVAL}s)")

    def _create_and_start_endpoint(self):
        """Cria, inicializa e registra o endpoint PJSIP"""
        # Cria endpoint PJSIP
        self.ep = pj.Endpoint()
        self.ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.logConfig.level = LOG_CONFIG["pjsip_log_level"]
        ep_cfg.logConfig.consoleLevel = LOG_CONFIG["pjsip_log_level"]

        if SBC_CONFIG["enabled"]:
            ep_cfg.uaConfig.userAgent = SIP_CONFIG["user_agent"]
            if SBC_CONFIG["keep_alive_interval"] > 0:
                ep_cfg.uaConfig.natTypeInSdp = 1

        self.ep.libInit(ep_cfg)

        # Null audio device
        self.ep.audDevManager().setNullDev()
        logger.info(" Null audio device configurado")

        # Configura transporte
        self._setup_transport()

        self.ep.libStart()
        logger.info(" Endpoint SIP iniciado")

        # Registra
        self._register()

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
                logger.info(" Transporte TCP configurado")
            elif transport_type == "tls":
                tp_cfg.tlsConfig.method = pj.PJSIP_TLSV1_2_METHOD
                self.ep.transportCreate(pj.PJSIP_TRANSPORT_TLS, tp_cfg)
                logger.info(" Transporte TLS configurado")
            else:
                self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tp_cfg)
                logger.info(" Transporte UDP configurado")
        else:
            tp_cfg.port = SIP_CONFIG["rtp_port_start"]
            self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tp_cfg)
            logger.info(" Transporte UDP local configurado")

    def _get_transport_param(self, transport: str) -> str:
        """Retorna parâmetro de transporte para URI SIP."""
        if transport == "tcp":
            return ";transport=tcp"
        elif transport == "tls":
            return ";transport=tls"
        return ""

    def _configure_sbc_account(self, acc_cfg: pj.AccountConfig) -> str:
        """Configura conta para modo SBC. Retorna realm."""
        sbc_host = SBC_CONFIG["host"]
        sbc_port = SBC_CONFIG["port"]
        transport = SBC_CONFIG["transport"].lower()
        transport_param = self._get_transport_param(transport)

        logger.info(f" Registrando via SBC: {SIP_CONFIG['username']}@{sbc_host}:{sbc_port}")
        acc_cfg.idUri = f"sip:{SIP_CONFIG['username']}@{sbc_host}"

        # Configuração de registro
        if SBC_CONFIG["register"]:
            acc_cfg.regConfig.registrarUri = f"sip:{sbc_host}:{sbc_port}{transport_param}"
            acc_cfg.regConfig.timeoutSec = SBC_CONFIG["register_timeout"]
            acc_cfg.regConfig.retryIntervalSec = 30
        else:
            acc_cfg.regConfig.registrarUri = ""
            logger.info("   Modo sem registro")

        # Outbound proxy
        outbound_proxy = SBC_CONFIG["outbound_proxy"]
        if not outbound_proxy and sbc_host:
            outbound_proxy = f"sip:{sbc_host}:{sbc_port}{transport_param}"
        if outbound_proxy:
            acc_cfg.sipConfig.proxies.append(outbound_proxy)
            logger.info(f"   Outbound proxy: {outbound_proxy}")

        # NAT config
        acc_cfg.natConfig.iceEnabled = False
        acc_cfg.natConfig.sipStunUse = pj.PJSUA_STUN_USE_DISABLED
        acc_cfg.natConfig.mediaStunUse = pj.PJSUA_STUN_USE_DISABLED

        if SBC_CONFIG["keep_alive_interval"] > 0:
            acc_cfg.natConfig.udpKaIntervalSec = SBC_CONFIG["keep_alive_interval"]
            acc_cfg.natConfig.contactRewriteUse = 1

        return SBC_CONFIG["realm"] if SBC_CONFIG["realm"] else "*"

    def _configure_local_account(self, acc_cfg: pj.AccountConfig) -> str:
        """Configura conta para modo local/Asterisk. Retorna realm."""
        logger.info(f" Registrando: {SIP_CONFIG['username']}@{SIP_CONFIG['domain']}:{SIP_CONFIG['port']}")
        acc_cfg.idUri = f"sip:{SIP_CONFIG['username']}@{SIP_CONFIG['domain']}"
        acc_cfg.regConfig.registrarUri = f"sip:{SIP_CONFIG['domain']}:{SIP_CONFIG['port']}"
        return "*"

    def _configure_auth(self, acc_cfg: pj.AccountConfig, realm: str):
        """Configura autenticação SIP."""
        cred = pj.AuthCredInfo()
        cred.scheme = "digest"
        cred.realm = realm
        cred.username = SIP_CONFIG["username"]
        cred.dataType = 0
        cred.data = SIP_CONFIG["password"]
        acc_cfg.sipConfig.authCreds.append(cred)

    def _register(self):
        """Registra no servidor SIP"""
        acc_cfg = pj.AccountConfig()

        if SBC_CONFIG["enabled"]:
            realm = self._configure_sbc_account(acc_cfg)
        else:
            realm = self._configure_local_account(acc_cfg)

        self._configure_auth(acc_cfg, realm)

        # Cria conta
        self.account = MyAccount(
            self.audio_destination, self.loop, self.fork_manager,
            ami_client=self.ami_client,
        )
        self.account.create(acc_cfg)

    def _health_check_loop(self):
        """Loop de health check periódico (roda em thread separada)"""
        # Registra thread no PJSIP (obrigatório para chamar getInfo, setRegistration, etc)
        try:
            pj.Endpoint.instance().libRegisterThread("health-check")
        except Exception:
            pass

        while self.running:
            time.sleep(HEALTH_CHECK_INTERVAL)
            if not self.running:
                break

            try:
                self._check_registration()
            except Exception as e:
                logger.error(f"Erro no health check SIP: {e}")

    def _check_registration(self):
        """Verifica estado de registro SIP e tenta recuperar se necessário"""
        if not self.account:
            return

        try:
            ai = self.account.getInfo()
            reg_status = ai.regStatus
        except Exception as e:
            logger.warning(f"Não foi possível obter status SIP: {e}")
            self._consecutive_failures += 1
            self._handle_failure()
            return

        if reg_status == 200:
            # Registro OK
            if self._consecutive_failures > 0:
                logger.info("SIP registration restored")
                self._notify_state_change('registered')
                track_sip_registration(success=True)
            elif self._consecutive_failures == 0:
                # Primeira verificação após startup - notifica estado registrado
                self._notify_state_change('registered')
            self._consecutive_failures = 0
        else:
            # Registro perdido ou com problema
            self._consecutive_failures += 1
            logger.warning(
                f"SIP registration lost (status={reg_status}), "
                f"attempting re-register... "
                f"(falha {self._consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})"
            )
            track_sip_registration(success=False, error_code=reg_status)
            self._notify_state_change('unregistered')

            if self._consecutive_failures < MAX_CONSECUTIVE_FAILURES:
                # Tenta re-registro
                try:
                    self.account.setRegistration(True)
                    logger.info("Re-registro SIP solicitado")
                except Exception as e:
                    logger.error(f"Falha ao solicitar re-registro: {e}")
            else:
                self._handle_failure()

    def _handle_failure(self):
        """Trata falhas consecutivas - recria endpoint se necessário"""
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                f"SIP endpoint recreated after {MAX_CONSECUTIVE_FAILURES} failures"
            )
            self._notify_state_change('failed')
            self._recreate_endpoint()

    def _recreate_endpoint(self):
        """Destrói e recria o endpoint SIP"""
        logger.info("Recriando endpoint SIP - início da recriação")

        # Destrói endpoint atual
        try:
            if self.account:
                if self.account.current_call:
                    try:
                        self.account.current_call.hangup(pj.CallOpParam())
                    except Exception:
                        pass
                    # Aguarda callbacks PJSIP finalizarem após hangup
                    time.sleep(0.5)
                self.account.shutdown()
                self.account = None
                # Aguarda shutdown da account completar antes de destruir lib
                time.sleep(0.2)
        except Exception as e:
            logger.warning(f"Erro ao destruir account: {e}")

        try:
            if self.ep:
                self.ep.libDestroy()
                self.ep = None
        except Exception as e:
            logger.warning(f"Erro ao destruir endpoint: {e}")

        # Recria
        try:
            self._create_and_start_endpoint()
            self._consecutive_failures = 0
            self._notify_state_change('recreated')
            logger.info("Endpoint SIP recriado com sucesso - fim da recriação")
        except Exception as e:
            logger.error(f"Falha ao recriar endpoint SIP: {e}")
            # Reseta falhas para que o health check possa tentar novamente
            self._consecutive_failures = 0
            self._notify_state_change('failed')

    def stop(self):
        """Para o endpoint"""
        logger.info(" Parando endpoint SIP...")
        self.running = False

        # Aguarda thread de health check encerrar
        if self._health_check_thread and self._health_check_thread.is_alive():
            self._health_check_thread.join(timeout=HEALTH_CHECK_INTERVAL + 2)

        if self.account:
            if self.account.current_call:
                try:
                    self.account.current_call.hangup(pj.CallOpParam())
                except Exception:
                    pass
            self.account.shutdown()

        if self.ep:
            self.ep.libDestroy()

        logger.info(" Endpoint SIP parado")
