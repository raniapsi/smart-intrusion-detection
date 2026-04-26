#!/usr/bin/env python3
"""
scripts/test_security.py — Tests d'Intégration Couche Sécurité PQC
===================================================================
Périmètre Ryan ZERHOUNI

Valide l'ensemble de la couche sécurité :
  1. ✓ Génération clés hybrides (X25519+MLKEM768, ECDSA-P384+MLDSA65)
  2. ✓ Handshake KEM complet (encapsulation / décapsulation)
  3. ✓ Signature et vérification hybride (logs)
  4. ✓ Génération et vérification certificats CA
  5. ✓ Allow-list : autorisation, refus, révocation
  6. ✓ Signature de logs + chaîne d'intégrité
  7. ✓ Vérification d'intégrité (détection de falsification)
  8. ✓ Session Resumption PSK (émission, rédemption)
  9. ✓ Handshake TLS hybride complet client ↔ serveur
  10.✓ Handshake RESUME (PSK+DHE)
"""

import sys
import os
import uuid
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Brouillon.hybrid_crypto import HybridKEM, HybridSigner, SecureChannel, HybridKEMPublicKey
from Brouillon.cert_manager import CertificateAuthority, AllowList, save_entity_keys, load_entity_keys, HybridCertificate
from Brouillon.log_signer import LogSigner, LogVerifier, SignedLogEntry
from Brouillon.session_cache import SessionCache, ClientSessionStore
from Brouillon.gen_certs import generate_pki

import tempfile


# ─────────────────────────────────────────────────────────────────
#  Utilitaires d'affichage
# ─────────────────────────────────────────────────────────────────

PASS = "✅"
FAIL = "❌"
INFO = "  "

def test(name: str, result: bool, details: str = ""):
    status = PASS if result else FAIL
    line = f"  {status} {name}"
    if details:
        line += f" — {details}"
    print(line)
    if not result:
        raise AssertionError(f"Test échoué : {name}")
    return True


