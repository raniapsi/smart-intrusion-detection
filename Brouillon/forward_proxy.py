"""
proxy/forward_proxy.py — Forward Proxy PQC (Côté Gateway)
===========================================================
Périmètre Ryan ZERHOUNI — Architecture §4.4 Double Tunnel Proxy

Rôle :
  Intercepte les flux MQTT/HTTP locaux du simulateur et les encapsule
  dans le tunnel TLS/PQC (X25519MLKEM768) vers le Reverse Proxy.

Architecture réseau :
  [Simulateur]  →(MQTT plain)→  [Forward Proxy]  →(TLS PQC)→  [Reverse Proxy]  →(MQTT plain)→  [Mosquitto]

Avantage "agnosticisme applicatif" :
  Les applications (simulateur, Node-RED) n'ont pas besoin de supporter
  nativement les bibliothèques PQC. Elles communiquent en clair sur des
  interfaces locales Docker sécurisées. Le proxy est l'unique point PQC.

Configuration Docker :
  - Le simulateur envoie vers localhost:1883 (forward proxy local)
  - Le forward proxy encapsule en PQC et envoie vers reverse-proxy:8443
  - Réseau Docker iot-net (internal: true) → simulateur ne peut pas atteindre l'extérieur
"""

import asyncio
import logging
import struct
import json
import os
import base64
from typing import Optional

log = logging.getLogger("pqc.forward-proxy")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")


class ForwardProxy:
    """
    Forward Proxy PQC — Côté Gateway (Edge).

    Écoute les connexions locales non-chiffrées (MQTT/HTTP) et les relaie
    via un tunnel TLS hybride PQC vers le Reverse Proxy cible.

    Paramètres :
      listen_host/port   : interface locale (ex: 0.0.0.0:1883 pour MQTT)
      target_host/port   : reverse proxy distant (ex: reverse-proxy:8443)
      pqc_client         : instance PQCClient configurée avec les clés gateway
      protocol           : "MQTT" | "HTTP" (pour le logging)
    """

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        target_host: str,
        target_port: int,
        pqc_client,          # PQCClient — évite import circulaire
        protocol: str = "MQTT",
    ):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self._pqc_client = pqc_client
        self.protocol = protocol
        self._active_tunnels = 0

    async def start(self):
        """Démarre le forward proxy."""
        server = await asyncio.start_server(
            self._handle_local_connection,
            self.listen_host, self.listen_port,
        )
        addr = server.sockets[0].getsockname()
        log.info(
            f"[FWD-PROXY/{self.protocol}] En écoute sur {addr[0]}:{addr[1]} "
            f"→ PQC tunnel vers {self.target_host}:{self.target_port}"
        )
        async with server:
            await server.serve_forever()

    async def _handle_local_connection(
        self,
        local_reader: asyncio.StreamReader,
        local_writer: asyncio.StreamWriter,
    ):
        """
        Gère une connexion locale (simulateur/gateway) :
        1. Établit le tunnel PQC vers le reverse proxy
        2. Relaie les données des deux côtés
        """
        peer = local_writer.get_extra_info("peername")
        self._active_tunnels += 1
        tunnel_id = self._active_tunnels
        log.info(f"[FWD-PROXY] Tunnel #{tunnel_id} depuis {peer}")

        try:
            # Établir la connexion PQC sécurisée vers le reverse proxy
            pqc_conn = await self._pqc_client.connect(self.target_host, self.target_port)
            log.info(
                f"[FWD-PROXY] Tunnel #{tunnel_id} PQC établi "
                f"({pqc_conn.handshake_type}) ✓"
            )

            # Relai bidirectionnel
            await asyncio.gather(
                self._pipe_local_to_pqc(local_reader, pqc_conn, tunnel_id),
                self._pipe_pqc_to_local(pqc_conn, local_writer, tunnel_id),
                return_exceptions=True,
            )

        except Exception as e:
            log.warning(f"[FWD-PROXY] Tunnel #{tunnel_id} erreur : {e}")
        finally:
            local_writer.close()
            try:
                await local_writer.wait_closed()
            except Exception:
                pass
            log.info(f"[FWD-PROXY] Tunnel #{tunnel_id} fermé")

    async def _pipe_local_to_pqc(
        self,
        local_reader: asyncio.StreamReader,
        pqc_conn,
        tunnel_id: int,
    ):
        """Local (plain) → PQC tunnel (chiffré AES-256-GCM)."""
        bytes_forwarded = 0
        try:
            while True:
                # Lire par chunks (adapté MQTT/HTTP)
                data = await local_reader.read(65536)
                if not data:
                    break
                # Chiffrer et envoyer via le tunnel PQC
                await pqc_conn.send(
                    data,
                    associated_data=f"tunnel-{tunnel_id}".encode()
                )
                bytes_forwarded += len(data)
                log.debug(f"[FWD-PROXY] →PQC #{tunnel_id}: {len(data)} bytes")
        except Exception as e:
            log.debug(f"[FWD-PROXY] →PQC #{tunnel_id} fin : {e}")
        finally:
            await pqc_conn.close()
        log.info(f"[FWD-PROXY] #{tunnel_id} Local→PQC : {bytes_forwarded} bytes transférés")

    async def _pipe_pqc_to_local(
        self,
        pqc_conn,
        local_writer: asyncio.StreamWriter,
        tunnel_id: int,
    ):
        """PQC tunnel (chiffré) → Local (plain)."""
        bytes_forwarded = 0
        try:
            while True:
                data = await pqc_conn.recv(
                    associated_data=f"tunnel-{tunnel_id}".encode()
                )
                local_writer.write(data)
                await local_writer.drain()
                bytes_forwarded += len(data)
                log.debug(f"[FWD-PROXY] PQC→ #{tunnel_id}: {len(data)} bytes")
        except Exception as e:
            log.debug(f"[FWD-PROXY] PQC→ #{tunnel_id} fin : {e}")
        finally:
            local_writer.close()
        log.info(f"[FWD-PROXY] #{tunnel_id} PQC→Local : {bytes_forwarded} bytes transférés")

    def stats(self) -> dict:
        return {
            "active_tunnels": self._active_tunnels,
            "protocol": self.protocol,
            "listen": f"{self.listen_host}:{self.listen_port}",
            "target": f"{self.target_host}:{self.target_port}",
        }


