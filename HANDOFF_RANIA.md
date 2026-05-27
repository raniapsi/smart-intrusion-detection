# Passation Technique — Ryan → Rania
**De :** Ryan ZERHOUNI (PQC Transport & Tunnel Lead)
**Pour :** Rania El Haddaoui (PQC Identity & Integrity Lead)
**Date :** 01/05/2026

---

## 1. Résumé de ce que j'ai fait

J'ai mis en place **l'intégralité du tunnel de transport Post-Quantique** entre la zone IoT (Edge/Gateway) et le Cloud (Middleware). Concrètement, j'ai créé un "tuyau sécurisé" qui traverse Internet et qui est déjà résistant aux ordinateurs quantiques.

### Ce qui est opérationnel aujourd'hui :

| Composant | Statut | Détail |
|-----------|--------|--------|
| **Forward Proxy** (côté Mac/Edge) | ✅ Fonctionnel | Nginx compilé avec OQS-provider, encapsule MQTT dans un WebSocket chiffré PQC |
| **Reverse Proxy** (côté VM Oracle) | ✅ Fonctionnel | Termine le tunnel PQC, redirige vers Mosquitto |
| **Tunnel PQC X25519MLKEM768** | ✅ Validé | TLS 1.3 avec échange de clés hybride (classique + post-quantique) |
| **Session Resumption (PSK+DHE)** | ✅ Mesuré | Gain de latence de ~56% sur les reconnexions |
| **Segmentation réseau Docker** | ✅ Isolé | `iot-net` (interne, Edge), `internet-net` (transit), `middleware-net` (interne, Cloud) |
| **Broker Mosquitto** | ✅ Isolé | Ne voit jamais l'IP publique, communique uniquement avec le Reverse Proxy |

---

## 2. Architecture en place

```
[Capteur IoT]                                              [Mosquitto Broker]
     │                                                            ▲
     │ MQTT (clair)                                               │ MQTT (clair)
     ▼                                                            │
┌─────────────────┐        internet-net            ┌──────────────────────┐
│  Forward Proxy  │ ──── Tunnel PQC (TLS 1.3) ───► │   Reverse Proxy      │
│  (Edge / Mac)   │    X25519MLKEM768 + mTLS       │   (Cloud / VM Oracle)│
│  Port 9001      │                                │   Port 8443          │
└─────────────────┘                                └──────────────────────┘
   Réseau: iot-net                                    Réseau: middleware-net
   (internal: true)                                   (internal: true)
```

---

## 3. Où interviennent TES certificats dans MON infrastructure

C'est le point le plus important. Mon tunnel **fonctionne déjà** avec des certificats temporaires, mais **ta partie va le sécuriser pour de vrai** en ajoutant l'authentification mutuelle (mTLS).

### Fichiers que tu dois me fournir :

```
security/
├── ca/
│   └── ca.crt                 ← Le certificat racine de ta CA hybride
├── gateway/
│   ├── gateway.crt            ← Certificat du Forward Proxy (signé par ta CA)
│   └── gateway.key            ← Clé privée hybride du Forward Proxy
└── middleware/
    ├── middleware.crt          ← Certificat du Reverse Proxy (signé par ta CA)
    └── middleware.key          ← Clé privée hybride du Reverse Proxy
```

### Comment je les utilise dans mes fichiers Nginx :

**Dans `infra/reverse-proxy/nginx.conf`** (côté Cloud) :
```nginx
ssl_certificate /etc/nginx/certs/middleware.crt;         # ← TON certificat
ssl_certificate_key /etc/nginx/certs/middleware.key;       # ← TA clé privée

ssl_client_certificate /etc/nginx/certs/ca.crt;           # ← TON CA (pour vérifier le client)
ssl_verify_client on;                                      # ← Active le mTLS
```

**Dans `infra/forward-proxy/nginx.conf`** (côté Edge) :
```nginx
proxy_ssl_certificate /etc/nginx/certs/gateway.crt;       # ← TON certificat
proxy_ssl_certificate_key /etc/nginx/certs/gateway.key;     # ← TA clé privée
```

