"""
session_cache.py — Session Resumption Hybride (PSK+DHE)
=======================================================
Périmètre Ryan ZERHOUNI

Implémente la Session Resumption TLS 1.3 en mode hybride PSK+DHE,
comme défini à la §4.2.4 de l'architecture.

Principe :
  • Handshake FULL  : échange X25519MLKEM768 complet → PSK émis, dérivé de ss_mlkem
  • Handshake RESUME: PSK (héritage PQC) + X25519 éphémère (PFS classique)
    → Réduction overhead PQC de 90% sur les reconnexions
    → PFS garantie : vol du ticket → pas de déchiffrement sessions passées/futures
    → Héritage PQC : PSK dérivé du ss_mlkem du handshake initial

Propriété clé :
  "La reprise de session ne perd pas sa sécurité PQC. Le PSK utilisé lors
   de la reprise est directement dérivé du secret partagé établi via ML-KEM-768
   lors du handshake initial." — ARCHITECTURE.md §4.2.4
"""

import os
import json
import time
import struct
import hashlib
import threading
from datetime import datetime, timezone
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA3_256


# ─────────────────────────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────────────────────────

PSK_SIZE            = 32    # bytes — clé pré-partagée (dérivée de ss_mlkem)
TICKET_ID_SIZE      = 16    # bytes — identifiant du ticket
TICKET_LIFETIME_S   = 3600  # 1 heure — durée de vie d'un ticket PSK
TICKET_ENCRYPT_KEY  = b"psk-ticket-encryption-master-key-32b"   # en prod: clé aléatoire au boot


# ═══════════════════════════════════════════════════════════════════
#  PSKTicket — structure d'un ticket de session
# ═══════════════════════════════════════════════════════════════════

class PSKTicket:
    """
    Ticket de session PSK émis après un handshake FULL réussi.

    Contenu (chiffré AES-256-GCM côté serveur) :
      - ticket_id  : 16 bytes aléatoires (identifiant public)
      - psk        : 32 bytes dérivés de ss_mlkem (secret PQC hérité)
      - client_id  : identifiant de l'entité cliente
      - issued_at  : timestamp d'émission
      - expires_at : timestamp d'expiration

    La clé de chiffrement du ticket n'est jamais transmise au client.
    Le client reçoit uniquement le ticket_id + le blob chiffré opaque.
    """

    def __init__(
        self,
        ticket_id: bytes,
        psk: bytes,
        client_id: str,
        issued_at: float,
        expires_at: float,
    ):
        self.ticket_id  = ticket_id
        self.psk        = psk
        self.client_id  = client_id
        self.issued_at  = issued_at
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def __repr__(self) -> str:
        exp = datetime.fromtimestamp(self.expires_at, timezone.utc).isoformat()
        return f"PSKTicket(id={self.ticket_id.hex()[:8]}…, client={self.client_id}, expires={exp})"


# ═══════════════════════════════════════════════════════════════════
#  SessionCache — côté serveur
# ═══════════════════════════════════════════════════════════════════

