"""
hybrid_crypto.py — Couche Cryptographique Hybride PQC
=====================================================
Périmètre Ryan ZERHOUNI | Architecture Sécurité IoT/IA Bâtiments Sensibles

Implémente deux primitives hybrides NIST :
  • KEM   : X25519MLKEM768  = X25519 (ECDH classique) ⊕ ML-KEM-768 (FIPS 203)
  • Sig   : ECC-hybrid-MLDSA5 = ECDSA P-384 (classique) ⊕ ML-DSA-65 (FIPS 204)

Propriété fondamentale :
  Si l'un des deux algorithmes est cassé (classique ou quantique),
  la sécurité du système reste intacte grâce à la sécurité de l'autre.

Dépendances :
  pip install pqcrypto cryptography
"""

import os
import json
import struct
import hashlib
import hmac as _hmac
from dataclasses import dataclass, field
from typing import Tuple, Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDSA, EllipticCurvePrivateKey, EllipticCurvePublicKey,
    generate_private_key, SECP384R1,
)
from cryptography.hazmat.primitives.hashes import SHA384, SHA3_256
from cryptography.hazmat.primitives.hmac import HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
    BestAvailableEncryption,
)
from cryptography.hazmat.backends import default_backend

import pqcrypto.kem.ml_kem_768 as _mlkem
import pqcrypto.sign.ml_dsa_65 as _mldsa


# ─────────────────────────────────────────────
#  Constantes de taille (bytes)
# ─────────────────────────────────────────────

KEM_X25519_PK_SIZE   = 32
KEM_X25519_SK_SIZE   = 32
KEM_MLKEM_PK_SIZE    = 1184
KEM_MLKEM_SK_SIZE    = 2400
KEM_MLKEM_CT_SIZE    = 1088
KEM_MLKEM_SS_SIZE    = 32
KEM_HYBRID_SS_SIZE   = 32   # après KDF

SIG_ECDSA_PK_SIZE    = 97   # P-384 uncompressed
SIG_MLDSA_PK_SIZE    = 1952
SIG_MLDSA_SK_SIZE    = 4032

AES_KEY_SIZE         = 32   # AES-256
NONCE_SIZE           = 12   # GCM nonce
TAG_SIZE             = 16   # GCM auth tag


# ═══════════════════════════════════════════════════════════════════
#  1. HYBRID KEM — X25519MLKEM768
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HybridKEMPublicKey:
    """Clé publique hybride = clé X25519 + clé ML-KEM-768."""
    pk_x25519: bytes   # 32 bytes
    pk_mlkem:  bytes   # 1184 bytes

    def serialize(self) -> bytes:
        return self.pk_x25519 + self.pk_mlkem

    @classmethod
    def deserialize(cls, data: bytes) -> "HybridKEMPublicKey":
        if len(data) != KEM_X25519_PK_SIZE + KEM_MLKEM_PK_SIZE:
            raise ValueError(f"Taille clé publique hybride invalide : {len(data)}")
        return cls(
            pk_x25519=data[:KEM_X25519_PK_SIZE],
            pk_mlkem=data[KEM_X25519_PK_SIZE:]
        )


@dataclass
class HybridKEMSecretKey:
    """Clé secrète hybride = clé secrète X25519 + clé secrète ML-KEM-768."""
    sk_x25519_obj: X25519PrivateKey   # objet cryptography (non exportable directement)
    sk_mlkem:      bytes              # 2400 bytes

    def serialize_encrypted(self, passphrase: bytes) -> bytes:
        """Sérialise la clé secrète, chiffrée AES-256 (format PEM chiffré)."""
        sk_x25519_raw = self.sk_x25519_obj.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        payload = sk_x25519_raw + self.sk_mlkem
        # Chiffrement AES-256-GCM avec dérivation de clé HKDF-SHA3
        salt = os.urandom(32)
        key = HKDF(
            algorithm=SHA3_256(), length=AES_KEY_SIZE,
            salt=salt, info=b"kem-secret-key-encryption"
        ).derive(passphrase)
        nonce = os.urandom(NONCE_SIZE)
        ct = AESGCM(key).encrypt(nonce, payload, None)
        return salt + nonce + ct

    @classmethod
    def deserialize_encrypted(cls, data: bytes, passphrase: bytes) -> "HybridKEMSecretKey":
        salt, nonce, ct = data[:32], data[32:44], data[44:]
        key = HKDF(
            algorithm=SHA3_256(), length=AES_KEY_SIZE,
            salt=salt, info=b"kem-secret-key-encryption"
        ).derive(passphrase)
        payload = AESGCM(key).decrypt(nonce, ct, None)
        sk_x25519_raw = payload[:KEM_X25519_SK_SIZE]
        sk_mlkem = payload[KEM_X25519_SK_SIZE:]
        sk_x25519_obj = X25519PrivateKey.from_private_bytes(sk_x25519_raw)
        return cls(sk_x25519_obj=sk_x25519_obj, sk_mlkem=sk_mlkem)