**Dans `infra/docker-compose-cloud.yml`** (volumes montés) :
```yaml
volumes:
  - ../security/middleware/middleware.crt:/etc/nginx/certs/middleware.crt:ro
  - ../security/middleware/middleware.key:/etc/nginx/certs/middleware.key:ro
  - ../security/ca/ca.crt:/etc/nginx/certs/ca.crt:ro
```

> [!IMPORTANT]
> **Les noms des fichiers et les chemins sont déjà câblés dans ma config.** Tu dois respecter exactement cette arborescence (`security/ca/`, `security/gateway/`, `security/middleware/`) et ces noms de fichiers.

---

## 4. Contraintes techniques à respecter

### 4.1. Format des certificats
- **Format PEM** (texte, pas DER/binaire)
- Les certificats doivent être signés avec ton algorithme hybride **ECC-hybrid-MLDSA5**
- Le `Common Name` (CN) du certificat middleware peut être ce que tu veux (ex: `middleware.iot.local`), car notre config Nginx n'a pas de `server_name` défini — il n'y a pas de vérification hostname

### 4.2. Compatibilité avec l'image Docker OQS
Mon infrastructure utilise l'image **`openquantumsafe/nginx:latest`** qui embarque déjà :
- OpenSSL 3.x avec le provider OQS
- Support natif de X25519MLKEM768 (KEM)
- Support natif de ECC-hybrid-MLDSA5 (signatures)

Tu peux donc utiliser cette même image pour tester tes certificats :
```bash
docker run --rm -v $(pwd)/security:/certs openquantumsafe/curl \
  openssl verify -CAfile /certs/ca/ca.crt /certs/gateway/gateway.crt
```

### 4.3. Permissions des clés
- Les fichiers `.key` doivent avoir les permissions `600` (lecture seule par le propriétaire)
- Docker les monte en `:ro` (read-only), donc aucun risque d'écriture accidentelle

---

## 5. Comment tester que tes certificats fonctionnent avec mon tunnel

Une fois que tu auras généré tes certificats et les auras placés dans `security/`, voici la procédure de test :

### Étape 1 : Redémarrer l'infrastructure
```bash
# Sur la VM Oracle
cd ~/iot/infra
sudo docker compose -f docker-compose-cloud.yml down
sudo docker compose -f docker-compose-cloud.yml up -d

# Sur le Mac
cd infra/
docker compose -f docker-compose-edge.yml down
docker compose -f docker-compose-edge.yml up -d
```

### Étape 2 : Lancer le test du tunnel
```bash
./test_tunnel.sh
```

### Étape 3 : Vérifier le mTLS
Si le mTLS fonctionne, tu verras `CONNACK (0)`. Si tes certificats sont rejetés, tu verras une erreur `SSL handshake failure` dans les logs du Reverse Proxy :
```bash
sudo docker logs reverse-proxy-cloud
```

---

## 6. Ce que tu n'as PAS besoin de toucher

| Fichier / Composant | Responsabilité |
|---------------------|---------------|
| `infra/forward-proxy/nginx.conf` | Ryan (ne modifie pas) |
| `infra/reverse-proxy/nginx.conf` | Ryan (ne modifie pas) |
| `infra/docker-compose-cloud.yml` | Ryan (ne modifie pas) |
| `infra/docker-compose-edge.yml` | Ryan (ne modifie pas) |
| `infra/mosquitto/mosquitto.conf` | Ryan (ne modifie pas) |
| `infra/test_tunnel.sh` | Ryan (tu peux l'utiliser pour tester) |
| `infra/test_performance.sh` | Ryan (tu peux l'utiliser pour tester) |

**Ton périmètre est exclusivement dans le dossier `security/`.**

---

## 7. Points de synchronisation

| Quand | Quoi | Comment |
|-------|------|---------|
| **Dès que tes certs sont prêts** | Tu me préviens | Je relance l'infra et on teste ensemble |
| **Si tu veux tester ton intégrité** | Tu utilises `test_tunnel.sh` | Il génère du vrai trafic MQTT qui traverse le tunnel PQC |

---

*Document de passation créé le 01/05/2026 par Ryan ZERHOUNI*
