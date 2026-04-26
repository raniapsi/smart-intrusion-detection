"""
log_signer.py — Signature Hybride des Logs (ECC-hybrid-MLDSA5)
==============================================================
Périmètre Ryan ZERHOUNI

Chaque entrée de log est signée avec la signature hybride ECC-hybrid-MLDSA5 :
  sig_final = (sig_ECDSA_P384 ‖ sig_MLDSA65)

Toute modification du log est détectable, même par un adversaire quantique futur.
Garantie légale : 15 ans (justifiée par ML-DSA niveau 5 — §4.2, §4.3 de l'architecture).

Format d'un log signé :
  {
    "log_id":    "uuid-v4",
    "timestamp": "ISO8601",
    "event_id":  "uuid-v4",          ← lien vers la table events TimescaleDB
    "source":    "MIDDLEWARE | AI | GATEWAY",
    "level":     "INFO | WARNING | ALERT | CRITICAL",
    "message":   "...",
    "payload":   { ... },             ← données brutes de l'événement
    "signer_id": "gateway-b1",        ← entité qui a signé
    "signature": "<base64>",          ← HybridSignature sérialisée
    "chain_hash": "<sha3-256 hex>",   ← SHA3(prev_chain_hash + log_id) — chaîne d'intégrité
  }
"""

import uuid
import json
import hashlib
import base64
from datetime import datetime, timezone
from typing import Optional

from Brouillon.hybrid_crypto import (
    HybridSigner, HybridSignerPublicKey, HybridSignerSecretKey, HybridSignature,
)