# ─────────────────────────────────────────────────────────────────
#  Point d'entrée autonome (pour test ou Docker CMD)
# ─────────────────────────────────────────────────────────────────

async def run_forward_proxy(
    listen_host: str = "0.0.0.0",
    listen_port: int = 1883,
    target_host: str = "reverse-proxy",
    target_port: int = 8443,
    entity_dir: str = "/app/security/gateway",
    entity_id: str = "gateway-b1",
    ca_dir: str = "/app/security/ca",
    allowlist_path: str = "/app/security/allowlist.json",
    passphrase: bytes = b"changeme-in-production",
    protocol: str = "MQTT",
):
    """
    Lance le forward proxy en mode autonome (usage Docker).
    Charge les clés depuis les fichiers et démarre l'écoute.
    """
    import sys
    sys.path.insert(0, "/app/security")
    from cert_manager import load_entity_keys, CertificateAuthority, AllowList
    from tls_client import PQCClient

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    log.info(f"[FWD-PROXY] Démarrage — chargement des clés {entity_id}…")
    ca = CertificateAuthority.load(ca_dir, passphrase)
    allowlist = AllowList(ca, allowlist_path)
    cert, kem_sk, sig_sk = load_entity_keys(entity_dir, entity_id, passphrase)

    pqc_client = PQCClient(
        client_id=entity_id,
        client_cert=cert,
        client_kem_sk=kem_sk,
        client_sig_sk=sig_sk,
        allowlist=allowlist,
    )

    proxy = ForwardProxy(
        listen_host=listen_host,
        listen_port=listen_port,
        target_host=target_host,
        target_port=target_port,
        pqc_client=pqc_client,
        protocol=protocol,
    )
    await proxy.start()


if __name__ == "__main__":
    import os
    asyncio.run(run_forward_proxy(
        listen_host=os.getenv("LISTEN_HOST", "0.0.0.0"),
        listen_port=int(os.getenv("LISTEN_PORT", "1883")),
        target_host=os.getenv("TARGET_HOST", "reverse-proxy"),
        target_port=int(os.getenv("TARGET_PORT", "8443")),
        entity_dir=os.getenv("ENTITY_DIR", "/app/security/gateway"),
        entity_id=os.getenv("ENTITY_ID", "gateway-b1"),
        ca_dir=os.getenv("CA_DIR", "/app/security/ca"),
        allowlist_path=os.getenv("ALLOWLIST_PATH", "/app/security/allowlist.json"),
        passphrase=os.getenv("KEY_PASSPHRASE", "changeme-in-production").encode(),
        protocol=os.getenv("PROTOCOL", "MQTT"),
    ))
