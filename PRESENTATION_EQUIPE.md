# 🛡️ Ce que j'ai mis en place — Présentation Équipe
**Par :** Ryan ZERHOUNI
**Date :** 01/05/2026
**Pour :** Ilyes, Sam, Alban, Rania — Réunion d'équipe du mercredi

---

## En une phrase

J'ai construit un **tunnel sécurisé invisible** entre vos capteurs IoT et le Cloud. Vos données voyagent désormais dans un tuyau blindé que même un futur ordinateur quantique ne pourra pas casser.

---

## 1. Le problème qu'on résout

Imaginez que vos capteurs (badges, portes, caméras) envoient des alertes au serveur Cloud. Sans protection, un attaquant pourrait :
- **Espionner** les messages en transit (savoir qui entre où, à quelle heure)
- **Modifier** les alertes (supprimer une alerte d'intrusion avant qu'elle n'arrive au dashboard)
- **Enregistrer** tout le trafic aujourd'hui et le déchiffrer dans 10 ans avec un ordinateur quantique ("Harvest Now, Decrypt Later")

**Ma solution** : un tunnel chiffré Post-Quantique (PQC) qui protège contre ces trois menaces, y compris les futures.

---

## 2. Comment ça marche (Version Simple)

```
                        🔒 TUNNEL PQC (Internet)
                        ========================
Votre Mac                                              VM Oracle Cloud
┌──────────┐     ┌──────────┐          ┌──────────┐     ┌──────────┐
│ Capteur  │────►│ Garde du │══════════│ Garde du │────►│ Mosquitto│
│ (MQTT)   │     │ Portail  │  Chiffré │ Château  │     │ (Broker) │
└──────────┘     │ (Forward │  PQC     │ (Reverse │     └──────────┘
                 │  Proxy)  │          │  Proxy)  │
                 └──────────┘          └──────────┘
```

**Analogie :** Pensez à un service de transport de fonds blindé.
- Le **Forward Proxy** est le garde qui met votre colis (message MQTT) dans le camion blindé.
- Le **tunnel PQC** est le camion blindé lui-même (personne ne peut voir ou toucher le contenu).
- Le **Reverse Proxy** est le garde à l'arrivée qui ouvre le camion et livre le colis à Mosquitto.
- **Mosquitto** ne sait même pas qu'il y avait un camion : il reçoit le colis comme si de rien n'était.

---

## 3. Ce qui change pour VOUS (Impact par rôle)

### 👨‍💻 Pour Ilyes, Sam, Alban (Simulation, IA, Dashboard)

| Question | Réponse |
|----------|---------|
| **Est-ce que je dois modifier mon code ?** | **Non.** Le tunnel est transparent. Vos capteurs publient en MQTT comme avant, le tunnel s'occupe du reste. |
| **Est-ce que ça ralentit le système ?** | **Presque pas.** La première connexion prend ~50ms de plus. Les suivantes sont optimisées grâce au "Session Resumption" (~25ms). |
| **Est-ce que mes messages MQTT changent de format ?** | **Non.** Le JSON reste identique. Le tunnel ne touche pas au contenu, il protège juste le transport. |
| **Est-ce que le dashboard doit afficher quelque chose ?** | **Optionnel.** Vous pourriez afficher un indicateur "🟢 Tunnel PQC Actif" si vous voulez, mais ce n'est pas obligatoire. |

### 📡 Pour la partie IoT (Capteurs / Simulation)

Vos capteurs doivent publier leurs messages MQTT **vers le Forward Proxy** (port `9001`), pas directement vers le Cloud. Le tunnel s'occupe du reste.

```
# Exemple de publication depuis un capteur (ou un script de simulation) :
mosquitto_pub -h forward-proxy-edge -p 9001 -t "alerts/intrusion" -m '{"badge":"A12","zone":"B3"}' --ws
```

| Paramètre | Valeur | Pourquoi |
|-----------|--------|----------|
| **Host** | `forward-proxy-edge` (en Docker) ou `localhost` (depuis le Mac) | Le Forward Proxy est votre unique point d'entrée |
| **Port** | `9001` | Le port WebSocket du proxy |
| **Option** | `--ws` | Obligatoire : le tunnel utilise MQTT-over-WebSocket |
| **Topic** | Ce que vous voulez (`alerts/intrusion`, `sensors/door`, etc.) | Le tunnel est transparent, tous les topics passent |

> **En résumé :** Changez juste le **host** de vos clients MQTT pour pointer vers `forward-proxy-edge:9001` au lieu de `mosquitto:1883`. C'est le seul changement.

### 🖥️ Pour la partie Middleware (Node-RED / Dashboard)

Vos services (Node-RED, dashboard, IA) tournent **côté Cloud** dans le même réseau Docker que Mosquitto. Vous vous connectez à Mosquitto **directement**, comme avant.

```
# Exemple de souscription depuis un container Cloud (Node-RED, etc.) :
mosquitto_sub -h mosquitto -p 9001 -t "alerts/#" --ws
```

| Paramètre | Valeur | Pourquoi |
|-----------|--------|----------|
| **Host** | `mosquitto` (nom Docker du broker) | Vous êtes dans le même réseau `middleware-net` |
| **Port** | `9001` | Le port WebSocket de Mosquitto |
| **Option** | `--ws` | WebSocket activé dans la config Mosquitto |

> **En résumé :** Rien ne change pour vous ! Mosquitto reçoit les messages des capteurs de manière transparente via le tunnel. Vous n'avez même pas besoin de savoir que le tunnel existe.

---

## 4. Architecture Réseau (Ce qui est isolé)

```
┌─────────────────────────────────────────────────┐
│                 VM ORACLE CLOUD                  │
│                                                  │
│   ┌───────────────────┐    ┌──────────────────┐  │
│   │  Reverse Proxy    │────│   Mosquitto      │  │
│   │  (Port 8443)      │    │   (Port 9001)    │  │
│   │  🌐 Accessible    │    │   🔒 Isolé       │  │
│   └───────────────────┘    └──────────────────┘  │
│   internet-net             middleware-net         │
│   (bridge)                 (internal: true)       │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│                    VOTRE MAC                     │
│                                                  │
│   ┌──────────────┐    ┌───────────────────────┐  │
│   │  Capteurs    │────│   Forward Proxy       │──── → Internet → Oracle
│   │  (Simulateur)│    │   (Port 9001)         │  │
│   │  🔒 Isolé    │    │   🌐 Sortie autorisée │  │
│   └──────────────┘    └───────────────────────┘  │
│   iot-net              internet-net               │
│   (internal: true)     (bridge)                   │
└─────────────────────────────────────────────────┘
```

**Points clés :**
- ❌ Les capteurs **ne peuvent PAS** joindre Internet directement (réseau `internal: true`)
- ❌ Mosquitto **ne peut PAS** être contacté depuis Internet (pas de port exposé)
- ✅ Le **seul** chemin possible passe par le tunnel PQC via `internet-net` et les deux Proxies

---

## 5. Les preuves que ça marche

J'ai documenté et testé 6 points de validation :

| # | Test | Résultat |
|---|------|----------|
| 1 | Tunnel de bout-en-bout (Mac → Oracle) | ✅ `CONNACK (0)` — Message livré |
| 2 | Algorithme PQC (X25519MLKEM768) | ✅ Confirmé par les logs Nginx |
| 3 | Isolation capteurs (`iot-net`) | ✅ `ping: Network unreachable` |
| 4 | Isolation Mosquitto (`middleware-net`) | ✅ `ping: Network unreachable` |
| 5 | Session Resumption (gain latence) | ✅ ~56% de réduction |
| 6 | Perfect Forward Secrecy (PFS) | ✅ Clé éphémère unique par connexion |

> Pour les détails techniques complets, voir le document `DETAILS_TRANSPORT_PQC.md`.

---

## 6. Glossaire (pour ceux qui veulent comprendre)

| Terme | Explication simple |
|-------|-------------------|
| **PQC** | Post-Quantum Cryptography — Chiffrement résistant aux ordinateurs quantiques |
| **X25519MLKEM768** | Le "cadenas hybride" qu'on utilise : un cadenas classique + un cadenas quantique, les deux en même temps |
| **TLS 1.3** | Le protocole de sécurité d'Internet (celui que votre navigateur utilise pour HTTPS) |
| **mTLS** | Les deux côtés du tunnel se vérifient mutuellement (pas juste le serveur) |
| **Forward Proxy** | Le "garde" côté capteurs qui chiffre les messages sortants |
| **Reverse Proxy** | Le "garde" côté Cloud qui déchiffre les messages entrants |
| **Session Resumption** | Technique pour accélérer les reconnexions (on réutilise un "ticket" au lieu de tout refaire) |
| **MQTT** | Le protocole léger que vos capteurs utilisent pour envoyer des messages |
| **Mosquitto** | Le serveur central qui reçoit tous les messages MQTT |

---

## 7. Questions fréquentes

**Q : Est-ce que le tunnel marche même si Internet est lent ?**
R : Oui. Le protocole MQTT est très léger (quelques octets). Le tunnel ajoute un overhead minimal.

**Q : Que se passe-t-il si le tunnel tombe ?**
R : Les capteurs continuent de publier localement. Dès que le tunnel revient, les messages en attente sont envoyés.

**Q : Est-ce que je dois installer quelque chose sur mon poste ?**
R : Non. Tout tourne dans Docker. Un simple `docker compose up -d` suffit.

**Q : C'est quoi la différence entre le travail de Ryan et celui de Rania ?**
R : Ryan = le **tuyau blindé** (transport). Rania = les **badges d'accès** (certificats d'identité). Le tuyau existe, mais les badges vont garantir que seuls nos capteurs autorisés peuvent l'utiliser.

---

*Document préparé pour la réunion d'équipe du mercredi — Ryan ZERHOUNI*