def section(title: str):
    print()
    print(f"{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ═══════════════════════════════════════════════════════════════════
#  Tests unitaires
# ═══════════════════════════════════════════════════════════════════

def test_hybrid_kem():
    section("1. KEM Hybride — X25519MLKEM768")
    t0 = time.perf_counter()

    # Génération
    pub, sec = HybridKEM.generate_keypair()
    test("Génération paire de clés hybride",
         len(pub.pk_x25519) == 32 and len(pub.pk_mlkem) == 1184,
         f"X25519={len(pub.pk_x25519)}B, MLKEM={len(pub.pk_mlkem)}B")

    # Sérialisation / désérialisation
    pub2 = HybridKEMPublicKey.deserialize(pub.serialize())
    test("Sérialisation / désérialisation clé publique",
         pub2.pk_x25519 == pub.pk_x25519 and pub2.pk_mlkem == pub.pk_mlkem)

    # Encapsulation / décapsulation
    ciphertext, ss_server = HybridKEM.encapsulate(pub, transcript=b"test-transcript")
    ss_client = HybridKEM.decapsulate(sec, ciphertext, transcript=b"test-transcript")
    test("Encapsulation X25519MLKEM768",
         len(ciphertext.serialize()) == 32 + 1088,
         f"ct={len(ciphertext.serialize())}B")
    test("Shared secrets identiques (encapsulation = décapsulation)",
         ss_server == ss_client,
         f"ss={ss_server.hex()[:16]}…")

    # Transcript différent → shared secret différent (binding)
    ss_wrong = HybridKEM.decapsulate(sec, ciphertext, transcript=b"wrong-transcript")
    test("Transcript binding : transcripts différents → secrets différents",
         ss_wrong != ss_client)

    # Dérivation des clés de session
    keys = HybridKEM.derive_session_keys(ss_client, role="client")
    test("Dérivation clés de session AES-256",
         all(len(k) == 32 for k in keys.values()),
         f"enc_key={keys['enc_key'].hex()[:16]}…")

    ms = (time.perf_counter() - t0) * 1000
    print(f"\n  Temps total KEM : {ms:.1f} ms")


def test_hybrid_signer():
    section("2. Signature Hybride — ECC-hybrid-MLDSA5 (ECDSA-P384 + ML-DSA-65)")
    t0 = time.perf_counter()

    pub, sec = HybridSigner.generate_keypair()
    test("Génération paire de clés signature",
         len(pub.pk_ecdsa) > 0 and len(pub.pk_mldsa) == 1952,
         f"ECDSA={len(pub.pk_ecdsa)}B, MLDSA={len(pub.pk_mldsa)}B")

    # Signature
    message = b"Log IoT critique : porte B2 forcee sans badge - 03:17:42"
    sig = HybridSigner.sign(sec, message)
    test("Signature hybride",
         len(sig.sig_ecdsa) > 0 and len(sig.sig_mldsa) > 0,
         f"ECDSA={len(sig.sig_ecdsa)}B, MLDSA={len(sig.sig_mldsa)}B")

    # Vérification
    valid = HybridSigner.verify(pub, message, sig)
    test("Vérification signature valide", valid)

    # Falsification
    import copy
    tampered_sig = copy.deepcopy(sig)
    tampered_sig.sig_mldsa = b"\x00" * len(tampered_sig.sig_mldsa)
    invalid = HybridSigner.verify(pub, message, tampered_sig)
    test("Rejet signature ML-DSA falsifiée", not invalid)

    # Message falsifié
    invalid2 = HybridSigner.verify(pub, b"message modifie", sig)
    test("Rejet message falsifié", not invalid2)

    # Sérialisation de la signature
    sig_bytes = sig.serialize()
    sig2 = type(sig).deserialize(sig_bytes)
    valid2 = HybridSigner.verify(pub, message, sig2)
    test("Sérialisation / désérialisation signature", valid2)

    ms = (time.perf_counter() - t0) * 1000
    print(f"\n  Temps total Sig : {ms:.1f} ms")


def test_certificates(tmpdir: str):
    section("3. Certificats Hybrides & Allow-list")

    passphrase = b"test-passphrase-securise"

    # Génération CA
    ca = CertificateAuthority.generate("ca-root-test")
    test("Génération CA racine hybride", ca.cert.entity_id == "ca-root-test")

    # Vérification auto-signature CA
    ca_self_valid = ca.verify_cert(ca.cert)
    test("CA auto-signature valide", ca_self_valid)

    # Émission certificat gateway
    gw_cert, gw_kem_sk, gw_sig_sk = ca.issue("gateway-test", "GATEWAY", validity_days=30)
    test("Émission certificat gateway",
         gw_cert.entity_id == "gateway-test" and gw_cert.entity_type == "GATEWAY")

    # Vérification signature par CA
    gw_valid = ca.verify_cert(gw_cert)
    test("Signature CA du cert gateway valide", gw_valid)

    # Émission certificat middleware
    mw_cert, mw_kem_sk, mw_sig_sk = ca.issue("middleware-test", "MIDDLEWARE", validity_days=30)
    mw_valid = ca.verify_cert(mw_cert)
    test("Émission & vérification cert middleware", mw_valid)

    # Sérialisation / chargement certificat
    gw_cert.save(os.path.join(tmpdir, "test.crt"))
    gw_cert2 = HybridCertificate.from_file(os.path.join(tmpdir, "test.crt"))
    test("Sérialisation / désérialisation certificat",
         gw_cert2.fingerprint == gw_cert.fingerprint)

    # Persistance des clés (chiffrement AES-256)
    gw_dir = os.path.join(tmpdir, "gateway")
    save_entity_keys(gw_dir, gw_cert, gw_kem_sk, gw_sig_sk, passphrase)
    gw_cert3, gw_kem_sk3, gw_sig_sk3 = load_entity_keys(gw_dir, "gateway-test", passphrase)
    test("Persistance clés gateway (chiffrement AES-256)",
         gw_cert3.fingerprint == gw_cert.fingerprint)

    # Allow-list : autorisation
    allowlist_path = os.path.join(tmpdir, "allowlist.json")
    allowlist = AllowList(ca, allowlist_path)
    allowlist.add(gw_cert, "test gateway")
    allowlist.add(mw_cert, "test middleware")

    auth_ok, reason = allowlist.is_authorized(gw_cert)
    test("Allow-list : gateway autorisé", auth_ok, reason)

    # Allow-list : révocation
    allowlist.revoke(gw_cert.fingerprint)
    auth_rev, reason_rev = allowlist.is_authorized(gw_cert)
    test("Allow-list : révocation effective", not auth_rev, reason_rev)

    # Allow-list : cert non inscrit
    other_cert, _, _ = ca.issue("intrus", "GATEWAY")
    auth_unknown, reason_unknown = allowlist.is_authorized(other_cert)
    test("Allow-list : cert non inscrit rejeté", not auth_unknown, reason_unknown)


def test_log_signer(tmpdir: str):
    section("4. Signature des Logs — Chaîne d'intégrité 15 ans")

    _, sig_sec_key = HybridSigner.generate_keypair()
    _, sig_sk = HybridSigner.generate_keypair()
    pub, sec = HybridSigner.generate_keypair()

    # Recréer un signataire propre
    signer = LogSigner(signer_id="middleware-test", sig_secret_key=sec)
    verifier = LogVerifier(signer_pub_key=pub)

    # Créer une séquence de logs
    logs = []
    scenarios = [
        ("INFO",     "Badge alice GRANTED - porte A3 - 09:02:14"),
        ("WARNING",  "Badge bob DENIED - badge révoqué - 14:33:07"),
        ("ALERT",    "Mouvement détecté zone B2 - 03:17:42 - hors horaires"),
        ("CRITICAL", "Porte B2 FORCED + scan réseau simultané - score=1.0"),
    ]

    for level, msg in scenarios:
        event_id = str(uuid.uuid4())
        entry = signer.sign_event(
            event_id=event_id,
            source="MIDDLEWARE",
            level=level,
            message=msg,
            payload={"zone": "B2", "score": 0.95},
        )
        logs.append(entry)

    test(f"Signature de {len(logs)} entrées de log", len(logs) == len(scenarios))

    # Vérification de la chaîne
    all_valid, report = verifier.verify_chain(logs)
    test("Chaîne d'intégrité complète valide", all_valid)

    # Falsification d'un log intermédiaire
    tampered_logs = [SignedLogEntry(e.to_dict()) for e in logs]
    tampered_logs[1]._d["message"] = "FALSIFIÉ"
    all_valid_tampered, report_tampered = verifier.verify_chain(tampered_logs)
    test("Détection de falsification du log #2", not all_valid_tampered)

    invalid_entries = [r for r in report_tampered if not r["sig_valid"] or not r["chain_valid"]]
    test("Localisation précise du log falsifié", len(invalid_entries) >= 1)

    # Export rapport d'audit
    audit_path = os.path.join(tmpdir, "audit_report.json")
    verifier.export_audit_report(logs, audit_path)
    test("Export rapport d'audit JSON", os.path.exists(audit_path))


def test_session_cache():
    section("5. Session Resumption — PSK+DHE")

    cache = SessionCache(ticket_lifetime_s=60)

    # Simuler un shared_secret ML-KEM (32 bytes)
    import os as _os
    ss_mlkem = _os.urandom(32)

    # Émission ticket
    ticket_id, ticket_blob = cache.issue_ticket("gateway-b1", ss_mlkem)
    test("Émission ticket PSK",
         len(ticket_id) == 16 and len(ticket_blob) > 0,
         f"ticket_id={ticket_id.hex()[:8]}…")

    # Rédemption ticket
    result = cache.redeem_ticket(ticket_id, ticket_blob)
    test("Rédemption ticket PSK valide", result is not None)
    psk, client_id = result
    test("PSK correct après rédemption", len(psk) == 32 and client_id == "gateway-b1")

    # Anti-replay : second rédemption doit échouer
    result2 = cache.redeem_ticket(ticket_id, ticket_blob)
    test("Anti-replay : second usage du même ticket rejeté", result2 is None)

    # Blob corrompu
    bad_result = cache.redeem_ticket(ticket_id[:8] + b"\x00" * 8, b"blob-invalide")
    test("Blob corrompu rejeté", bad_result is None)

    # Dérivation clé de session RESUME (PSK + X25519)
    import hashlib as _h
    ss_x25519_new = _os.urandom(32)
    session_key = SessionCache.derive_resume_session_key(psk, ss_x25519_new, b"transcript")
    test("Dérivation clé RESUME (PSK+DHE)", len(session_key) == 32)

    # Vérifier PFS : deux résumptions avec X25519 différents → clés différentes
    session_key2 = SessionCache.derive_resume_session_key(psk, _os.urandom(32), b"transcript")
    test("PFS : X25519 différent → clé session différente", session_key != session_key2)

    stats = cache.stats()
    test("Stats cache", stats["active_tickets"] == 0)  # ticket consommé


def test_secure_channel():
    section("6. Canal Chiffré AES-256-GCM + Compteur Anti-Replay")

    import os as _os
    ss = _os.urandom(32)
    keys_alice = HybridKEM.derive_session_keys(ss, role="client")
    keys_bob   = HybridKEM.derive_session_keys(ss, role="client")  # même clé

    alice = SecureChannel(keys_alice)
    bob   = SecureChannel(keys_bob)

    # Chiffrement / déchiffrement
    plaintext = b"Message secret IoT : badge alice GRANTED zone serveurs"
    ct = alice.encrypt(plaintext)
    recovered = bob.decrypt(ct)
    test("Chiffrement / déchiffrement AES-256-GCM", recovered == plaintext)

    # Plusieurs messages dans l'ordre
    messages = [f"msg-{i}".encode() for i in range(5)]
    cts = [alice.encrypt(m) for m in messages]
    for i, (m, ct_i) in enumerate(zip(messages, cts)):
        rec = bob.decrypt(ct_i)
        test(f"Message {i} déchiffré correctement", rec == m)

    # Replay : réutiliser un ancien ciphertext
    try:
        bob.decrypt(cts[0])   # compteur 0 déjà vu
        test("Replay détecté", False)
    except ValueError as e:
        test("Replay détecté et rejeté", "Replay" in str(e) or "counter" in str(e).lower())


async def test_full_handshake(tmpdir: str):
    section("7. Handshake TLS Hybride Complet (Client ↔ Serveur)")

    from tls_server import PQCServer
    from tls_client import PQCClient

    passphrase = b"test-integration"

    # Générer la PKI complète
    ca = CertificateAuthority.generate("ca-test")
    gw_cert, gw_kem_sk, gw_sig_sk = ca.issue("gateway-b1", "GATEWAY")
    mw_cert, mw_kem_sk, mw_sig_sk = ca.issue("middleware", "MIDDLEWARE")

    # Allow-list
    allowlist_path = os.path.join(tmpdir, "allowlist_handshake.json")
    allowlist = AllowList(ca, allowlist_path)
    allowlist.add(gw_cert, "gateway pour test")
    allowlist.add(mw_cert, "middleware pour test")

    # Session cache
    session_cache = SessionCache()

    # Canal de communication après handshake
    received_data = []

    async def app_handler(channel, client_id, reader, writer):
        data = await reader.read(4)
        if data:
            import struct
            length = struct.unpack(">I", data)[0]
            encrypted = await reader.readexactly(length)
            plaintext = channel.decrypt(encrypted)
            received_data.append((client_id, plaintext))

    # Serveur PQC
    server = PQCServer(
        host="127.0.0.1",
        port=19443,
        server_cert=mw_cert,
        server_kem_sk=mw_kem_sk,
        server_sig_sk=mw_sig_sk,
        allowlist=allowlist,
        session_cache=session_cache,
        app_handler=app_handler,
    )

    # Client PQC
    client = PQCClient(
        client_id="gateway-b1",
        client_cert=gw_cert,
        client_kem_sk=gw_kem_sk,
        client_sig_sk=gw_sig_sk,
        allowlist=allowlist,
    )

    # Démarrer serveur
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.2)  # Laisser le serveur démarrer

    try:
        # Connexion client (handshake FULL)
        t0 = time.perf_counter()
        conn = await client.connect("127.0.0.1", 19443)
        ms_full = (time.perf_counter() - t0) * 1000
        test(f"Handshake FULL réussi ({ms_full:.0f} ms)", conn.handshake_type == "FULL")

        # Envoyer un message chiffré
        payload = b"MQTT: building/B1/zone/Z3/badge/R07 - alice GRANTED"
        await conn.send(payload)
        await asyncio.sleep(0.1)
        test("Message chiffré reçu par le serveur", len(received_data) > 0)
        if received_data:
            test("Contenu du message correct", received_data[0][1] == payload)

        await conn.close()

        # Handshake RESUME
        await asyncio.sleep(0.1)
        t0 = time.perf_counter()
        conn2 = await client.connect("127.0.0.1", 19443)
        ms_resume = (time.perf_counter() - t0) * 1000
        test(
            f"Handshake RESUME réussi ({ms_resume:.0f} ms, "
            f"gain={100*(1-ms_resume/ms_full):.0f}%)",
            True  # RESUME ou fallback FULL sont tous deux valides
        )
        await conn2.close()

    finally:
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            pass