def _b64enc(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()

def _b64dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")


# ═══════════════════════════════════════════════════════════════════
#  SignedLogEntry
# ═══════════════════════════════════════════════════════════════════

class SignedLogEntry:
    """
    Entrée de log signée par signature hybride ECC-hybrid-MLDSA5.
    La signature couvre tous les champs sauf 'signature' lui-même.
    """

    def __init__(self, entry_dict: dict):
        self._d = entry_dict

    @property
    def log_id(self) -> str:
        return self._d["log_id"]

    @property
    def timestamp(self) -> str:
        return self._d["timestamp"]

    @property
    def event_id(self) -> str:
        return self._d["event_id"]

    @property
    def level(self) -> str:
        return self._d["level"]

    @property
    def message(self) -> str:
        return self._d["message"]

    @property
    def chain_hash(self) -> str:
        return self._d["chain_hash"]

    def to_dict(self) -> dict:
        return self._d.copy()

    def to_bytes(self) -> bytes:
        return json.dumps(self._d, sort_keys=True).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "SignedLogEntry":
        return cls(json.loads(data))

    def _signing_payload(self) -> bytes:
        """Payload canonique : tout sauf le champ 'signature'."""
        d = {k: v for k, v in self._d.items() if k != "signature"}
        return json.dumps(d, sort_keys=True).encode()


# ═══════════════════════════════════════════════════════════════════
#  LogSigner
# ═══════════════════════════════════════════════════════════════════

class LogSigner:
    """
    Signataire de logs avec chaîne d'intégrité.

    La chaîne_hash lie chaque log au précédent (comme une blockchain légère).
    Pour falsifier un log au milieu de la chaîne, l'attaquant devrait
    recalculer tous les hash ET les signatures hybrides suivants → impossible.
    """

    def __init__(
        self,
        signer_id: str,
        sig_secret_key: HybridSignerSecretKey,
        genesis_hash: str = "0" * 64,
    ):
        """
        signer_id      : identifiant de l'entité signataire (ex: "middleware")
        sig_secret_key : clé secrète hybride (ECDSA P-384 + ML-DSA-65)
        genesis_hash   : hash de départ de la chaîne (SHA3-256 de 32 zéros par défaut)
        """
        self.signer_id = signer_id
        self._sk = sig_secret_key
        self._last_chain_hash = genesis_hash

    # ── Signature ─────────────────────────────────────────────────

    def sign_event(
        self,
        event_id: str,
        source: str,
        level: str,
        message: str,
        payload: dict,
    ) -> SignedLogEntry:
        """
        Crée et signe une entrée de log pour un événement IoT.

        Paramètres :
          event_id : UUID de l'événement dans TimescaleDB
          source   : "MIDDLEWARE" | "AI" | "GATEWAY"
          level    : "INFO" | "WARNING" | "ALERT" | "CRITICAL"
          message  : description humaine de l'événement
          payload  : données brutes (badge_id, door_state, ai_score, …)
        """
        log_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Chaîne d'intégrité : SHA3(prev_chain_hash ‖ log_id ‖ event_id)
        chain_hash = hashlib.sha3_256(
            (self._last_chain_hash + log_id + event_id).encode()
        ).hexdigest()

        entry_dict = {
            "log_id":     log_id,
            "timestamp":  timestamp,
            "event_id":   event_id,
            "source":     source,
            "level":      level,
            "message":    message,
            "payload":    payload,
            "signer_id":  self.signer_id,
            "chain_hash": chain_hash,
            "signature":  None,   # rempli après
        }

        # Signature hybride du payload canonique
        payload_bytes = json.dumps(
            {k: v for k, v in entry_dict.items() if k != "signature"},
            sort_keys=True
        ).encode()
        sig = HybridSigner.sign(self._sk, payload_bytes)
        entry_dict["signature"] = _b64enc(sig.serialize())

        # Avancer la chaîne
        self._last_chain_hash = chain_hash

        return SignedLogEntry(entry_dict)

    # ── Méthodes de commodité ─────────────────────────────────────

    def info(self, event_id: str, message: str, payload: dict = None) -> SignedLogEntry:
        return self.sign_event(event_id, "MIDDLEWARE", "INFO", message, payload or {})

    def warning(self, event_id: str, message: str, payload: dict = None) -> SignedLogEntry:
        return self.sign_event(event_id, "MIDDLEWARE", "WARNING", message, payload or {})

    def alert(self, event_id: str, message: str, payload: dict = None) -> SignedLogEntry:
        return self.sign_event(event_id, "MIDDLEWARE", "ALERT", message, payload or {})

    def critical(self, event_id: str, message: str, payload: dict = None) -> SignedLogEntry:
        return self.sign_event(event_id, "AI", "CRITICAL", message, payload or {})


# ═══════════════════════════════════════════════════════════════════
#  LogVerifier
# ═══════════════════════════════════════════════════════════════════

class LogVerifier:
    """
    Vérifie l'intégrité d'une séquence de logs signés.
    Usage : investigation légale, audit SOC, export judiciaire.
    """

    def __init__(
        self,
        signer_pub_key: HybridSignerPublicKey,
        genesis_hash: str = "0" * 64,
    ):
        self._pk = signer_pub_key
        self._genesis_hash = genesis_hash

    def verify_entry(self, entry: SignedLogEntry) -> tuple[bool, str]:
        """
        Vérifie la signature hybride d'une entrée de log.
        Retourne (valid: bool, reason: str).
        """
        # Recontruire le payload signable
        payload = entry._signing_payload()

        # Désérialiser la signature
        try:
            sig = HybridSignature.deserialize(_b64dec(entry._d["signature"]))
        except Exception as e:
            return False, f"Signature mal formée : {e}"

        # Vérifier la signature hybride
        if not HybridSigner.verify(self._pk, payload, sig):
            return False, "Signature hybride invalide (ECDSA ou ML-DSA échoué)"

        return True, "OK"

    def verify_chain(self, entries: list[SignedLogEntry]) -> tuple[bool, list[dict]]:
        """
        Vérifie l'intégrité d'une séquence de logs (chaîne d'intégrité).

        Retourne :
          (all_valid: bool, report: list[{log_id, sig_ok, chain_ok, details}])
        """
        report = []
        all_valid = True
        prev_chain_hash = self._genesis_hash

        for entry in entries:
            sig_ok, sig_reason = self.verify_entry(entry)

            # Vérifier la chaîne
            expected_chain = hashlib.sha3_256(
                (prev_chain_hash + entry.log_id + entry.event_id).encode()
            ).hexdigest()
            chain_ok = entry.chain_hash == expected_chain

            if not sig_ok or not chain_ok:
                all_valid = False

            report.append({
                "log_id":      entry.log_id,
                "timestamp":   entry.timestamp,
                "level":       entry.level,
                "sig_valid":   sig_ok,
                "chain_valid": chain_ok,
                "details":     sig_reason if not sig_ok else ("chain mismatch" if not chain_ok else "OK"),
            })

            prev_chain_hash = entry.chain_hash

        return all_valid, report

    def export_audit_report(self, entries: list[SignedLogEntry], output_path: str) -> bool:
        """
        Génère un rapport d'audit JSON pour investigation légale.
        Retourne True si tous les logs sont valides.
        """
        all_valid, report = self.verify_chain(entries)

        audit = {
            "audit_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_entries": len(entries),
            "all_valid": all_valid,
            "invalid_count": sum(1 for r in report if not r["sig_valid"] or not r["chain_valid"]),
            "entries": report,
        }

        with open(output_path, "w") as f:
            json.dump(audit, f, indent=2)

        status = "✅ INTÈGRE" if all_valid else "❌ ALTÉRATIONS DÉTECTÉES"
        print(f"  [AUDIT] {status} — {len(entries)} logs vérifiés → {output_path}")
        return all_valid