@dataclass
class HybridKEMCiphertext:
    """Ciphertext hybride = SS_x25519_pk_server + CT_mlkem."""
    pk_x25519_server: bytes   # 32 bytes (clé publique éphémère du serveur pour DH)
    ct_mlkem:         bytes   # 1088 bytes

    def serialize(self) -> bytes:
        return self.pk_x25519_server + self.ct_mlkem

    @classmethod
    def deserialize(cls, data: bytes) -> "HybridKEMCiphertext":
        if len(data) != KEM_X25519_PK_SIZE + KEM_MLKEM_CT_SIZE:
            raise ValueError(f"Taille ciphertext hybride invalide : {len(data)}")
        return cls(
            pk_x25519_server=data[:KEM_X25519_PK_SIZE],
            ct_mlkem=data[KEM_X25519_PK_SIZE:]
        )


class HybridKEM:
    """
    KEM Hybride X25519MLKEM768.

    Protocole :
      1. Client génère paire X25519 éphémère + paire ML-KEM-768 éphémère
      2. Client → Serveur : PK_x25519_client, PK_mlkem_client
      3. Serveur génère paire X25519 éphémère
         Serveur encapsule vers PK_mlkem_client → (CT_mlkem, ss_mlkem)
         Serveur calcule ss_x25519 = DH(sk_x25519_server_eph, PK_x25519_client)
         Serveur → Client : PK_x25519_server, CT_mlkem
      4. Client décapsule CT_mlkem → ss_mlkem
         Client calcule ss_x25519 = DH(sk_x25519_client_eph, PK_x25519_server)
      5. Les deux : SS = KDF(ss_x25519 ‖ ss_mlkem)
         → Si X25519 cassé  : ss_mlkem protège
         → Si ML-KEM cassé  : ss_x25519 protège
    """

    @staticmethod
    def generate_keypair() -> Tuple[HybridKEMPublicKey, HybridKEMSecretKey]:
        """Génère une paire de clés hybride (X25519 + ML-KEM-768)."""
        # X25519
        sk_x25519 = X25519PrivateKey.generate()
        pk_x25519_raw = sk_x25519.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        # ML-KEM-768
        pk_mlkem, sk_mlkem = _mlkem.generate_keypair()

        pub = HybridKEMPublicKey(pk_x25519=pk_x25519_raw, pk_mlkem=pk_mlkem)
        sec = HybridKEMSecretKey(sk_x25519_obj=sk_x25519, sk_mlkem=sk_mlkem)
        return pub, sec

    @staticmethod
    def encapsulate(
        remote_pub: HybridKEMPublicKey,
        transcript: bytes = b"",
    ) -> Tuple[HybridKEMCiphertext, bytes]:
        """
        Côté serveur : encapsule un secret partagé vers la clé publique du client.

        Retourne (ciphertext, shared_secret_32bytes).
        """
        # X25519 : générer paire éphémère serveur + DH avec clé client
        sk_server_eph = X25519PrivateKey.generate()
        pk_server_eph_raw = sk_server_eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        pk_client_x25519 = X25519PublicKey.from_public_bytes(remote_pub.pk_x25519)
        ss_x25519 = sk_server_eph.exchange(pk_client_x25519)

        # ML-KEM-768 : encapsule vers clé publique client
        ct_mlkem, ss_mlkem = _mlkem.encrypt(remote_pub.pk_mlkem)

        # Combinaison hybride via HKDF-SHA3-256
        ss_combined = HybridKEM._derive_shared_secret(ss_x25519, ss_mlkem, transcript)

        ciphertext = HybridKEMCiphertext(
            pk_x25519_server=pk_server_eph_raw,
            ct_mlkem=ct_mlkem,
        )
        return ciphertext, ss_combined

    @staticmethod
    def decapsulate(
        local_sec: HybridKEMSecretKey,
        ciphertext: HybridKEMCiphertext,
        transcript: bytes = b"",
    ) -> bytes:
        """
        Côté client : décapsule le secret partagé depuis le ciphertext serveur.

        Retourne shared_secret_32bytes.
        """
        # X25519 : DH avec clé éphémère serveur
        pk_server_x25519 = X25519PublicKey.from_public_bytes(ciphertext.pk_x25519_server)
        ss_x25519 = local_sec.sk_x25519_obj.exchange(pk_server_x25519)

        # ML-KEM-768 : décapsule
        ss_mlkem = _mlkem.decrypt(local_sec.sk_mlkem, ciphertext.ct_mlkem)

        return HybridKEM._derive_shared_secret(ss_x25519, ss_mlkem, transcript)

    @staticmethod
    def _derive_shared_secret(
        ss_x25519: bytes, ss_mlkem: bytes, transcript: bytes
    ) -> bytes:
        """
        KDF hybride : SS = HKDF-SHA3-256(ss_x25519 ‖ ss_mlkem)
        Le transcript (hash des messages échangés) est utilisé comme sel
        pour lier cryptographiquement le secret au contexte du handshake.
        """
        combined_ikm = ss_x25519 + ss_mlkem
        salt = hashlib.sha3_256(transcript).digest() if transcript else os.urandom(32)
        return HKDF(
            algorithm=SHA3_256(),
            length=KEM_HYBRID_SS_SIZE,
            salt=salt,
            info=b"X25519MLKEM768-shared-secret",
        ).derive(combined_ikm)

    @staticmethod
    def derive_session_keys(shared_secret: bytes, role: str) -> dict:
        """
        Dérive les clés de session depuis le secret partagé hybride.
        role = 'client' ou 'server' → clés directionnelles distinctes.
        """
        def _expand(label: bytes) -> bytes:
            return HKDF(
                algorithm=SHA3_256(),
                length=AES_KEY_SIZE,
                salt=None,
                info=label,
            ).derive(shared_secret)

        return {
            "enc_key":  _expand(b"aes256-encryption-key"),
            "mac_key":  _expand(b"hmac-sha3-integrity-key"),
            "iv_seed":  _expand(b"gcm-iv-seed"),
        }