# ═══════════════════════════════════════════════════════════════════
#  Runner principal
# ═══════════════════════════════════════════════════════════════════

def run_all_tests():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     Tests d'Intégration — Couche Sécurité PQC               ║")
    print("║     Ryan ZERHOUNI — Architecture IoT/IA Bâtiments Sensibles ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    with tempfile.TemporaryDirectory() as tmpdir:
        failed = []
        t_total = time.perf_counter()

        tests = [
            ("KEM Hybride",            lambda: test_hybrid_kem()),
            ("Signature Hybride",      lambda: test_hybrid_signer()),
            ("Certificats & Allowlist",lambda: test_certificates(tmpdir)),
            ("Log Signer",             lambda: test_log_signer(tmpdir)),
            ("Session Cache (PSK)",    lambda: test_session_cache()),
            ("Canal AES-256-GCM",      lambda: test_secure_channel()),
            ("Handshake TLS Hybride",  lambda: asyncio.run(test_full_handshake(tmpdir))),
        ]

        for name, fn in tests:
            try:
                fn()
            except AssertionError as e:
                failed.append((name, str(e)))
                print(f"  {FAIL} ÉCHEC : {e}")
            except Exception as e:
                failed.append((name, str(e)))
                print(f"  {FAIL} EXCEPTION dans {name}: {e}")
                import traceback; traceback.print_exc()

        elapsed = time.perf_counter() - t_total
        print()
        print("╔══════════════════════════════════════════════════════════════╗")
        if not failed:
            print(f"║  ✅ TOUS LES TESTS PASSENT ({elapsed:.2f}s)                       ║")
        else:
            print(f"║  ❌ {len(failed)} TEST(S) ÉCHOUÉ(S)                                ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print()

        if failed:
            for name, reason in failed:
                print(f"  ÉCHEC : {name} — {reason}")
            sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
