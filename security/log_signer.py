"""
log_signer.py — Double signature p384_mldsa65 pour les logs d'intrusion.

Chaque entrée de log est signée avec :
  1. ECDSA P-384  (sécurité classique, via `cryptography`)
  2. ML-DSA-65    (sécurité post-quantique, via `liboqs-python`)

Usage :
    python log_signer.py keygen                   # Génère les clés de signing
    python log_signer.py sign   <log_entry>       # Signe une entrée (JSON)
    python log_signer.py verify <log_entry_file>  # Vérifie l'intégrité
"""

import json
import os
import sys
import hashlib
import base64
from datetime import datetime, timezone
from pathlib import Path

# --- Dépendances ---
try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
        encode_dss_signature,
    )
    from cryptography.hazmat.primitives import hashes, serialization
except ImportError:
    sys.exit("cryptography manquant : pip install cryptography")

try:
    import oqs
except ImportError:
    sys.exit("liboqs-python manquant : pip install liboqs-python")

# --- Chemins ---
SECURITY_DIR = Path(__file__).parent
KEY_DIR = SECURITY_DIR / "log_signing_keys"
ECDSA_PRIV_PATH = KEY_DIR / "ecdsa_p384.pem"
ECDSA_PUB_PATH = KEY_DIR / "ecdsa_p384_pub.pem"
MLDSA_PRIV_PATH = KEY_DIR / "mldsa65.bin"
MLDSA_PUB_PATH = KEY_DIR / "mldsa65_pub.bin"

MLDSA_ALG = "ML-DSA-65"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_ecdsa_priv() -> ec.EllipticCurvePrivateKey:
    with open(ECDSA_PRIV_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _load_ecdsa_pub() -> ec.EllipticCurvePublicKey:
    with open(ECDSA_PUB_PATH, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def _canonical_bytes(entry: dict) -> bytes:
    """Sérialisation canonique déterministe d'une entrée de log."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Keygen
# ---------------------------------------------------------------------------

def keygen() -> None:
    """Génère et stocke les paires de clés ECDSA P-384 et ML-DSA-65."""
    KEY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    # ECDSA P-384
    ecdsa_priv = ec.generate_private_key(ec.SECP384R1())
    ECDSA_PRIV_PATH.write_bytes(
        ecdsa_priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    ECDSA_PUB_PATH.write_bytes(
        ecdsa_priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(ECDSA_PRIV_PATH, 0o600)

    # ML-DSA-65
    with oqs.Signature(MLDSA_ALG) as signer:
        mldsa_pub = signer.generate_keypair()
        mldsa_priv = signer.export_secret_key()

    MLDSA_PRIV_PATH.write_bytes(mldsa_priv)
    MLDSA_PUB_PATH.write_bytes(mldsa_pub)
    os.chmod(MLDSA_PRIV_PATH, 0o600)

    print(f"[keygen] Clés générées dans {KEY_DIR}/")
    print(f"  ECDSA P-384  : {ECDSA_PRIV_PATH.name}, {ECDSA_PUB_PATH.name}")
    print(f"  ML-DSA-65    : {MLDSA_PRIV_PATH.name}, {MLDSA_PUB_PATH.name}")


# ---------------------------------------------------------------------------
# Sign
# ---------------------------------------------------------------------------

def sign(entry: dict) -> dict:
    """
    Signe une entrée de log et retourne l'enveloppe signée.

    L'enveloppe a la structure :
    {
        "payload":    <dict original>,
        "timestamp":  <ISO-8601 UTC>,
        "digest":     <SHA-256 hex du payload canonique>,
        "signatures": {
            "ecdsa_p384": <base64>,
            "mldsa65":    <base64>
        }
    }
    """
    payload_bytes = _canonical_bytes(entry)
    digest = hashlib.sha256(payload_bytes).hexdigest()
    timestamp = datetime.now(timezone.utc).isoformat()

    # Données à signer = timestamp ‖ digest (protège contre replay)
    signed_data = f"{timestamp}|{digest}".encode("utf-8")

    # 1. ECDSA P-384
    ecdsa_priv = _load_ecdsa_priv()
    ecdsa_sig = ecdsa_priv.sign(signed_data, ec.ECDSA(hashes.SHA384()))
    ecdsa_b64 = base64.b64encode(ecdsa_sig).decode()

    # 2. ML-DSA-65
    mldsa_secret = MLDSA_PRIV_PATH.read_bytes()
    with oqs.Signature(MLDSA_ALG, mldsa_secret) as signer:
        mldsa_sig = signer.sign(signed_data)
    mldsa_b64 = base64.b64encode(mldsa_sig).decode()

    return {
        "payload": entry,
        "timestamp": timestamp,
        "digest": digest,
        "signatures": {
            "ecdsa_p384": ecdsa_b64,
            "mldsa65": mldsa_b64,
        },
    }


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify(envelope: dict) -> bool:
    """
    Vérifie les deux signatures d'une enveloppe de log.

    Retourne True si tout est valide, lève une exception sinon.
    """
    payload_bytes = _canonical_bytes(envelope["payload"])
    expected_digest = hashlib.sha256(payload_bytes).hexdigest()

    if envelope["digest"] != expected_digest:
        raise ValueError(
            f"Digest invalide : attendu {expected_digest}, reçu {envelope['digest']}"
        )

    signed_data = f"{envelope['timestamp']}|{envelope['digest']}".encode("utf-8")

    # 1. Vérification ECDSA P-384
    ecdsa_pub = _load_ecdsa_pub()
    ecdsa_sig = base64.b64decode(envelope["signatures"]["ecdsa_p384"])
    ecdsa_pub.verify(ecdsa_sig, signed_data, ec.ECDSA(hashes.SHA384()))

    # 2. Vérification ML-DSA-65
    mldsa_pub = MLDSA_PUB_PATH.read_bytes()
    mldsa_sig = base64.b64decode(envelope["signatures"]["mldsa65"])
    with oqs.Signature(MLDSA_ALG) as verifier:
        valid = verifier.verify(signed_data, mldsa_sig, mldsa_pub)
    if not valid:
        raise ValueError("Signature ML-DSA-65 invalide")

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _usage():
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _usage()

    cmd = sys.argv[1]

    if cmd == "keygen":
        keygen()

    elif cmd == "sign":
        if len(sys.argv) < 3:
            print("Usage: log_signer.py sign '<json>'")
            sys.exit(1)
        entry = json.loads(sys.argv[2])
        envelope = sign(entry)
        print(json.dumps(envelope, indent=2))

    elif cmd == "verify":
        if len(sys.argv) < 3:
            print("Usage: log_signer.py verify <envelope_file.json>")
            sys.exit(1)
        path = Path(sys.argv[2])
        envelope = json.loads(path.read_text())
        try:
            verify(envelope)
            print(f"[OK] Signatures valides pour {path.name}")
        except Exception as exc:
            print(f"[FAIL] {exc}")
            sys.exit(1)

    else:
        _usage()