class SessionCache:
    """
    Cache de sessions PSK côté serveur.
    Thread-safe. Nettoyage automatique des tickets expirés.

    Usage :
      cache = SessionCache()

      # Après handshake FULL réussi :
      ticket_id, blob = cache.issue_ticket(
          client_id="gateway-b1",
          ss_mlkem=shared_secret_mlkem   ← PSK dérivé du secret ML-KEM
      )
      # Envoyer (ticket_id, blob) au client

      # Lors d'une reconnexion (RESUME) :
      psk = cache.redeem_ticket(ticket_id, blob)
      # Combiner psk + nouvel échange X25519 → session_key
    """

    def __init__(self, ticket_lifetime_s: int = TICKET_LIFETIME_S):
        self._tickets: dict[bytes, PSKTicket] = {}   # ticket_id → PSKTicket
        self._lifetime = ticket_lifetime_s
        self._lock = threading.Lock()
        # Clé maître de chiffrement des tickets (en prod : dérivée au boot)
        self._master_key = hashlib.sha3_256(TICKET_ENCRYPT_KEY).digest()

    # ── Émission d'un ticket (après handshake FULL) ───────────────

    def issue_ticket(
        self, client_id: str, ss_mlkem: bytes
    ) -> tuple[bytes, bytes]:
        """
        Émet un ticket PSK dérivé du secret ML-KEM-768.

        Paramètres :
          client_id : identifiant de l'entité cliente
          ss_mlkem  : secret partagé ML-KEM-768 du handshake FULL (32 bytes)

        Retourne :
          ticket_id   : 16 bytes (envoyé au client comme identifiant)
          ticket_blob : blob chiffré opaque (envoyé au client pour présenter lors de RESUME)
        """
        # PSK = HKDF(ss_mlkem, info="psk-session-resumption")
        # Hérite de la sécurité PQC de ML-KEM-768
        psk = HKDF(
            algorithm=SHA3_256(), length=PSK_SIZE, salt=None,
            info=b"psk-session-resumption"
        ).derive(ss_mlkem)

        ticket_id = os.urandom(TICKET_ID_SIZE)
        now = time.time()

        ticket = PSKTicket(
            ticket_id=ticket_id,
            psk=psk,
            client_id=client_id,
            issued_at=now,
            expires_at=now + self._lifetime,
        )

        # Stocker en mémoire
        with self._lock:
            self._tickets[ticket_id] = ticket
            self._cleanup_expired_locked()

        # Chiffrer pour le client (blob opaque)
        blob = self._encrypt_ticket(ticket)

        return ticket_id, blob

    # ── Rédemption (lors de la reconnexion RESUME) ────────────────

    def redeem_ticket(
        self, ticket_id: bytes, ticket_blob: bytes
    ) -> Optional[tuple[bytes, str]]:
        """
        Valide et rachète un ticket PSK lors d'une reprise de session.

        Retourne (psk, client_id) si valide, None sinon.

        Sécurité :
          - Le ticket est supprimé après usage (anti-replay)
          - Vérifie l'intégrité du blob (AES-256-GCM)
          - Vérifie l'expiration
        """
        # 1. Déchiffrer le blob pour récupérer le PSK original
        ticket = self._decrypt_ticket(ticket_blob)
        if ticket is None:
            return None

        # 2. Vérifier que le ticket_id correspond
        if ticket.ticket_id != ticket_id:
            return None

        # 3. Vérifier expiration
        if ticket.is_expired():
            with self._lock:
                self._tickets.pop(ticket_id, None)
            return None

        # 4. Supprimer le ticket (one-time use — anti-replay)
        with self._lock:
            stored = self._tickets.pop(ticket_id, None)
            if stored is None:
                return None   # déjà utilisé ou inconnu

        return ticket.psk, ticket.client_id

    # ── Dérivation clé de session RESUME (PSK + X25519 éphémère) ──

    @staticmethod
    def derive_resume_session_key(
        psk: bytes,
        ss_x25519_new: bytes,
        transcript: bytes = b"",
    ) -> bytes:
        """
        Dérive la clé de session pour une reprise PSK+DHE.

        Propriétés :
          • PQC inherited : psk dérivé de ss_mlkem du handshake initial
          • PFS classique : ss_x25519_new est éphémère → sessions indépendantes
          • Binding       : transcript lie la clé au contexte du handshake RESUME
        """
        # Combinaison : PSK (PQC hérité) + X25519 éphémère (PFS)
        ikm = psk + ss_x25519_new
        salt = hashlib.sha3_256(transcript).digest() if transcript else os.urandom(32)
        return HKDF(
            algorithm=SHA3_256(),
            length=32,
            salt=salt,
            info=b"psk-dhe-resume-session-key",
        ).derive(ikm)

    # ── Gestion interne tickets ────────────────────────────────────

    def _encrypt_ticket(self, ticket: PSKTicket) -> bytes:
        """Chiffre un ticket PSK en blob opaque (AES-256-GCM)."""
        payload = json.dumps({
            "ticket_id":  ticket.ticket_id.hex(),
            "psk":        ticket.psk.hex(),
            "client_id":  ticket.client_id,
            "issued_at":  ticket.issued_at,
            "expires_at": ticket.expires_at,
        }).encode()

        nonce = os.urandom(12)
        ct = AESGCM(self._master_key).encrypt(nonce, payload, None)
        return nonce + ct

    def _decrypt_ticket(self, blob: bytes) -> Optional[PSKTicket]:
        """Déchiffre et reconstruit un PSKTicket depuis un blob opaque."""
        try:
            nonce, ct = blob[:12], blob[12:]
            payload = AESGCM(self._master_key).decrypt(nonce, ct, None)
            d = json.loads(payload)
            return PSKTicket(
                ticket_id=bytes.fromhex(d["ticket_id"]),
                psk=bytes.fromhex(d["psk"]),
                client_id=d["client_id"],
                issued_at=d["issued_at"],
                expires_at=d["expires_at"],
            )
        except Exception:
            return None

    def _cleanup_expired_locked(self):
        """Supprime les tickets expirés (appelé sous lock)."""
        expired = [tid for tid, t in self._tickets.items() if t.is_expired()]
        for tid in expired:
            del self._tickets[tid]

    def stats(self) -> dict:
        with self._lock:
            self._cleanup_expired_locked()
            return {
                "active_tickets": len(self._tickets),
                "ticket_lifetime_s": self._lifetime,
            }


# ═══════════════════════════════════════════════════════════════════
#  ClientSessionStore — côté client
# ═══════════════════════════════════════════════════════════════════

class ClientSessionStore:
    """
    Stockage côté client des tickets PSK reçus du serveur.
    Permet de réutiliser les tickets pour les reconnexions (RESUME).
    """

    def __init__(self):
        self._sessions: dict[str, dict] = {}   # server_id → {ticket_id, ticket_blob}

    def save_ticket(self, server_id: str, ticket_id: bytes, ticket_blob: bytes):
        """Sauvegarde un ticket PSK reçu du serveur après handshake FULL."""
        self._sessions[server_id] = {
            "ticket_id":   ticket_id,
            "ticket_blob": ticket_blob,
            "saved_at":    time.time(),
        }

    def get_ticket(self, server_id: str) -> Optional[tuple[bytes, bytes]]:
        """
        Récupère le ticket PSK pour un serveur donné.
        Retourne (ticket_id, ticket_blob) ou None si pas de session disponible.
        """
        sess = self._sessions.get(server_id)
        if sess is None:
            return None
        # Purger si trop vieux (conservatif : retirer après TICKET_LIFETIME_S)
        if time.time() - sess["saved_at"] > TICKET_LIFETIME_S:
            del self._sessions[server_id]
            return None
        return sess["ticket_id"], sess["ticket_blob"]

    def invalidate(self, server_id: str):
        """Invalide le ticket pour un serveur (après échec RESUME ou révocation)."""
        self._sessions.pop(server_id, None)
