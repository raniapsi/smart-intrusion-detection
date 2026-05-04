# Livrable — Rania El Haddaoui : PQC Identity & Integrity

> **Branche :** `rania/pqc-identity`  
> **Charge :** 15% du projet (bloc Identité & Intégrité)  
> **Date :** 4 mai 2026

---

## Vue d'ensemble

Ce document décrit l'ensemble des livrables implémentés dans le cadre du bloc **PQC Identity & Integrity** du projet Smart Intrusion Detection.

L'objectif est de fournir une **chaîne de confiance cryptographique résistante aux ordinateurs quantiques** pour les communications entre le Gateway IoT et le Middleware, en s'appuyant sur l'algorithme hybride **p384_mldsa65** (P-384 + ML-DSA-65).

---

## Algorithme retenu : `p384_mldsa65`

| Composante | Algorithme | Standard |
|-----------|-----------|---------|
| Classique | ECDSA / ECDH P-384 | NIST FIPS 186 |
| Post-quantique | ML-DSA-65 (ex-CRYSTALS-Dilithium 3) | NIST FIPS 204 |
| Niveau de sécurité | NIST Level 3 | ≈ AES-192 |

**Pourquoi hybride ?**  
Si un ordinateur quantique casse P-384 demain, ML-DSA-65 tient. Si liboqs a un bug, P-384 tient. Les deux algorithmes doivent être cassés simultanément pour compromettre la sécurité — c'est le principe de la cryptographie hybride.

**Pourquoi ML-DSA-65 et pas ML-DSA-87 ?**  
ML-DSA-87 (level 5) était l'algorithme initial. Après analyse, ML-DSA-65 (level 3) offre un meilleur équilibre performance/sécurité pour ce cas d'usage (IoT embarqué, latence contrainte), avec une sécurité largement suffisante pour l'horizon post-quantique visé.

---

## Livrables

### 1. CA Hybride PKI-free

**Fichiers :** `security/ca/ca.key`, `security/ca/ca.crt`

Certificat racine auto-signé généré avec l'algorithme `p384_mldsa65` via le container Docker `openquantumsafe/curl` (OpenSSL 3.x + OQS-provider).

```
Signature Algorithm : p384_mldsa65
Subject             : CN=PQC-Root-CA, O=SmartIDS, C=FR
Validity            : 825 jours
```

Pas de PKI externe : modèle **allow-list** — seuls les certificats listés dans `allowlist.json` sont autorisés à se connecter.

---

### 2. Certificats d'identité Gateway & Middleware

**Fichiers :**
- `security/gateway/gateway.key`, `gateway.csr`, `gateway.crt`
- `security/middleware/middleware.key`, `middleware.csr`, `middleware.crt`

Chaque certificat est :
- généré avec une clé privée `p384_mldsa65`
- signé par la CA racine via un CSR
- valide 365 jours

```
Signature Algorithm : p384_mldsa65
Issuer              : CN=PQC-Root-CA (notre CA)
gateway CN          : gateway.iot.local
middleware CN       : middleware.iot.local
```

Ces certificats sont utilisés par Ryan dans la configuration Nginx pour le mTLS (mutual TLS).

---

### 3. mTLS Allowlist

**Fichier :** `allowlist.json`

Mécanisme d'authentification mutuelle sans PKI centrale : le fichier liste les empreintes (fingerprints) des certificats autorisés. Le Gateway et le Middleware vérifient mutuellement leur identité lors de chaque connexion TLS.

---

### 4. Stockage sécurisé des clés

Toutes les clés privées (`.key`) ont des **permissions 600** (lecture réservée au propriétaire uniquement), appliquées automatiquement par `gen_certs.py`.

```bash
-rw------- security/ca/ca.key
-rw------- security/gateway/gateway.key
-rw------- security/middleware/middleware.key
```

---

### 5. Script de génération des certificats

**Fichier :** `security/gen_certs.py`

Script Python qui automatise la génération de toute la chaîne PKI. Utilise Docker (`openquantumsafe/curl`) donc **aucune dépendance locale à installer**.

```bash
# Premier démarrage (génère les certs)
python security/gen_certs.py

# Regénérer (crée un backup automatique daté)
python security/gen_certs.py --force
```

