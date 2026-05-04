"""
gen_certs.py — Génération de la chaîne PKI hybride p384_mldsa65.

Génère via le container Docker openquantumsafe/curl (OpenSSL + OQS-provider) :
  1. CA racine auto-signée         → security/ca/ca.key + ca.crt
  2. Certificat d'identité Gateway → security/gateway/gateway.key + gateway.crt
  3. Certificat d'identité Middleware → security/middleware/middleware.key + middleware.crt

Pré-requis : Docker installé et accessible.

Usage :
    python security/gen_certs.py [--force]

Options :
    --force   Écrase les certificats existants (sinon le script s'arrête s'il
              détecte des fichiers en place).
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent          # racine du dépôt
SECURITY_DIR = Path(__file__).parent              # security/
CA_DIR = SECURITY_DIR / "ca"
GW_DIR = SECURITY_DIR / "gateway"
MW_DIR = SECURITY_DIR / "middleware"

ALGO = "p384_mldsa65"
DAYS_CA = 825
DAYS_LEAF = 365
OQS_IMAGE = "openquantumsafe/curl"

# Subjects des certificats
SUBJ_CA = "/CN=PQC-Root-CA/O=SmartIDS/C=FR"
SUBJ_GW = "/CN=gateway.iot.local/O=SmartIDS/C=FR"
SUBJ_MW = "/CN=middleware.iot.local/O=SmartIDS/C=FR"

# Montage Docker : le répertoire security/ → /certs dans le container
MOUNT = f"{SECURITY_DIR}:/certs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], step: str) -> None:
    """Exécute une commande et arrête le script en cas d'erreur."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERREUR] Étape : {step}")
        print(result.stderr.strip())
        sys.exit(1)
    print(f"  [OK] {step}")


def _docker_openssl(args: list[str], step: str) -> None:
    """Lance openssl dans le container OQS via Docker."""
    cmd = ["docker", "run", "--rm", "-v", MOUNT, OQS_IMAGE, "openssl"] + args
    _run(cmd, step)


def _backup_existing() -> None:
    """Crée un backup daté des certs existants."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = SECURITY_DIR / f"backup_{ts}"
    backup_dir.mkdir()
    for d in [CA_DIR, GW_DIR, MW_DIR]:
        if d.exists():
            shutil.copytree(d, backup_dir / d.name)
    print(f"  [OK] Backup créé : {backup_dir.relative_to(REPO_ROOT)}/")


def _set_permissions() -> None:
    """Applique chmod 600 sur toutes les clés privées."""
    for keyfile in SECURITY_DIR.rglob("*.key"):
        keyfile.chmod(0o600)
    print("  [OK] Permissions 600 appliquées sur les clés privées")


def _certs_exist() -> bool:
    return (CA_DIR / "ca.crt").exists()


# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------

def generate_ca() -> None:
    print("\n[1/3] Génération de la CA racine...")
    CA_DIR.mkdir(parents=True, exist_ok=True)

    _docker_openssl([
        "genpkey", "-algorithm", ALGO,
        "-out", "/certs/ca/ca.key",
    ], "CA — génération de la clé privée")

    _docker_openssl([
        "req", "-new", "-x509",
        "-key", "/certs/ca/ca.key",
        "-out", "/certs/ca/ca.crt",
        "-days", str(DAYS_CA),
        "-subj", SUBJ_CA,
    ], "CA — certificat auto-signé")


def generate_gateway() -> None:
    print("\n[2/3] Génération du certificat Gateway...")
    GW_DIR.mkdir(parents=True, exist_ok=True)

    _docker_openssl([
        "genpkey", "-algorithm", ALGO,
        "-out", "/certs/gateway/gateway.key",
    ], "Gateway — génération de la clé privée")

    _docker_openssl([
        "req", "-new",
        "-key", "/certs/gateway/gateway.key",
        "-out", "/certs/gateway/gateway.csr",
        "-subj", SUBJ_GW,
    ], "Gateway — création du CSR")

    _docker_openssl([
        "x509", "-req",
        "-in", "/certs/gateway/gateway.csr",
        "-CA", "/certs/ca/ca.crt",
        "-CAkey", "/certs/ca/ca.key",
        "-CAcreateserial",
        "-out", "/certs/gateway/gateway.crt",
        "-days", str(DAYS_LEAF),
    ], "Gateway — signature par la CA")


def generate_middleware() -> None:
    print("\n[3/3] Génération du certificat Middleware...")
    MW_DIR.mkdir(parents=True, exist_ok=True)

    _docker_openssl([
        "genpkey", "-algorithm", ALGO,
        "-out", "/certs/middleware/middleware.key",
    ], "Middleware — génération de la clé privée")

    _docker_openssl([
        "req", "-new",
        "-key", "/certs/middleware/middleware.key",
        "-out", "/certs/middleware/middleware.csr",
        "-subj", SUBJ_MW,
    ], "Middleware — création du CSR")

    _docker_openssl([
        "x509", "-req",
        "-in", "/certs/middleware/middleware.csr",
        "-CA", "/certs/ca/ca.crt",
        "-CAkey", "/certs/ca/ca.key",
        "-CAserial", "/certs/ca/ca.srl",
        "-out", "/certs/middleware/middleware.crt",
        "-days", str(DAYS_LEAF),
    ], "Middleware — signature par la CA")


def verify_chain() -> None:
    """Vérifie que les certificats leaf sont bien signés par la CA."""
    print("\n[Vérification] Chaîne de confiance...")
    for name, crt in [("gateway", "/certs/gateway/gateway.crt"),
                      ("middleware", "/certs/middleware/middleware.crt")]:
        _docker_openssl([
            "verify", "-CAfile", "/certs/ca/ca.crt", crt,
        ], f"Vérification {name} → CA")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true",
                        help="Écrase les certificats existants après backup")
    args = parser.parse_args()

    # Vérifier que Docker est disponible
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        sys.exit("[ERREUR] Docker n'est pas accessible. Démarrez Docker Desktop.")

    # Vérifier que l'image OQS est dispo (pull si nécessaire)
    print(f"[Init] Vérification de l'image Docker {OQS_IMAGE}...")
    subprocess.run(["docker", "pull", OQS_IMAGE], capture_output=True)

    # Gestion des certs existants
    if _certs_exist():
        if not args.force:
            print("[INFO] Des certificats existent déjà.")
            print("       Utilisez --force pour les regénérer (un backup sera créé automatiquement).")
            sys.exit(0)
        print("[Backup] Sauvegarde des certificats existants...")
        _backup_existing()

    # Génération
    generate_ca()
    generate_gateway()
    generate_middleware()

    # Permissions
    print("\n[Permissions]")
    _set_permissions()

    # Vérification
    verify_chain()

    print(f"""
╔══════════════════════════════════════════════════════╗
║  Certificats générés avec succès (algorithme: {ALGO})
║
║  security/ca/ca.crt              ← CA racine
║  security/gateway/gateway.crt   ← Identité Gateway
║  security/middleware/middleware.crt ← Identité Middleware
╚══════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
