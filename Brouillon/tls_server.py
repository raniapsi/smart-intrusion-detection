"""
tls_server.py — Serveur TLS Hybride PQC (X25519MLKEM768 + ECC-hybrid-MLDSA5)
=============================================================================
Périmètre Ryan ZERHOUNI

Serveur asyncio implémentant le protocole de handshake hybride PQC.
Utilisé par le Reverse Proxy pour terminer les connexions venant du Gateway.

Protocole handshake FULL :
  C→S  ClientHello  {type=FULL, client_id, client_cert, pk_x25519, pk_mlkem, nonce}
  S→C  ServerHello  {server_cert, pk_x25519, ct_mlkem, nonce, server_finished, psk_ticket_id, psk_blob}
  C→S  ClientFinished {client_finished}
  ══   Canal AES-256-GCM établi

Protocole handshake RESUME (PSK+DHE) :
  C→S  ClientHello  {type=RESUME, client_id, ticket_id, ticket_blob, pk_x25519, nonce}
  S→C  ServerResume {pk_x25519, nonce, server_finished}
  C→S  ClientFinished {client_finished}
  ══   Canal AES-256-GCM établi (PSK + X25519 éphémère)

Authentification mutuelle :
  - Le serveur vérifie le cert client contre l'allow-list
  - Le client vérifie le cert serveur contre l'allow-list
"""

import asyncio
import json
import os
import struct
import hashlib
import logging
import base64
from typing import Callable, Optional, Awaitable

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from Brouillon.hybrid_crypto import (
    HybridKEM, HybridSigner, SecureChannel,
    HybridKEMPublicKey, HybridKEMSecretKey,
    HybridSignerPublicKey, HybridSignerSecretKey,
    HybridSignature, transcript_hash, hmac_sha3,
)
from Brouillon.cert_manager import HybridCertificate, AllowList, CertificateAuthority
from Brouillon.session_cache import SessionCache

log = logging.getLogger("pqc.server")

# ─────────────────────────────────────────────────────────────────
#  Helpers sérialisation
# ─────────────────────────────────────────────────────────────────

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")


def _send_msg(writer: asyncio.StreamWriter, msg: dict):
    """Envoie un message JSON avec préfixe longueur 4 bytes."""
    payload = json.dumps(msg).encode()
    writer.write(struct.pack(">I", len(payload)) + payload)


async def _recv_msg(reader: asyncio.StreamReader) -> dict:
    """Reçoit un message JSON avec préfixe longueur 4 bytes."""
    header = await reader.readexactly(4)
    length = struct.unpack(">I", header)[0]
    if length > 10 * 1024 * 1024:   # sanity: 10 MB max
        raise ValueError(f"Message trop grand : {length} bytes")
    data = await reader.readexactly(length)
    return json.loads(data)


# ═══════════════════════════════════════════════════════════════════
#  PQCServer
# ═══════════════════════════════════════════════════════════════════

