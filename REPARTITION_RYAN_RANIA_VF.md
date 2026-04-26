# Répartition du travail — Ryan & Rania (Security & PQC, 30%)

> **Référence :** [ARCHITECTURE.md](./ARCHITECTURE.md) — Section 4 (Security Layer) + Section 15 (Roles)
> **Charge globale du binôme :** 30% du projet (15% chacun)

---

## Vue d'ensemble

Le périmètre Security & PQC couvre **4 grands blocs fonctionnels** :

| Bloc | Description |
|------|-------------|
| **Double Proxy** | Forward Proxy (côté Gateway) + Reverse Proxy (côté Middleware) avec terminaison PQC |
| **Handshake TLS 1.3 hybride** | Échange de clés X25519MLKEM768 + Session Resumption PSK+DHE |
| **Certificats & mTLS** | CA hybride, génération de certificats ECC-hybrid-MLDSA5, allowlist mTLS |
| **Signature des logs** | Signature PQC des logs avec ECC-hybrid-MLDSA5 + stockage sécurisé des clés |

La répartition sépare le **transport** (tunnel chiffré) de l'**identité** (certificats, authentification, signature).

---

## 🔧 Ryan Zerhouni — PQC Transport & Tunnel Lead (15%)

### Rôle
Responsable de la mise en place du **tunnel PQC de bout en bout** entre la zone IoT et le Middleware, via le double proxy Nginx/OQS.

### Missions détaillées

| # | Mission | Détail |
|---|---------|--------|
| 1 | **Forward Proxy (Gateway side)** | Configuration Nginx compilé avec OQS-provider. Interception des flux locaux MQTT/HTTP et encapsulation dans le tunnel TLS/PQC sortant. |
| 2 | **Reverse Proxy (Middleware side)** | Terminaison du tunnel PQC entrant, vérification de l'identité client, redirection du trafic déchiffré vers Mosquitto Broker / Node-RED. |
| 3 | **Handshake TLS 1.3 hybride** | Configuration du key group `X25519MLKEM768` dans OpenSSL 3.x + OQS-provider. Validation du handshake complet (ClientHello → ServerHello → session AES-256-GCM). |
| 4 | **Session Resumption (PSK+DHE)** | Activation du mécanisme de reprise de session TLS 1.3 en mode hybride : PSK dérivé du secret ML-KEM-768 initial + échange éphémère X25519 sur chaque reconnexion. |
| 5 | **Segmentation réseau Docker** | Configuration des Docker Networks isolés (`internal: true`) pour garantir que le tunnel PQC est le seul vecteur de communication entre le périmètre IoT et le périmètre Middleware. |
| 6 | **Tests de performance** | Mesure de la latence du handshake complet vs. session resumption. Validation du gain de 90% annoncé dans l'architecture. |

### Fichiers sous responsabilité

```
infra/
├── forward-proxy/
│   ├── Dockerfile            ← Build Nginx + OQS-provider
│   └── nginx.conf            ← Config proxy sortant + TLS/PQC (X25519MLKEM768)
├── reverse-proxy/
│   ├── Dockerfile
│   └── nginx.conf            ← Config proxy entrant + terminaison PQC
└── docker-compose.yml        ← Sections forward-proxy, reverse-proxy, réseaux isolés
```

> **Note :** pas de scripts Python `tls_client.py` / `tls_server.py` — le TLS/PQC est entièrement géré par **Nginx compilé avec OQS-provider**. La configuration se fait dans les `nginx.conf`.

### Livrables

- [ ] Forward Proxy fonctionnel (Nginx/OQS) avec tunnel PQC sortant
- [ ] Reverse Proxy fonctionnel avec terminaison PQC et redirection
- [ ] Handshake X25519MLKEM768 validé (capture Wireshark ou logs OpenSSL)
- [ ] Session Resumption PSK+DHE fonctionnelle (mesure du gain de latence)
- [ ] Docker Networks segmentés (`internal: true`) opérationnels
- [ ] Documentation des tests de performance (latence handshake vs. resumption)

---

## 🔐 Rania El haddaoui — PQC Identity & Integrity Lead (15%)

