#!/usr/bin/env python3
"""
scripts/gen_certs.py — Génération des Certificats Hybrides
===========================================================
Périmètre Ryan ZERHOUNI

Génère l'infrastructure de clés complète :
  1. Autorité de certification (CA) racine hybride (ECC-hybrid-MLDSA5)
  2. Certificat Gateway (gateway-b1) — émis par la CA
  3. Certificat Middleware — émis par la CA
  4. Allow-list initiale avec les deux certificats

Usage :
  python scripts/gen_certs.py [--passphrase <passphrase>] [--base-dir <dir>]

Structure générée :
  security/
  ├── ca/
  │   ├── ca.crt          ← certificat CA (JSON hybride, public)
  │   └── ca.key.enc      ← clé secrète CA (chiffrée AES-256, perm. 600)
  ├── gateway/
  │   ├── gateway-b1.crt
  │   ├── gateway-b1.kem.key.enc
  │   └── gateway-b1.sig.key.enc
  ├── middleware/
  │   ├── middleware.crt
  │   ├── middleware.kem.key.enc
  │   └── middleware.sig.key.enc
  └── allowlist.json
"""

import sys
import os
import argparse
import logging

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Brouillon.cert_manager import (
    CertificateAuthority, AllowList,
    save_entity_keys,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gen-certs")


def generate_pki(base_dir: str, passphrase: bytes, force: bool = False):
    """
    Génère l'intégralité de l'infrastructure de clés hybride PQC.

    Paramètres :
      base_dir   : répertoire racine security/ du projet
      passphrase : passphrase AES-256 pour chiffrer les clés privées
      force      : écraser les clés existantes si True
    """
    ca_dir         = os.path.join(base_dir, "ca")
    gateway_dir    = os.path.join(base_dir, "gateway")
    middleware_dir = os.path.join(base_dir, "middleware")
    allowlist_path = os.path.join(base_dir, "allowlist.json")

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║    Génération PKI Hybride PQC — ECC-hybrid-MLDSA5           ║")
    print("║    X25519MLKEM768 (KEM) + ECDSA-P384+ML-DSA-65 (Signature)  ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # ── 1. Autorité de Certification (CA) ────────────────────────
    print("▶ [1/4] Génération de la CA racine hybride…")
    if os.path.exists(os.path.join(ca_dir, "ca.crt")) and not force:
        log.info("  CA existante détectée — chargement (utiliser --force pour régénérer)")
        ca = CertificateAuthority.load(ca_dir, passphrase)
    else:
        ca = CertificateAuthority.generate(ca_id="ca-root")
        ca.save(ca_dir, passphrase)

    print(f"  Fingerprint CA : {ca.cert.fingerprint[:32]}…")
    print(f"  Validité       : jusqu'au {ca.cert.not_after.date()}")
    print()

    # ── 2. Certificat Gateway ─────────────────────────────────────
    print("▶ [2/4] Génération du certificat Gateway (gateway-b1)…")
    gw_cert_path = os.path.join(gateway_dir, "gateway-b1.crt")
    if os.path.exists(gw_cert_path) and not force:
        log.info("  Certificat gateway-b1 existant — ignoré (--force pour régénérer)")
        from cert_manager import HybridCertificate, load_entity_keys
        gw_cert = HybridCertificate.from_file(gw_cert_path)
    else:
        gw_cert, gw_kem_sk, gw_sig_sk = ca.issue(
            entity_id="gateway-b1",
            entity_type="GATEWAY",
            validity_days=365,
        )
        save_entity_keys(gateway_dir, gw_cert, gw_kem_sk, gw_sig_sk, passphrase)

    print(f"  Fingerprint GW : {gw_cert.fingerprint[:32]}…")
    print(f"  Validité       : jusqu'au {gw_cert.not_after.date()}")
    print()

    # ── 3. Certificat Middleware ──────────────────────────────────
    print("▶ [3/4] Génération du certificat Middleware…")
    mw_cert_path = os.path.join(middleware_dir, "middleware.crt")
    if os.path.exists(mw_cert_path) and not force:
        log.info("  Certificat middleware existant — ignoré (--force pour régénérer)")
        from cert_manager import HybridCertificate
        mw_cert = HybridCertificate.from_file(mw_cert_path)
    else:
        mw_cert, mw_kem_sk, mw_sig_sk = ca.issue(
            entity_id="middleware",
            entity_type="MIDDLEWARE",
            validity_days=365,
        )
        save_entity_keys(middleware_dir, mw_cert, mw_kem_sk, mw_sig_sk, passphrase)

    print(f"  Fingerprint MW : {mw_cert.fingerprint[:32]}…")
    print(f"  Validité       : jusqu'au {mw_cert.not_after.date()}")
    print()

    # ── 4. Allow-list ─────────────────────────────────────────────
    print("▶ [4/4] Construction de l'allow-list mTLS…")
    allowlist = AllowList(ca, allowlist_path)
    allowlist.add(ca.cert,  comment="CA racine auto-inscrite")
    allowlist.add(gw_cert,  comment="Gateway bâtiment B1 — zone capteurs")
    allowlist.add(mw_cert,  comment="Middleware — normalisation & Kafka")

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                    ✅  PKI GÉNÉRÉE                          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Répertoire    : {base_dir}")
    print(f"  Algorithmes   : X25519+ML-KEM-768 (KEM) / ECDSA-P384+ML-DSA-65 (Sig)")
    print(f"  Clés chiffrées: AES-256-GCM + HKDF-SHA3-256 (permissions 600)")
    print(f"  Allow-list    : {len(allowlist.list_entries())} entrées")
    print()
    print("  ⚠ SÉCURITÉ : Changez la passphrase en production !")
    print("    Variable d'environnement : KEY_PASSPHRASE")
    print()

    return ca, gw_cert, mw_cert, allowlist


def main():
    parser = argparse.ArgumentParser(
        description="Génération de la PKI hybride PQC pour IoT Security"
    )
    parser.add_argument(
        "--passphrase",
        default=os.getenv("KEY_PASSPHRASE", "changeme-in-production"),
        help="Passphrase pour chiffrer les clés privées (défaut: $KEY_PASSPHRASE)"
    )
    parser.add_argument(
        "--base-dir",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="Répertoire racine security/ (défaut: répertoire du script)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regénérer même si des clés existent déjà"
    )
    args = parser.parse_args()

    generate_pki(
        base_dir=args.base_dir,
        passphrase=args.passphrase.encode(),
        force=args.force,
    )


if __name__ == "__main__":
    main()