**Ce que fait le script :**
1. Vérifie que Docker est disponible
2. Détecte les certs existants → refuse d'écraser sans `--force`
3. Avec `--force` : backup daté → génération CA → Gateway → Middleware
4. Applique chmod 600 sur toutes les clés
5. Vérifie la chaîne de confiance (`openssl verify`)

---

### 6. Signature PQC des logs

**Fichier :** `security/log_signer.py`

Chaque entrée de log sensible est protégée par une **double signature** :
- **ECDSA P-384** — sécurité classique, interopérable
- **ML-DSA-65** — résistance post-quantique

**Pourquoi signer les logs ?**  
Dans un système de détection d'intrusion, les logs sont la preuve forensique. Un attaquant qui compromet le serveur peut modifier les logs pour effacer ses traces. La signature cryptographique rend toute falsification détectable.

**Structure d'une entrée signée :**

```json
{
  "payload": { "event": "intrusion_detected", "src_ip": "192.168.1.42" },
  "timestamp": "2026-05-04T22:30:00+00:00",
  "digest": "sha256:...",
  "signatures": {
    "ecdsa_p384": "<base64>",
    "mldsa65":    "<base64>"
  }
}
```

**Usage :**

```bash
# Générer les clés de signing (une seule fois)
python security/log_signer.py keygen

# Signer une entrée de log
python security/log_signer.py sign '{"event":"intrusion","src_ip":"1.2.3.4","severity":"high"}'

# Vérifier l'intégrité
python security/log_signer.py verify envelope.json
```

Les clés de signing sont stockées dans `security/log_signing_keys/` (créé par `keygen`, permissions 600).

---

## Dépendance avec Ryan

```
Rania (ce bloc)                    Ryan (PQC Transport)
──────────────────────────────     ──────────────────────────────
ca.crt             ──────────►    ssl_client_certificate (nginx.conf)
gateway.crt        ──────────►    ssl_certificate        (nginx.conf)
middleware.crt     ──────────►    ssl_certificate        (nginx.conf)

                   ◄──────────    tunnel TLS X25519MLKEM768
allowlist.json     ──────────►    vérification mTLS en conditions réelles
```

---

## Arborescence des fichiers

```
security/
├── ca/
│   ├── ca.crt                  ← Certificat CA racine (p384_mldsa65)
│   ├── ca.key                  ← Clé privée CA (chmod 600)
│   └── ca.srl                  ← Numéro de série des certs émis
├── gateway/
│   ├── gateway.crt             ← Certificat d'identité Gateway
│   ├── gateway.csr             ← CSR (peut être supprimé en prod)
│   └── gateway.key             ← Clé privée (chmod 600)
├── middleware/
│   ├── middleware.crt          ← Certificat d'identité Middleware
│   ├── middleware.csr
│   └── middleware.key          ← Clé privée (chmod 600)
├── log_signing_keys/           ← Clés de signature des logs
│   ├── ecdsa_p384.pem          ← Clé privée ECDSA P-384
│   ├── ecdsa_p384_pub.pem      ← Clé publique ECDSA P-384
│   ├── mldsa65.bin             ← Clé privée ML-DSA-65
│   └── mldsa65_pub.bin         ← Clé publique ML-DSA-65
├── backup_*/                   ← Backups datés des anciennes clés
├── gen_certs.py                ← Script de génération PKI
├── log_signer.py               ← Signature PQC des logs
└── allowlist.json              ← Certificats mTLS autorisés
```

---

## Vérification rapide

```bash
# Vérifier l'algorithme des certificats
docker run --rm -v $(pwd)/security:/certs openquantumsafe/curl \
  openssl x509 -in /certs/ca/ca.crt -noout -text \
  | grep "Signature Algorithm"
# → Signature Algorithm: p384_mldsa65

# Tester la signature des logs
DYLD_LIBRARY_PATH=/tmp/liboqs-build/build/lib \
  python security/log_signer.py sign '{"event":"test"}' | \
  python security/log_signer.py verify /dev/stdin
```

---

## Dépendances techniques

| Outil | Usage |
|-------|-------|
| Docker + `openquantumsafe/curl` | Génération des certificats (OpenSSL + OQS-provider) |
| `cryptography` (Python) | Signature ECDSA P-384 dans `log_signer.py` |
| `liboqs-python` + `liboqs` (Homebrew) | Signature ML-DSA-65 dans `log_signer.py` |
