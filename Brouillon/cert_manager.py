"""
cert_manager.py — Gestion des Certificats Hybrides (mTLS sans PKI)
===================================================================
Périmètre Ryan ZERHOUNI

Implémente un système de certificats auto-signé hybride (ECC-hybrid-MLDSA5)
sans PKI centrale. L'authentification mutuelle repose sur une allow-list de
certificats autorisés, mise à jour manuellement ou par script de provisionnement.

Structure d'un certificat hybride :
  {
    "version": 1,
    "entity_id": "gateway-b1" | "middleware" | "ca",
    "entity_type": "CA" | "GATEWAY" | "MIDDLEWARE",
    "not_before": "ISO8601",
    "not_after":  "ISO8601",
    "public_keys": {
      "kem_hybrid":  "<base64>",   ← HybridKEMPublicKey (X25519 + ML-KEM-768)
      "sig_hybrid":  "<base64>",   ← HybridSignerPublicKey (ECDSA P-384 + ML-DSA-65)
    },
    "fingerprint": "<sha3-256 hex>",
    "issuer_id": "ca",
    "signature": "<base64 HybridSignature>",  ← signé par la CA
  }
"""

import os
import json
import base64
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from Brouillon.hybrid_crypto import (
    HybridKEM, HybridSigner,
    HybridKEMPublicKey, HybridKEMSecretKey,
    HybridSignerPublicKey, HybridSignerSecretKey,
    HybridSignature,
)


# ─────────────────────────────────────────────────────────────────
#  Sérialisation base64 (URL-safe, sans padding pour JSON propre)
# ─────────────────────────────────────────────────────────────────

