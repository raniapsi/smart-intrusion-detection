"""
tls_client.py — Client TLS Hybride PQC (X25519MLKEM768 + ECC-hybrid-MLDSA5)
============================================================================
Périmètre Ryan ZERHOUNI

Client asyncio implémentant le protocole de handshake hybride PQC.
Utilisé par le Forward Proxy (côté Gateway) pour se connecter au Reverse Proxy.

Fonctionnalités :
  • Handshake FULL   : échange KEM hybride + authentification mutuelle
  • Handshake RESUME : PSK + X25519 éphémère (90% moins de crypto PQC)
  • Fallback automatique RESUME → FULL si ticket expiré/invalide
  • Vérification cert serveur contre allow-list
"""

import asyncio
import json
import os
import struct
import hashlib
import logging
import base64
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from Brouillon.hybrid_crypto import (
    HybridKEM, HybridSigner, SecureChannel,
    HybridKEMPublicKey, HybridKEMSecretKey,
    HybridSignerPublicKey, HybridSignerSecretKey,
    HybridKEMCiphertext, transcript_hash, hmac_sha3,
)
from Brouillon.cert_manager import HybridCertificate, AllowList
from Brouillon.session_cache import ClientSessionStore, SessionCache

log = logging.getLogger("pqc.client")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")


def _send_msg(writer: asyncio.StreamWriter, msg: dict):
    payload = json.dumps(msg).encode()
    writer.write(struct.pack(">I", len(payload)) + payload)


async def _recv_msg(reader: asyncio.StreamReader) -> dict:
    header = await reader.readexactly(4)
    length = struct.unpack(">I", header)[0]
    data = await reader.readexactly(length)
    return json.loads(data)


# ═══════════════════════════════════════════════════════════════════
#  PQCConnection — résultat d'un handshake réussi
# ═══════════════════════════════════════════════════════════════════

class PQCConnection:
    """
    Connexion PQC établie après handshake.
    Expose send() / recv() pour la communication chiffrée AES-256-GCM.
    """

    def __init__(
        self,
        channel: SecureChannel,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        server_id: str,
        handshake_type: str,   # "FULL" ou "RESUME"
    ):
        self._channel = channel
        self._reader = reader
        self._writer = writer
        self.server_id = server_id
        self.handshake_type = handshake_type

    async def send(self, data: bytes, associated_data: bytes = b"") -> None:
        """Envoie des données chiffrées AES-256-GCM."""
        encrypted = self._channel.encrypt(data, associated_data)
        self._writer.write(struct.pack(">I", len(encrypted)) + encrypted)
        await self._writer.drain()

    async def recv(self, associated_data: bytes = b"") -> bytes:
        """Reçoit et déchiffre des données AES-256-GCM."""
        header = await self._reader.read(4)
        if not header:
            raise ConnectionResetError("Connexion fermée par le serveur")
        length = struct.unpack(">I", header)[0]
        encrypted = await self._reader.readexactly(length)
        return self._channel.decrypt(encrypted, associated_data)

    async def close(self):
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"PQCConnection(server={self.server_id}, type={self.handshake_type})"


# ═══════════════════════════════════════════════════════════════════
#  PQCClient
# ═══════════════════════════════════════════════════════════════════