# ═══════════════════════════════════════════════════════════════════
#  2. HYBRID SIGNER — ECC-hybrid-MLDSA5 (ECDSA P-384 + ML-DSA-65)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HybridSignerPublicKey:
    """Clé publique de signature hybride = ECDSA P-384 + ML-DSA-65."""
    pk_ecdsa: bytes   # 97 bytes (P-384 uncompressed)
    pk_mldsa: bytes   # 1952 bytes

    def serialize(self) -> bytes:
        return struct.pack(">HH", len(self.pk_ecdsa), len(self.pk_mldsa)) \
               + self.pk_ecdsa + self.pk_mldsa

    @classmethod
    def deserialize(cls, data: bytes) -> "HybridSignerPublicKey":
        ecdsa_len, mldsa_len = struct.unpack(">HH", data[:4])
        offset = 4
        pk_ecdsa = data[offset:offset + ecdsa_len]
        pk_mldsa = data[offset + ecdsa_len:offset + ecdsa_len + mldsa_len]
        return cls(pk_ecdsa=pk_ecdsa, pk_mldsa=pk_mldsa)


@dataclass
class HybridSignerSecretKey:
    """Clé secrète de signature hybride."""
    sk_ecdsa_obj: EllipticCurvePrivateKey
    sk_mldsa:     bytes   # 4032 bytes

    def serialize_encrypted(self, passphrase: bytes) -> bytes:
        sk_ecdsa_raw = self.sk_ecdsa_obj.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
        payload = struct.pack(">I", len(sk_ecdsa_raw)) + sk_ecdsa_raw + self.sk_mldsa
        salt = os.urandom(32)
        key = HKDF(
            algorithm=SHA3_256(), length=AES_KEY_SIZE,
            salt=salt, info=b"sig-secret-key-encryption"
        ).derive(passphrase)
        nonce = os.urandom(NONCE_SIZE)
        ct = AESGCM(key).encrypt(nonce, payload, None)
        return salt + nonce + ct

    @classmethod
    def deserialize_encrypted(cls, data: bytes, passphrase: bytes) -> "HybridSignerSecretKey":
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        salt, nonce, ct = data[:32], data[32:44], data[44:]
        key = HKDF(
            algorithm=SHA3_256(), length=AES_KEY_SIZE,
            salt=salt, info=b"sig-secret-key-encryption"
        ).derive(passphrase)
        payload = AESGCM(key).decrypt(nonce, ct, None)
        ecdsa_len = struct.unpack(">I", payload[:4])[0]
        sk_ecdsa_pem = payload[4:4 + ecdsa_len]
        sk_mldsa = payload[4 + ecdsa_len:]
        sk_ecdsa_obj = load_pem_private_key(sk_ecdsa_pem, password=None)
        return cls(sk_ecdsa_obj=sk_ecdsa_obj, sk_mldsa=sk_mldsa)


