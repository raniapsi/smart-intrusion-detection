"""
proxy/reverse_proxy.py — Reverse Proxy PQC (Côté Middleware)
=============================================================
Périmètre Ryan ZERHOUNI — Architecture §4.4 Double Tunnel Proxy

Rôle :
  Termine les connexions TLS PQC venant du Forward Proxy,
  vérifie l'identité du client (mTLS), puis redirige le trafic
  déchiffré vers les services internes (Mosquitto Broker, Node-RED).

Architecture réseau :
  [Forward Proxy] →(TLS PQC)→ [Reverse Proxy] →(plain)→ [Mosquitto :1883]
                                                        → [Node-RED  :1880]

Sécurité par segmentation Docker :
  - Réseau iot-net (internal: true) : Forward Proxy ↔ Reverse Proxy uniquement
  - Réseau middleware-net (internal: true) : Reverse Proxy ↔ Mosquitto/Node-RED
  - Le Reverse Proxy est le seul container avec interfaces sur les deux réseaux
  - Impossible de joindre Mosquitto directement depuis le réseau IoT
"""

import asyncio
import logging
import struct
import base64
from typing import Optional

log = logging.getLogger("pqc.reverse-proxy")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")


# ═══════════════════════════════════════════════════════════════════
#  ReverseProxy
# ═══════════════════════════════════════════════════════════════════

class ReverseProxy:
    """
    Reverse Proxy PQC — Côté Middleware.

    Écoute les connexions PQC entrantes du Forward Proxy et les relaie
    vers le service interne cible (Mosquitto, Node-RED…).

    Paramètres :
      listen_host/port   : interface PQC exposée au réseau transit
      backend_host/port  : service interne cible (ex: mosquitto:1883)
      pqc_server         : instance PQCServer configurée avec les clés middleware
      protocol           : "MQTT" | "HTTP" (pour le logging)
    """

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        backend_host: str,
        backend_port: int,
        pqc_server,          # PQCServer — évite import circulaire
        protocol: str = "MQTT",
    ):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.backend_host = backend_host
        self.backend_port = backend_port
        self._pqc_server = pqc_server
        self.protocol = protocol
        self._active_tunnels = 0
        self._total_connections = 0
        self._total_bytes_decrypted = 0

    async def start(self):
        """Configure le PQCServer avec le handler de relai et démarre l'écoute."""
        self._pqc_server._app_handler = self._relay_handler
        await self._pqc_server.start()

    async def _relay_handler(
        self,
        channel,                          # SecureChannel
        client_id: str,
        pqc_reader: asyncio.StreamReader,
        pqc_writer: asyncio.StreamWriter,
    ):
        """
        Appelé après handshake PQC réussi.
        Ouvre une connexion vers le backend et relaie bidirectionnellement.
        """
        self._total_connections += 1
        self._active_tunnels += 1
        tunnel_id = self._total_connections

        log.info(
            f"[REV-PROXY/{self.protocol}] #{tunnel_id} "
            f"Relai PQC→{self.backend_host}:{self.backend_port} "
            f"pour {client_id}"
        )

        try:
            # Connexion vers le backend interne (non chiffrée sur réseau Docker interne)
            back_reader, back_writer = await asyncio.open_connection(
                self.backend_host, self.backend_port
            )
            log.info(f"[REV-PROXY] #{tunnel_id} Connecté au backend {self.backend_host}:{self.backend_port}")

            # Relai bidirectionnel
            await asyncio.gather(
                self._pipe_pqc_to_backend(channel, pqc_reader, back_writer, tunnel_id),
                self._pipe_backend_to_pqc(back_reader, channel, pqc_writer, tunnel_id),
                return_exceptions=True,
            )

        except ConnectionRefusedError:
            log.error(
                f"[REV-PROXY] #{tunnel_id} Backend {self.backend_host}:{self.backend_port} "
                f"inaccessible — vérifier Docker network"
            )
        except Exception as e:
            log.warning(f"[REV-PROXY] #{tunnel_id} Erreur relai : {e}")
        finally:
            self._active_tunnels -= 1
            log.info(f"[REV-PROXY] #{tunnel_id} Tunnel fermé (tunnels actifs: {self._active_tunnels})")

    async def _pipe_pqc_to_backend(
        self,
        channel,
        pqc_reader: asyncio.StreamReader,
        back_writer: asyncio.StreamWriter,
        tunnel_id: int,
    ):
        """PQC tunnel (chiffré) → Backend (plain)."""
        bytes_forwarded = 0
        try:
            while True:
                # Lire depuis le tunnel PQC chiffré
                header = await pqc_reader.read(4)
                if not header or len(header) < 4:
                    break
                length = struct.unpack(">I", header)[0]
                encrypted = await pqc_reader.readexactly(length)

                # Déchiffrer AES-256-GCM
                plaintext = channel.decrypt(
                    encrypted,
                    associated_data=f"tunnel-{tunnel_id}".encode()
                )

                # Envoyer en clair au backend interne
                back_writer.write(plaintext)
                await back_writer.drain()
                bytes_forwarded += len(plaintext)
                self._total_bytes_decrypted += len(plaintext)

                log.debug(
                    f"[REV-PROXY] PQC→Backend #{tunnel_id}: "
                    f"{len(plaintext)} bytes déchiffrés"
                )

        except Exception as e:
            log.debug(f"[REV-PROXY] PQC→Backend #{tunnel_id} fin : {e}")
        finally:
            back_writer.close()

        log.info(f"[REV-PROXY] #{tunnel_id} PQC→Backend : {bytes_forwarded} bytes déchiffrés")

    async def _pipe_backend_to_pqc(
        self,
        back_reader: asyncio.StreamReader,
        channel,
        pqc_writer: asyncio.StreamWriter,
        tunnel_id: int,
    ):
        """Backend (plain) → PQC tunnel (chiffré)."""
        bytes_forwarded = 0
        try:
            while True:
                data = await back_reader.read(65536)
                if not data:
                    break

                # Chiffrer AES-256-GCM avant d'envoyer vers le forward proxy
                encrypted = channel.encrypt(
                    data,
                    associated_data=f"tunnel-{tunnel_id}".encode()
                )
                pqc_writer.write(struct.pack(">I", len(encrypted)) + encrypted)
                await pqc_writer.drain()
                bytes_forwarded += len(data)

                log.debug(
                    f"[REV-PROXY] Backend→PQC #{tunnel_id}: "
                    f"{len(data)} bytes chiffrés"
                )

        except Exception as e:
            log.debug(f"[REV-PROXY] Backend→PQC #{tunnel_id} fin : {e}")

        log.info(f"[REV-PROXY] #{tunnel_id} Backend→PQC : {bytes_forwarded} bytes chiffrés")

    def stats(self) -> dict:
        return {
            "active_tunnels":        self._active_tunnels,
            "total_connections":     self._total_connections,
            "total_bytes_decrypted": self._total_bytes_decrypted,
            "protocol":              self.protocol,
            "listen":                f"{self.listen_host}:{self.listen_port}",
            "backend":               f"{self.backend_host}:{self.backend_port}",
        }