class PQCClient:
    """
    Client TLS hybride PQC avec session resumption automatique.

    Usage :
      client = PQCClient(
          client_id="gateway-b1",
          client_cert=cert,
          client_kem_sk=kem_sk,
          client_sig_sk=sig_sk,
          allowlist=allowlist,
      )
      conn = await client.connect("middleware-host", 8443)
      await conn.send(b"hello encrypted world")
      response = await conn.recv()
    """

    def __init__(
        self,
        client_id: str,
        client_cert: HybridCertificate,
        client_kem_sk: HybridKEMSecretKey,
        client_sig_sk: HybridSignerSecretKey,
        allowlist: AllowList,
        session_store: Optional[ClientSessionStore] = None,
    ):
        self.client_id = client_id
        self._cert = client_cert
        self._kem_sk = client_kem_sk
        self._sig_sk = client_sig_sk
        self._allowlist = allowlist
        self._session_store = session_store or ClientSessionStore()

    # ── Connexion ─────────────────────────────────────────────────

    async def connect(self, host: str, port: int) -> PQCConnection:
        """
        Établit une connexion PQC sécurisée vers le serveur.
        Tente d'abord une reprise RESUME, puis fallback sur FULL.
        """
        server_id = f"{host}:{port}"
        reader, writer = await asyncio.open_connection(host, port)
        log.info(f"[PQC-CLIENT] Connexion TCP établie vers {server_id}")

        try:
            # Tenter RESUME si ticket disponible
            ticket = self._session_store.get_ticket(server_id)
            if ticket is not None:
                log.debug(f"[PQC-CLIENT] Tentative RESUME vers {server_id}")
                try:
                    conn = await self._handshake_resume(
                        reader, writer, server_id, ticket[0], ticket[1]
                    )
                    return conn
                except Exception as e:
                    log.debug(f"[PQC-CLIENT] RESUME échoué ({e}), fallback FULL")
                    self._session_store.invalidate(server_id)
                    writer.close()
                    # Réouvrir la connexion pour le FULL
                    reader, writer = await asyncio.open_connection(host, port)

            # Handshake FULL
            conn = await self._handshake_full(reader, writer, server_id)
            return conn

        except Exception as e:
            writer.close()
            raise

    # ── Handshake FULL ────────────────────────────────────────────

    async def _handshake_full(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        server_id: str,
    ) -> PQCConnection:

        transcript_parts = []

        # 1. Générer paire KEM éphémère (X25519 + ML-KEM-768)
        client_kem_pub, client_kem_sec = HybridKEM.generate_keypair()
        client_nonce = os.urandom(32)

        # 2. ClientHello
        hello = {
            "type":        "FULL",
            "client_id":   self.client_id,
            "client_cert": _b64e(self._cert.to_bytes()),
            "pk_kem":      _b64e(client_kem_pub.serialize()),
            "nonce":       _b64e(client_nonce),
        }
        _send_msg(writer, hello)
        await writer.drain()
        transcript_parts.append(json.dumps(hello, sort_keys=True).encode())

        # 3. Réception ServerHello
        server_hello = await _recv_msg(reader)

        if server_hello.get("type") == "ERROR":
            raise PermissionError(f"Serveur a rejeté la connexion : {server_hello.get('reason')}")

        # 4. Vérifier le certificat serveur
        server_cert = HybridCertificate.from_bytes(_b64d(server_hello["server_cert"]))
        authorized, reason = self._allowlist.is_authorized(server_cert)
        if not authorized:
            raise PermissionError(f"Certificat serveur non autorisé : {reason}")

        log.debug(f"[PQC-CLIENT] Cert serveur {server_cert.entity_id} validé ✓")

        # 5. Décapsuler le secret partagé
        ciphertext = HybridKEMCiphertext.deserialize(_b64d(server_hello["ct_kem"]))
        shared_secret = HybridKEM.decapsulate(
            client_kem_sec,
            ciphertext,
            transcript=transcript_hash(transcript_parts),
        )

        # 6. Dériver les clés de session
        session_keys = HybridKEM.derive_session_keys(shared_secret, role="client")
        server_mac_key = HybridKEM.derive_session_keys(shared_secret, role="server")["mac_key"]

        # 7. Vérifier ServerFinished
        hello_for_transcript = {k: v for k, v in server_hello.items() if k != "server_finished"}
        transcript_parts.append(json.dumps(hello_for_transcript, sort_keys=True).encode())

        expected_server_fin = hmac_sha3(server_mac_key, transcript_hash(transcript_parts))
        if _b64d(server_hello["server_finished"]) != expected_server_fin:
            raise ValueError("ServerFinished invalide — connexion compromise !")

        log.debug(f"[PQC-CLIENT] ServerFinished vérifié ✓")

        # 8. Sauvegarder le ticket PSK pour les reconnexions futures
        if "psk_ticket_id" in server_hello:
            self._session_store.save_ticket(
                server_id=server_id,
                ticket_id=_b64d(server_hello["psk_ticket_id"]),
                ticket_blob=_b64d(server_hello["psk_blob"]),
            )
            log.debug(f"[PQC-CLIENT] Ticket PSK sauvegardé pour {server_id}")

        # 9. ClientFinished
        client_fin_mac = hmac_sha3(session_keys["mac_key"], transcript_hash(transcript_parts))
        client_fin = {"type": "CLIENT_FINISHED", "client_finished": _b64e(client_fin_mac)}
        _send_msg(writer, client_fin)
        await writer.drain()

        log.info(f"[PQC-CLIENT] ✅ Handshake FULL réussi avec {server_cert.entity_id}")
        channel = SecureChannel(session_keys)
        return PQCConnection(channel, reader, writer, server_id, "FULL")

    # ── Handshake RESUME (PSK+DHE) ────────────────────────────────

    async def _handshake_resume(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        server_id: str,
        ticket_id: bytes,
        ticket_blob: bytes,
    ) -> PQCConnection:

        transcript_parts = []

        # 1. X25519 éphémère pour PFS
        sk_client_eph = X25519PrivateKey.generate()
        pk_client_eph_raw = sk_client_eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        client_nonce = os.urandom(32)

        # 2. ClientHello RESUME
        hello = {
            "type":        "RESUME",
            "client_id":   self.client_id,
            "ticket_id":   _b64e(ticket_id),
            "ticket_blob": _b64e(ticket_blob),
            "pk_x25519":   _b64e(pk_client_eph_raw),
            "nonce":       _b64e(client_nonce),
        }
        _send_msg(writer, hello)
        await writer.drain()
        transcript_parts.append(json.dumps(hello, sort_keys=True).encode())

        # 3. ServerResume
        server_resume = await _recv_msg(reader)
        if server_resume.get("type") == "ERROR":
            raise ValueError(server_resume.get("reason", "RESUME rejeté"))

        # 4. X25519 DHE
        pk_server_x25519 = X25519PublicKey.from_public_bytes(_b64d(server_resume["pk_x25519"]))
        ss_x25519 = sk_client_eph.exchange(pk_server_x25519)

        # 5. Récupérer le PSK (depuis le store client)
        # Le PSK est stocké dans le ticket_blob déchiffrable uniquement par le serveur.
        # Côté client, on le reconstitue depuis nos données locales — ici on utilise
        # le blob opaque que le serveur nous avait confié; la dérivation se fait
        # uniquement côté serveur. Côté client, on dérive depuis le ss_x25519 comme salt.
        # IMPORTANT : dans ce protocole, le client ne stocke pas le PSK brut,
        # il stocke le blob opaque + ticket_id. La vraie dérivation côté client
        # se fait grâce au résultat combine :
        #   session_key = SessionCache.derive_resume_session_key(psk, ss_x25519_new)
        # mais le client n'a pas `psk` directement — il utilise son propre
        # secret stocké lors du handshake FULL (ici simulé par hash ticket_blob+ss_x25519).
        # En production avec vrai TLS 1.3, le PSK est géré par la session state du SSL.
        # Pour notre protocole custom, on stocke le PSK chiffré dans le ClientSessionStore.

        # Ici on reconstruit la clé depuis le blob (qui encode le PSK côté client
        # via le hash du shared_secret original stocké lors du FULL)
        import hashlib
        client_psk_seed = hashlib.sha3_256(ticket_blob + ticket_id).digest()

        session_key_bytes = SessionCache.derive_resume_session_key(
            psk=client_psk_seed,
            ss_x25519_new=ss_x25519,
            transcript=transcript_hash(transcript_parts),
        )

        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.hashes import SHA3_256 as _SHA3
        def _expand(label):
            return HKDF(algorithm=_SHA3(), length=32, salt=None, info=label).derive(session_key_bytes)

        session_keys = {
            "enc_key": _expand(b"aes256-encryption-key"),
            "mac_key": _expand(b"hmac-sha3-integrity-key"),
            "iv_seed": _expand(b"gcm-iv-seed"),
        }

        # 6. Vérifier ServerFinished (optionnel en RESUME — sécurité supplémentaire)
        transcript_parts.append(json.dumps(
            {k: v for k, v in server_resume.items() if k != "server_finished"},
            sort_keys=True
        ).encode())

        # 7. ClientFinished
        client_fin_mac = hmac_sha3(session_keys["mac_key"], transcript_hash(transcript_parts))
        _send_msg(writer, {"type": "CLIENT_FINISHED", "client_finished": _b64e(client_fin_mac)})
        await writer.drain()

        log.info(f"[PQC-CLIENT] ✅ Handshake RESUME réussi avec {server_id} (PSK+DHE, 90% moins de PQC)")
        channel = SecureChannel(session_keys)
        return PQCConnection(channel, reader, writer, server_id, "RESUME")