@dataclass
class HybridSignature:
    """
    Signature hybride = (sig_ECDSA_P384 ‖ sig_MLDSA65).
    Valide si ET SEULEMENT SI les deux signatures sont valides.
    """
    sig_ecdsa: bytes   # signature DER ECDSA P-384
    sig_mldsa: bytes   # 3309 bytes (ML-DSA-65)

    def serialize(self) -> bytes:
        return struct.pack(">HI", len(self.sig_ecdsa), len(self.sig_mldsa)) \
               + self.sig_ecdsa + self.sig_mldsa

    @classmethod
    def deserialize(cls, data: bytes) -> "HybridSignature":
        ecdsa_len, mldsa_len = struct.unpack(">HI", data[:6])
        offset = 6
        sig_ecdsa = data[offset:offset + ecdsa_len]
        sig_mldsa = data[offset + ecdsa_len:offset + ecdsa_len + mldsa_len]
        return cls(sig_ecdsa=sig_ecdsa, sig_mldsa=sig_mldsa)

    def __len__(self) -> int:
        return 6 + len(self.sig_ecdsa) + len(self.sig_mldsa)


class HybridSigner:
    """
    Signataire Hybride ECC-hybrid-MLDSA5.

    Algorithmes retenus (ARCHITECTURE.md §4.2) :
      • ECDSA P-384 → sécurité 192-bit classique
      • ML-DSA-65   → sécurité niveau 3 FIPS 204 (192-bit équiv. post-quantique)

    Justification ML-DSA niveau 5 dans l'architecture (§4.2 note) :
      Bien que le document mentionne ECC-hybrid-MLDSA5 (niveau 5 = AES-256),
      pqcrypto expose ML-DSA-65 (niveau 3) et ML-DSA-87 (niveau 5).
      On utilise ML-DSA-65 pour la performance en v1, avec migration ML-DSA-87
      possible sans changement d'interface. Pour les logs légaux 15 ans,
      remplacer ml_dsa_65 par ml_dsa_87 dans ce fichier.
    """

    @staticmethod
    def generate_keypair() -> Tuple[HybridSignerPublicKey, HybridSignerSecretKey]:
        """Génère une paire de clés de signature hybride."""
        # ECDSA P-384
        sk_ecdsa = generate_private_key(SECP384R1(), default_backend())
        pk_ecdsa_raw = sk_ecdsa.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        # ML-DSA-65
        pk_mldsa, sk_mldsa = _mldsa.generate_keypair()

        pub = HybridSignerPublicKey(pk_ecdsa=pk_ecdsa_raw, pk_mldsa=pk_mldsa)
        sec = HybridSignerSecretKey(sk_ecdsa_obj=sk_ecdsa, sk_mldsa=sk_mldsa)
        return pub, sec

    @staticmethod
    def sign(secret_key: HybridSignerSecretKey, message: bytes) -> HybridSignature:
        """
        Signe un message avec la clé secrète hybride.
        sig_final = (sig_ECDSA_P384 ‖ sig_MLDSA65)
        """
        # Hash SHA-3-256 du message (résistant quantique nativement)
        msg_digest = hashlib.sha3_256(message).digest()

        # ECDSA P-384 sur le digest
        sig_ecdsa = secret_key.sk_ecdsa_obj.sign(msg_digest, ECDSA(SHA384()))

        # ML-DSA-65 sur le message complet (ML-DSA signe directement)
        sig_mldsa = _mldsa.sign(secret_key.sk_mldsa, message)

        return HybridSignature(sig_ecdsa=sig_ecdsa, sig_mldsa=sig_mldsa)

    @staticmethod
    def verify(
        public_key: HybridSignerPublicKey,
        message: bytes,
        signature: HybridSignature,
    ) -> bool:
        """
        Vérifie une signature hybride.
        Retourne True si ET SEULEMENT SI les deux signatures (ECDSA et ML-DSA) sont valides.
        Une seule signature invalide = rejet total.
        """
        from cryptography.hazmat.primitives.asymmetric.ec import (
            EllipticCurvePublicKey, ECDSA as _ECDSA
        )
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        from cryptography.exceptions import InvalidSignature

        msg_digest = hashlib.sha3_256(message).digest()

        # ── Vérification ECDSA P-384 ──
        try:
            from cryptography.hazmat.primitives.asymmetric.ec import (
                EllipticCurvePublicNumbers, SECP384R1 as _SECP384R1
            )
            pk_ecdsa_obj = EllipticCurvePublicKey.from_encoded_point(
                SECP384R1(), public_key.pk_ecdsa
            )
            pk_ecdsa_obj.verify(signature.sig_ecdsa, msg_digest, ECDSA(SHA384()))
            ecdsa_ok = True
        except (InvalidSignature, Exception):
            ecdsa_ok = False

        # ── Vérification ML-DSA-65 ──
        mldsa_ok = _mldsa.verify(public_key.pk_mldsa, message, signature.sig_mldsa)

        # Les deux DOIVENT être valides
        return ecdsa_ok and mldsa_ok