### Rôle
Responsable de la **chaîne de confiance cryptographique** : génération des certificats hybrides, authentification mutuelle, et signature PQC des logs.

### Missions détaillées

| # | Mission | Détail |
|---|---------|--------|
| 1 | **CA hybride (PKI-free)** | Génération du certificat racine et de la clé privée hybride ECC-hybrid-MLDSA5 avec `liboqs` + `oqs-python`. Pas de PKI externe : modèle allow-list. |
| 2 | **Certificats Gateway & Middleware** | Génération des certificats d'identité pour le Gateway et le Middleware, signés par la CA hybride. Clés privées ECC-hybrid-MLDSA5. |
| 3 | **mTLS Allowlist** | Implémentation du mécanisme d'authentification mutuelle sans PKI : fichier `allowlist.json` listant les certificats autorisés. Validation croisée Gateway ↔ Middleware. |
| 4 | **Stockage sécurisé des clés** | Chiffrement des fichiers `.pem` avec AES-256 + passphrase. Permissions 600. Script de provisioning au premier démarrage. |
| 5 | **Signature PQC des logs** | Implémentation de `log_signer.py` : double signature ECC-hybrid-MLDSA5 (ECDSA P-384 ∥ ML-DSA-5) de chaque entrée de log. Vérification d'intégrité. |
| 6 | **Choix du schéma de signature devices** | Décision technique : ECC-hybrid-MLDSA5 (cohérent avec les logs, plus lourd) vs. ML-DSA-65 (plus léger) pour les certificats devices. Justification documentée. |

### Fichiers sous responsabilité

```
security/
├── ca/
│   ├── ca.crt                ← Certificat racine (ECC-hybrid-MLDSA5)
│   └── ca.key                ← Clé privée racine (chiffrée AES-256)
├── gateway/
│   ├── gateway.crt           ← Certificat d'identité Gateway
│   └── gateway.key           ← Clé privée hybride (perm. 600)
├── middleware/
│   ├── middleware.crt        ← Certificat d'identité Middleware
│   └── middleware.key        ← Clé privée hybride
├── allowlist.json            ← Liste des certificats autorisés (mTLS)
├── log_signer.py             ← Signature ECC-hybrid-MLDSA5 des logs
└── gen_certs.py              ← [NEW] Script de génération des certificats
```

### Livrables

- [ ] CA hybride fonctionnelle (certificat racine + clé ECC-hybrid-MLDSA5)
- [ ] Certificats Gateway et Middleware générés et signés par la CA
- [ ] Allowlist mTLS opérationnelle (authentification mutuelle validée)
- [ ] Clés `.pem` chiffrées AES-256 avec provisioning automatique
- [ ] `log_signer.py` : signature + vérification des logs fonctionnelles
- [ ] Note technique sur le choix ML-DSA-5 vs. ML-DSA-65 pour les devices

---

## Synthèse comparative

| Critère | Ryan | Rania |
|---------|------|-------|
| **Périmètre** | Transport & Tunnel | Identité & Intégrité |
| **Charge** | 15% | 15% |
| **Technos principales** | Nginx, OQS-provider, Docker Networks | liboqs, oqs-python, OpenSSL |
| **Algorithme principal** | X25519MLKEM768 (KEM) | ECC-hybrid-MLDSA5 (Signature) |
| **Focus** | Performance du tunnel, latence | Chaîne de confiance, non-répudiation |
| **Nb de livrables** | 6 | 6 |

---

## Dépendances croisées

```
Rania génère les certificats ──► Ryan les utilise dans la config Nginx
     (ca.crt, gateway.crt,          (ssl_certificate, ssl_certificate_key
      middleware.crt)                 dans nginx.conf)

Ryan fournit le tunnel TLS ──► Rania valide le mTLS de bout en bout
     (forward + reverse proxy)       (allowlist.json vérifié en conditions réelles)
```

> **Point de synchronisation :** les certificats de Rania doivent être générés **avant** que Ryan puisse tester le tunnel complet. Prévoir une livraison intermédiaire des certs en priorité.

---

*Document créé le 26/04/2026*