# ─────────────────────────────────────────────────────────────────
#  Point d'entrée autonome (Docker CMD)
# ─────────────────────────────────────────────────────────────────

async def run_reverse_proxy(
    listen_host: str = "0.0.0.0",
    listen_port: int = 8443,
    backend_host: str = "mosquitto",
    backend_port: int = 1883,
    entity_dir: str = "/app/security/middleware",
    entity_id: str = "middleware",
    ca_dir: str = "/app/security/ca",
    allowlist_path: str = "/app/security/allowlist.json",
    passphrase: bytes = b"changeme-in-production",
    protocol: str = "MQTT",
):
    import sys
    sys.path.insert(0, "/app/security")
    from cert_manager import load_entity_keys, CertificateAuthority, AllowList
    from tls_server import PQCServer
    from session_cache import SessionCache

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    log.info(f"[REV-PROXY] Démarrage — chargement des clés {entity_id}…")
    ca = CertificateAuthority.load(ca_dir, passphrase)
    allowlist = AllowList(ca, allowlist_path)
    cert, kem_sk, sig_sk = load_entity_keys(entity_dir, entity_id, passphrase)

    session_cache = SessionCache()

    pqc_server = PQCServer(
        host=listen_host,
        port=listen_port,
        server_cert=cert,
        server_kem_sk=kem_sk,
        server_sig_sk=sig_sk,
        allowlist=allowlist,
        session_cache=session_cache,
    )

    proxy = ReverseProxy(
        listen_host=listen_host,
        listen_port=listen_port,
        backend_host=backend_host,
        backend_port=backend_port,
        pqc_server=pqc_server,
        protocol=protocol,
    )
    await proxy.start()


if __name__ == "__main__":
    import os
    asyncio.run(run_reverse_proxy(
        listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
        listen_port=int(os.getenv("LISTEN_PORT", "8443")),
        backend_host=os.getenv("BACKEND_HOST", "mosquitto"),
        backend_port=int(os.getenv("BACKEND_PORT", "1883")),
        entity_dir=os.getenv("ENTITY_DIR", "/app/security/middleware"),
        entity_id=os.getenv("ENTITY_ID", "middleware"),
        ca_dir=os.getenv("CA_DIR", "/app/security/ca"),
        allowlist_path=os.getenv("ALLOWLIST_PATH", "/app/security/allowlist.json"),
        passphrase=os.getenv("KEY_PASSPHRASE", "changeme-in-production").encode(),
        protocol=os.getenv("PROTOCOL", "MQTT"),
    ))