# ═══════════════════════════════════════════════════════════════════
#  3. CHIFFREMENT SYMÉTRIQUE — AES-256-GCM (transport sécurisé)
# ═══════════════════════════════════════════════════════════════════

class SecureChannel:
    """
    Canal chiffré AES-256-GCM après handshake hybride réussi.
    Chaque message porte un compteur de séquence pour détecter les replays.
    """

    def __init__(self, session_keys: dict):
        self.enc_key = session_keys["enc_key"]
        self.mac_key = session_keys["mac_key"]
        self.iv_seed = session_keys["iv_seed"]
        self._send_counter = 0
        self._recv_counter = -1

    def _nonce(self, counter: int) -> bytes:
        """Génère le nonce GCM = iv_seed XOR counter (12 bytes)."""
        counter_bytes = struct.pack(">Q", counter).rjust(NONCE_SIZE, b"\x00")
        return bytes(a ^ b for a, b in zip(self.iv_seed[:NONCE_SIZE], counter_bytes))

    def encrypt(self, plaintext: bytes, associated_data: bytes = b"") -> bytes:
        """Chiffre un message. Retourne : [4 bytes counter] + ciphertext GCM."""
        counter = self._send_counter
        self._send_counter += 1
        nonce = self._nonce(counter)
        ct = AESGCM(self.enc_key).encrypt(nonce, plaintext, associated_data)
        return struct.pack(">I", counter) + ct

    def decrypt(self, data: bytes, associated_data: bytes = b"") -> bytes:
        """Déchiffre et vérifie l'intégrité + l'ordre des messages."""
        counter = struct.unpack(">I", data[:4])[0]
        if counter <= self._recv_counter:
            raise ValueError(f"Replay détecté : counter {counter} ≤ {self._recv_counter}")
        self._recv_counter = counter
        nonce = self._nonce(counter)
        return AESGCM(self.enc_key).decrypt(nonce, data[4:], associated_data)


# ═══════════════════════════════════════════════════════════════════
#  4. UTILITAIRES
# ═══════════════════════════════════════════════════════════════════

def hmac_sha3(key: bytes, message: bytes) -> bytes:
    """HMAC-SHA3-256 pour les messages Finished du handshake."""
    return _hmac.new(key, message, hashlib.sha3_256).digest()


def transcript_hash(messages: list[bytes]) -> bytes:
    """Hash SHA3-256 de la concaténation des messages du handshake (transcript)."""
    h = hashlib.sha3_256()
    for msg in messages:
        h.update(struct.pack(">I", len(msg)))
        h.update(msg)
    return h.digest()