def _b64enc(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()

def _b64dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")   # padding tolérant


# ═══════════════════════════════════════════════════════════════════
#  HybridCertificate
# ═══════════════════════════════════════════════════════════════════

class HybridCertificate:
    """
    Certificat d'identité hybride pour une entité du système IoT/IA.
    Contient les deux clés publiques (KEM + signature) signées par la CA.
    """

    def __init__(self, cert_dict: dict):
        self._d = cert_dict

    # ── Accesseurs ────────────────────────────────────────────────

    @property
    def entity_id(self) -> str:
        return self._d["entity_id"]

    @property
    def entity_type(self) -> str:
        return self._d["entity_type"]

    @property
    def fingerprint(self) -> str:
        return self._d["fingerprint"]

    @property
    def kem_public_key(self) -> HybridKEMPublicKey:
        return HybridKEMPublicKey.deserialize(_b64dec(self._d["public_keys"]["kem_hybrid"]))

    @property
    def sig_public_key(self) -> HybridSignerPublicKey:
        return HybridSignerPublicKey.deserialize(_b64dec(self._d["public_keys"]["sig_hybrid"]))

    @property
    def not_after(self) -> datetime:
        return datetime.fromisoformat(self._d["not_after"])

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.not_after

    # ── Sérialisation ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        return self._d.copy()

    def to_bytes(self) -> bytes:
        return json.dumps(self._d, sort_keys=True).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "HybridCertificate":
        return cls(json.loads(data))

    @classmethod
    def from_file(cls, path: str | Path) -> "HybridCertificate":
        return cls(json.loads(Path(path).read_text()))

    def save(self, path: str | Path):
        Path(path).write_text(json.dumps(self._d, indent=2))

    # ── Fingerprint ───────────────────────────────────────────────

    @staticmethod
    def compute_fingerprint(entity_id: str, kem_pk: bytes, sig_pk: bytes) -> str:
        """SHA3-256 des clés publiques → identifiant unique du certificat."""
        h = hashlib.sha3_256()
        h.update(entity_id.encode())
        h.update(kem_pk)
        h.update(sig_pk)
        return h.hexdigest()

    # ── Corps signable (sans la signature elle-même) ──────────────

    def _signing_payload(self) -> bytes:
        """Payload canonique signé par la CA (sans le champ 'signature')."""
        d = {k: v for k, v in self._d.items() if k != "signature"}
        return json.dumps(d, sort_keys=True).encode()


# ═══════════════════════════════════════════════════════════════════
#  CertificateAuthority
# ═══════════════════════════════════════════════════════════════════

class CertificateAuthority:
    """
    Autorité de certification racine hybride.
    Génère et signe les certificats des entités (gateway, middleware).
    Les clés CA sont stockées chiffrées (AES-256) dans ca/ca.key.enc
    """

    def __init__(
        self,
        ca_cert: HybridCertificate,
        ca_sig_secret: HybridSignerSecretKey,
    ):
        self.cert = ca_cert
        self._sk = ca_sig_secret

    # ── Génération ────────────────────────────────────────────────

    @classmethod
    def generate(cls, ca_id: str = "ca-root") -> "CertificateAuthority":
        """Génère une nouvelle CA racine (KEM + signer hybrides)."""
        kem_pub, _kem_sec = HybridKEM.generate_keypair()   # pour la CA: KEM pas utilisé en pratique
        sig_pub, sig_sec = HybridSigner.generate_keypair()

        now = datetime.now(timezone.utc)
        not_after = now + timedelta(days=365 * 10)   # CA valide 10 ans

        kem_pk_bytes = kem_pub.serialize()
        sig_pk_bytes = sig_pub.serialize()
        fingerprint = HybridCertificate.compute_fingerprint(ca_id, kem_pk_bytes, sig_pk_bytes)

        cert_dict = {
            "version": 1,
            "entity_id": ca_id,
            "entity_type": "CA",
            "not_before": now.isoformat(),
            "not_after": not_after.isoformat(),
            "public_keys": {
                "kem_hybrid": _b64enc(kem_pk_bytes),
                "sig_hybrid": _b64enc(sig_pk_bytes),
            },
            "fingerprint": fingerprint,
            "issuer_id": ca_id,   # auto-signé
            "signature": None,    # rempli après
        }

        # Auto-signe
        payload = json.dumps(
            {k: v for k, v in cert_dict.items() if k != "signature"},
            sort_keys=True
        ).encode()
        sig = HybridSigner.sign(sig_sec, payload)
        cert_dict["signature"] = _b64enc(sig.serialize())

        ca_cert = HybridCertificate(cert_dict)
        return cls(ca_cert=ca_cert, ca_sig_secret=sig_sec)

    def issue(
        self,
        entity_id: str,
        entity_type: str,
        validity_days: int = 365,
    ) -> tuple[HybridCertificate, HybridKEMSecretKey, HybridSignerSecretKey]:
        """
        Émet un certificat pour une entité (gateway, middleware).
        Retourne : (cert, kem_secret_key, sig_secret_key)
        """
        kem_pub, kem_sec = HybridKEM.generate_keypair()
        sig_pub, sig_sec = HybridSigner.generate_keypair()

        now = datetime.now(timezone.utc)
        not_after = now + timedelta(days=validity_days)

        kem_pk_bytes = kem_pub.serialize()
        sig_pk_bytes = sig_pub.serialize()
        fingerprint = HybridCertificate.compute_fingerprint(entity_id, kem_pk_bytes, sig_pk_bytes)

        cert_dict = {
            "version": 1,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "not_before": now.isoformat(),
            "not_after": not_after.isoformat(),
            "public_keys": {
                "kem_hybrid": _b64enc(kem_pk_bytes),
                "sig_hybrid": _b64enc(sig_pk_bytes),
            },
            "fingerprint": fingerprint,
            "issuer_id": self.cert.entity_id,
            "signature": None,
        }

        # Signe avec la clé de la CA
        payload = json.dumps(
            {k: v for k, v in cert_dict.items() if k != "signature"},
            sort_keys=True
        ).encode()
        sig = HybridSigner.sign(self._sk, payload)
        cert_dict["signature"] = _b64enc(sig.serialize())

        cert = HybridCertificate(cert_dict)
        return cert, kem_sec, sig_sec

    def verify_cert(self, cert: HybridCertificate) -> bool:
        """
        Vérifie qu'un certificat a bien été signé par cette CA.
        Utilise la signature hybride (ECDSA P-384 + ML-DSA-65).
        """
        payload = cert._signing_payload()
        sig_bytes = _b64dec(cert._d["signature"])
        sig = HybridSignature.deserialize(sig_bytes)
        ca_sig_pub = self.cert.sig_public_key
        return HybridSigner.verify(ca_sig_pub, payload, sig)

    # ── Persistance CA ────────────────────────────────────────────

    def save(self, ca_dir: str | Path, passphrase: bytes):
        """Sauvegarde la CA : certificat (public) + clé secrète (chiffrée AES-256)."""
        ca_dir = Path(ca_dir)
        ca_dir.mkdir(parents=True, exist_ok=True)
        self.cert.save(ca_dir / "ca.crt")
        enc_key = self._sk.serialize_encrypted(passphrase)
        (ca_dir / "ca.key.enc").write_bytes(enc_key)
        (ca_dir / "ca.key.enc").chmod(0o600)
        print(f"  [CA] Sauvegardé dans {ca_dir} (clé chiffrée AES-256)")

    @classmethod
    def load(cls, ca_dir: str | Path, passphrase: bytes) -> "CertificateAuthority":
        """Charge une CA depuis le disque (déchiffre la clé secrète)."""
        ca_dir = Path(ca_dir)
        ca_cert = HybridCertificate.from_file(ca_dir / "ca.crt")
        enc_data = (ca_dir / "ca.key.enc").read_bytes()
        sig_sec = HybridSignerSecretKey.deserialize_encrypted(enc_data, passphrase)
        return cls(ca_cert=ca_cert, ca_sig_secret=sig_sec)


# ═══════════════════════════════════════════════════════════════════
#  AllowList — mTLS sans PKI
# ═══════════════════════════════════════════════════════════════════

class AllowList:
    """
    Liste blanche des certificats autorisés à se connecter (mTLS sans PKI).

    À la différence d'une PKI classique où toute entité signée par la CA est
    acceptée automatiquement, l'allow-list exige une inscription explicite de
    chaque fingerprint. Révocation instantanée par suppression de l'entrée.

    Format allowlist.json :
    {
      "version": 1,
      "updated_at": "ISO8601",
      "ca_fingerprint": "<sha3-256>",
      "entries": [
        {
          "entity_id": "gateway-b1",
          "entity_type": "GATEWAY",
          "fingerprint": "<sha3-256>",
          "added_at": "ISO8601",
          "expires_at": "ISO8601",
          "revoked": false,
          "comment": "Gateway bâtiment B1, zone serveurs"
        },
        ...
      ]
    }
    """

    def __init__(self, ca: CertificateAuthority, path: str | Path):
        self._ca = ca
        self._path = Path(path)
        self._data = self._load_or_init()

    def _load_or_init(self) -> dict:
        if self._path.exists():
            return json.loads(self._path.read_text())
        return {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "ca_fingerprint": self._ca.cert.fingerprint,
            "entries": [],
        }

    def save(self):
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._path.write_text(json.dumps(self._data, indent=2))

    def add(self, cert: HybridCertificate, comment: str = "") -> bool:
        """Ajoute un certificat à l'allow-list après vérification de la signature CA."""
        # 1. Vérifier que le cert est signé par notre CA
        if not self._ca.verify_cert(cert):
            print(f"  [ALLOWLIST] REJET : certificat {cert.entity_id} non signé par la CA")
            return False
        # 2. Vérifier non expiré
        if cert.is_expired():
            print(f"  [ALLOWLIST] REJET : certificat {cert.entity_id} expiré")
            return False
        # 3. Ajouter
        entry = {
            "entity_id": cert.entity_id,
            "entity_type": cert.entity_type,
            "fingerprint": cert.fingerprint,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": cert.not_after.isoformat(),
            "revoked": False,
            "comment": comment,
        }
        # Supprimer l'ancienne entrée si elle existe
        self._data["entries"] = [
            e for e in self._data["entries"] if e["fingerprint"] != cert.fingerprint
        ]
        self._data["entries"].append(entry)
        self.save()
        print(f"  [ALLOWLIST] Ajouté : {cert.entity_id} ({cert.fingerprint[:16]}…)")
        return True

    def revoke(self, fingerprint: str):
        """Révoque un certificat par son fingerprint."""
        for entry in self._data["entries"]:
            if entry["fingerprint"] == fingerprint:
                entry["revoked"] = True
                self.save()
                print(f"  [ALLOWLIST] Révoqué : {entry['entity_id']} ({fingerprint[:16]}…)")
                return
        raise KeyError(f"Fingerprint non trouvé : {fingerprint}")

    def is_authorized(self, cert: HybridCertificate) -> tuple[bool, str]:
        """
        Vérifie si un certificat est autorisé.
        Retourne (authorized: bool, reason: str).

        Contrôles effectués :
          1. Le fingerprint est dans la liste
          2. L'entrée n'est pas révoquée
          3. Le certificat n'est pas expiré
          4. La signature CA est valide (hybride)
        """
        # 1. Recherche par fingerprint
        entry = next(
            (e for e in self._data["entries"] if e["fingerprint"] == cert.fingerprint),
            None
        )
        if entry is None:
            return False, f"Fingerprint {cert.fingerprint[:16]}… absent de l'allow-list"

        # 2. Révocation
        if entry["revoked"]:
            return False, f"Certificat {cert.entity_id} révoqué"

        # 3. Expiration
        if cert.is_expired():
            return False, f"Certificat {cert.entity_id} expiré"

        # 4. Vérification signature CA (hybride)
        if not self._ca.verify_cert(cert):
            return False, f"Signature CA invalide pour {cert.entity_id}"

        return True, "OK"

    def list_entries(self) -> list[dict]:
        return self._data["entries"]


# ═══════════════════════════════════════════════════════════════════
#  Utilitaire : sauvegarde clés entité
# ═══════════════════════════════════════════════════════════════════

def save_entity_keys(
    entity_dir: str | Path,
    cert: HybridCertificate,
    kem_sec: HybridKEMSecretKey,
    sig_sec: HybridSignerSecretKey,
    passphrase: bytes,
):
    """
    Sauvegarde les clés d'une entité (gateway, middleware) :
      - <entity>.crt  → certificat hybride (JSON, public)
      - <entity>.kem.key.enc → clé secrète KEM (chiffrée AES-256)
      - <entity>.sig.key.enc → clé secrète signer (chiffrée AES-256)
    Permissions 600 sur les fichiers de clés.
    """
    d = Path(entity_dir)
    d.mkdir(parents=True, exist_ok=True)

    entity_id = cert.entity_id
    cert.save(d / f"{entity_id}.crt")

    kem_enc = kem_sec.serialize_encrypted(passphrase)
    kem_path = d / f"{entity_id}.kem.key.enc"
    kem_path.write_bytes(kem_enc)
    kem_path.chmod(0o600)

    sig_enc = sig_sec.serialize_encrypted(passphrase)
    sig_path = d / f"{entity_id}.sig.key.enc"
    sig_path.write_bytes(sig_enc)
    sig_path.chmod(0o600)

    print(f"  [{entity_id.upper()}] Clés sauvegardées dans {d} (chiffrées AES-256, perm. 600)")


def load_entity_keys(
    entity_dir: str | Path,
    entity_id: str,
    passphrase: bytes,
) -> tuple[HybridCertificate, HybridKEMSecretKey, HybridSignerSecretKey]:
    """Charge les clés d'une entité depuis le disque."""
    d = Path(entity_dir)
    cert = HybridCertificate.from_file(d / f"{entity_id}.crt")
    kem_sec = HybridKEMSecretKey.deserialize_encrypted(
        (d / f"{entity_id}.kem.key.enc").read_bytes(), passphrase
    )
    sig_sec = HybridSignerSecretKey.deserialize_encrypted(
        (d / f"{entity_id}.sig.key.enc").read_bytes(), passphrase
    )
    return cert, kem_sec, sig_sec