class PQCServer:
    """
    Serveur TLS hybride PQC.

    Paramètres :
      host, port         : interface d'écoute
      server_cert        : certificat hybride du serveur
      server_kem_sk      : clé secrète KEM du serveur (X25519 + ML-KEM-768)
      server_sig_sk      : clé secrète signature du serveur
      allowlist          : liste blanche des clients autorisés
      session_cache      : cache PSK pour session resumption
      app_handler        : coroutine(channel, client_id, reader, writer)
                           appelée après handshake réussi
    """

    def __init__(
        self,
        host: str,
        port: int,
        server_cert: HybridCertificate,
        server_kem_sk: HybridKEMSecretKey,
        server_sig_sk: HybridSignerSecretKey,
        allowlist: AllowList,
        session_cache: Optional[SessionCache] = None,
        app_handler: Optional[Callable] = None,
    ):
        self.host = host
        self.port = port
        self._cert = server_cert
        self._kem_sk = server_kem_sk
        self._sig_sk = server_sig_sk
        self._allowlist = allowlist
        self._session_cache = session_cache or SessionCache()
        self._app_handler = app_handler
        self._connections = 0

    # ── Démarrage serveur ─────────────────────────────────────────

    async def start(self):
        server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        addr = server.sockets[0].getsockname()
        log.info(f"[PQC-SERVER] En écoute sur {addr[0]}:{addr[1]}")
        async with server:
            await server.serve_forever()

    # ── Connexion entrante ────────────────────────────────────────

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        peer = writer.get_extra_info("peername")
        conn_id = self._connections
        self._connections += 1
        log.info(f"[PQC-SERVER] Connexion #{conn_id} depuis {peer}")

        try:
            channel, client_id = await self._handshake(reader, writer, conn_id)
            log.info(f"[PQC-SERVER] #{conn_id} Handshake OK — client={client_id}")

            if self._app_handler:
                await self._app_handler(channel, client_id, reader, writer)
            else:
                await self._echo_loop(channel, reader, writer)

        except Exception as e:
            log.warning(f"[PQC-SERVER] #{conn_id} Erreur handshake : {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── Handshake principal ───────────────────────────────────────

    async def _handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        conn_id: int,
    ) -> tuple["SecureChannel", str]:

        transcript_parts = []

        # ── 1. Réception ClientHello ──────────────────────────────
        hello = await _recv_msg(reader)
        transcript_parts.append(json.dumps(hello, sort_keys=True).encode())
        hs_type = hello.get("type", "FULL")

        if hs_type == "RESUME":
            return await self._handshake_resume(hello, reader, writer, transcript_parts, conn_id)

        # ── Handshake FULL ────────────────────────────────────────
        client_id = hello["client_id"]
        log.debug(f"[PQC-SERVER] #{conn_id} ClientHello FULL de {client_id}")

        # 2. Vérifier le certificat client (mTLS)
        client_cert = HybridCertificate.from_bytes(_b64d(hello["client_cert"]))
        authorized, reason = self._allowlist.is_authorized(client_cert)
        if not authorized:
            _send_msg(writer, {"type": "ERROR", "reason": reason})
            await writer.drain()
            raise PermissionError(f"Client non autorisé : {reason}")

        # 3. Récupérer la clé publique KEM client
        client_kem_pub = HybridKEMPublicKey.deserialize(_b64d(hello["pk_kem"]))

        # 4. Encapsuler vers la clé client (X25519MLKEM768)
        client_nonce = _b64d(hello["nonce"])
        server_nonce = os.urandom(32)

        ciphertext, shared_secret = HybridKEM.encapsulate(
            client_kem_pub,
            transcript=transcript_hash(transcript_parts),
        )

        # 5. Extraire ss_mlkem pour le PSK (depuis le ciphertext ML-KEM)
        # Note : on utilise le shared_secret complet comme base du PSK
        # (il contient déjà ss_mlkem via la KDF hybride)
        ticket_id, ticket_blob = self._session_cache.issue_ticket(
            client_id=client_id,
            ss_mlkem=shared_secret,   # shared_secret est déjà dérivé de ss_mlkem
        )

        # 6. Construire ServerHello
        session_keys = HybridKEM.derive_session_keys(shared_secret, role="server")
        server_mac_key = session_keys["mac_key"]

        server_hello = {
            "type":        "SERVER_HELLO",
            "server_cert": _b64e(self._cert.to_bytes()),
            "ct_kem":      _b64e(ciphertext.serialize()),
            "nonce":       _b64e(server_nonce),
            "psk_ticket_id":  _b64e(ticket_id),
            "psk_blob":    _b64e(ticket_blob),
        }
        transcript_parts.append(json.dumps(server_hello, sort_keys=True).encode())

        # Server Finished = HMAC(transcript, server_mac_key)
        server_hello["server_finished"] = _b64e(
            hmac_sha3(server_mac_key, transcript_hash(transcript_parts))
        )

        _send_msg(writer, server_hello)
        await writer.drain()

        # 7. Réception ClientFinished
        client_fin = await _recv_msg(reader)
        transcript_parts.append(json.dumps(
            {k: v for k, v in client_fin.items() if k != "client_finished"},
            sort_keys=True
        ).encode())

        # Vérifier client_finished
        client_mac_key_expected = HybridKEM.derive_session_keys(shared_secret, role="client")["mac_key"]
        expected_fin = hmac_sha3(client_mac_key_expected, transcript_hash(transcript_parts[:-1]))
        if not _b64d(client_fin["client_finished"]) == expected_fin:
            raise ValueError("ClientFinished invalide — handshake avorté")

        log.info(f"[PQC-SERVER] #{conn_id} ✅ Handshake FULL réussi avec {client_id}")
        channel = SecureChannel(session_keys)
        return channel, client_id

    # ── Handshake RESUME (PSK+DHE) ────────────────────────────────

    async def _handshake_resume(
        self,
        hello: dict,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        transcript_parts: list,
        conn_id: int,
    ) -> tuple["SecureChannel", str]:

        client_id = hello["client_id"]
        log.debug(f"[PQC-SERVER] #{conn_id} ClientHello RESUME de {client_id}")

        ticket_id = _b64d(hello["ticket_id"])
        ticket_blob = _b64d(hello["ticket_blob"])

        # 1. Racheter le ticket PSK
        result = self._session_cache.redeem_ticket(ticket_id, ticket_blob)
        if result is None:
            # Ticket invalide → forcer handshake FULL
            _send_msg(writer, {"type": "ERROR", "reason": "ticket_invalid", "fallback": "FULL"})
            await writer.drain()
            raise ValueError("Ticket PSK invalide ou expiré — faire un handshake FULL")

        psk, stored_client_id = result
        if stored_client_id != client_id:
            raise PermissionError(f"Ticket appartient à {stored_client_id}, pas {client_id}")

        # 2. X25519 éphémère (DHE pour PFS)
        pk_client_x25519 = X25519PublicKey.from_public_bytes(_b64d(hello["pk_x25519"]))
        sk_server_eph = X25519PrivateKey.generate()
        pk_server_eph_raw = sk_server_eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ss_x25519 = sk_server_eph.exchange(pk_client_x25519)

        # 3. Dériver la clé de session RESUME : PSK (PQC hérité) + X25519 (PFS)
        server_nonce = os.urandom(32)
        resume_transcript = transcript_hash(transcript_parts)

        from session_cache import SessionCache
        session_key_bytes = SessionCache.derive_resume_session_key(
            psk=psk,
            ss_x25519_new=ss_x25519,
            transcript=resume_transcript,
        )

        # Fabriquer les clés de session depuis la clé unifiée
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.hashes import SHA3_256 as _SHA3
        def _expand(label):
            return HKDF(algorithm=_SHA3(), length=32, salt=None, info=label).derive(session_key_bytes)

        session_keys = {
            "enc_key": _expand(b"aes256-encryption-key"),
            "mac_key": _expand(b"hmac-sha3-integrity-key"),
            "iv_seed": _expand(b"gcm-iv-seed"),
        }
        server_mac_key = session_keys["mac_key"]

        # 4. ServerResume
        server_resume = {
            "type":      "SERVER_RESUME",
            "pk_x25519": _b64e(pk_server_eph_raw),
            "nonce":     _b64e(server_nonce),
        }
        transcript_parts.append(json.dumps(server_resume, sort_keys=True).encode())
        server_resume["server_finished"] = _b64e(
            hmac_sha3(server_mac_key, transcript_hash(transcript_parts))
        )

        _send_msg(writer, server_resume)
        await writer.drain()

        # 5. ClientFinished
        client_fin = await _recv_msg(reader)
        expected_fin = hmac_sha3(
            session_keys["mac_key"],
            transcript_hash(transcript_parts),
        )
        if _b64d(client_fin["client_finished"]) != expected_fin:
            raise ValueError("ClientFinished RESUME invalide")

        log.info(f"[PQC-SERVER] #{conn_id} ✅ Handshake RESUME réussi avec {client_id} (PSK+DHE)")
        return SecureChannel(session_keys), client_id

    # ── Application : boucle echo (démo) ─────────────────────────

    async def _echo_loop(
        self,
        channel: SecureChannel,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Boucle écho de démonstration après handshake."""
        while True:
            header = await reader.read(4)
            if not header:
                break
            length = struct.unpack(">I", header)[0]
            encrypted = await reader.readexactly(length)
            plaintext = channel.decrypt(encrypted)
            response = channel.encrypt(plaintext)
            writer.write(struct.pack(">I", len(response)) + response)
            await writer.drain()
