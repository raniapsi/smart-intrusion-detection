# AI Engine — Détection intelligente d'intrusion cyber-physique

> **Projet :** Smart Intrusion Detection  
> **Périmètre :** partie IA / scoring / fusion cyber-physique  
> **Dossier concerné :** `ai-engine/`  
> **Objectif :** transformer des événements IoT normalisés en scores de risque `NORMAL`, `SUSPECT` ou `CRITICAL`.

---

## 1. Contexte dans l'architecture globale

Le projet global vise à sécuriser un bâtiment sensible à partir de données IoT simulées : badgeuses, portes, capteurs de mouvement, caméras et événements réseau. La branche principale décrit une architecture en plusieurs couches : simulation IoT, gateway, sécurité TLS/PQC, middleware, streaming, stockage, moteur IA et dashboard SOC.

La partie **AI Engine** correspond à la couche d'analyse comportementale. Elle reçoit des événements normalisés, extrait des caractéristiques utiles, applique un modèle de détection d'anomalies, complète ce score par des règles explicites, puis fusionne les signaux physiques et cyber pour produire une classification finale.

Dans la version actuelle du code, cette partie est principalement développée en mode **offline** : les événements sont lus depuis des fichiers `.jsonl`, les features sont écrites en `.parquet`, le modèle est entraîné et sauvegardé localement, puis les scénarios d'attaque sont scorés et évalués. Ce fonctionnement offline sert de base expérimentale avant une intégration temps réel avec Kafka, TimescaleDB et le dashboard.

---

## 2. Rôle de l'AI Engine

L'AI Engine répond à la question suivante :

> Est-ce qu'un événement observé dans le bâtiment ressemble à un comportement normal, ou est-ce qu'il présente un risque d'intrusion ?

Pour cela, le moteur combine trois approches :

1. **Détection d'anomalies par Isolation Forest**  
   Le modèle apprend les comportements normaux à partir d'un dataset de référence, puis attribue un score d'anomalie aux nouveaux événements.

2. **Moteur de règles**  
   Des règles déterministes détectent directement certains signaux suspects : porte forcée, badge refusé, accès hors horaires, exfiltration réseau, port scan, etc.

3. **Fusion cyber-physique**  
   Le moteur vérifie si un événement physique suspect et un événement cyber suspect apparaissent dans la même zone et dans une fenêtre temporelle proche. Si oui, le score final est renforcé.

Le résultat final est une classification :

```text
NORMAL   → événement considéré comme normal
SUSPECT  → comportement inhabituel nécessitant une vérification
CRITICAL → intrusion ou attaque probable
```

---

## 3. Structure du dossier `ai-engine/`

```text
ai-engine/
├── pyproject.toml
│
├── schemas/
│   ├── events.py
│   ├── payloads.py
│   ├── alerts.py
│   ├── enums.py
│   └── topology.py
│
├── dataset/
│   ├── cli.py
│   ├── topology/
│   │   ├── building_b1.yaml
│   │   ├── building_b1_mini.yaml
│   │   └── loader.py
│   ├── generators/
│   │   ├── orchestrator.py
│   │   ├── user_day.py
│   │   ├── network.py
│   │   ├── badge.py
│   │   ├── door.py
│   │   ├── motion.py
│   │   └── rng.py
│   └── scenarios/
│       ├── badge_off_hours.py
│       ├── forced_door.py
│       ├── tailgating.py
│       ├── revoked_badge.py
│       ├── hybrid_intrusion.py
│       ├── camera_compromise.py
│       └── credential_theft.py
│
├── features/
│   ├── cli.py
│   ├── extractor.py
│   ├── schema.py
│   ├── temporal.py
│   ├── spatial.py
│   ├── frequency.py
│   ├── network.py
│   ├── baselines.py
│   └── io.py
│
├── models/
│   ├── cli.py
│   ├── isolation_forest.py
│   └── rules_engine.py
│
├── fusion/
│   ├── cli.py
│   ├── correlator.py
│   └── scorer.py
│
├── evaluation/
│   └── metrics.py
│
└── tests/
```

Les dossiers `dataset/output/`, `features/output/`, `models/output/`, `models/trained/` et `fusion/output/` sont générés localement pendant l'exécution. Ils sont normalement ignorés par Git via le `.gitignore`.

---

## 4. Installation

### 4.1 Prérequis

- Python `>= 3.11`
- `pip`
- environnement virtuel recommandé

Le projet utilise notamment :

```text
pydantic
pyyaml
numpy
pandas
pyarrow
scikit-learn
joblib
pytest
```

### 4.2 Création de l'environnement

Depuis la racine du dépôt :

```bash
cd ai-engine
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
pip install -e ".[dev]"
```

Sous Windows PowerShell :

```powershell
cd ai-engine
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
pip install -e ".[dev]"
```

---

## 5. Vue d'ensemble du pipeline IA

Le pipeline complet suit cette logique :

```text
1. Génération d'une baseline normale
   train_normal_30d.jsonl

2. Apprentissage des baselines réseau
   baselines.json

3. Extraction des features d'entraînement
   train_features.parquet

4. Entraînement du modèle Isolation Forest
   isoforest.joblib + isoforest.meta.json

5. Génération des scénarios d'attaque
   test_<scenario>.jsonl + test_<scenario>.truth.json

6. Extraction des features des scénarios
   test_<scenario>.parquet

7. Scoring IA + règles
   test_<scenario>.scored.parquet

8. Fusion cyber-physique
   test_<scenario>.fused.parquet

9. Évaluation finale
   eval_summary.csv
```

---

## 6. Données d'entrée : événements normalisés

Les événements sont stockés au format `.jsonl` : un événement JSON par ligne.

Un événement contient par exemple :

```json
{
  "event_id": "...",
  "event_type": "BADGE_ACCESS",
  "source_layer": "PHYSICAL",
  "timestamp": "2026-04-01T08:42:00Z",
  "building_id": "B1",
  "zone_id": "Z2",
  "device_id": "BR-02",
  "user_id": "u001",
  "severity_raw": "INFO",
  "payload": {
    "kind": "BADGE_ACCESS",
    "badge_id": "b001",
    "access_result": "GRANTED"
  },
  "ai_score": null,
  "ai_classification": null
}
```

Les événements peuvent provenir de la couche physique ou cyber :

```text
PHYSICAL → badge, porte, mouvement
CYBER    → flux réseau, anomalie réseau
```

---

## 7. Génération du dataset

### 7.1 Générer une journée simple pour un utilisateur

Commande utile pour tester rapidement le générateur :

```bash
python -m dataset.cli generate-one-day \
  --topology dataset/topology/building_b1_mini.yaml \
  --user u001 \
  --day 2026-04-01 \
  --seed 42 \
  --out dataset/output/sample_one_day.jsonl
```

Cette commande génère une journée de travail simulée pour un utilisateur, avec des événements comme :

```text
BADGE_ACCESS
DOOR_OPENED
MOTION_DETECTED
DOOR_CLOSED
```

### 7.2 Générer une baseline normale sur 30 jours

Cette étape crée le dataset normal utilisé pour entraîner le modèle.

```bash
python -m dataset.cli generate-baseline \
  --topology dataset/topology/building_b1.yaml \
  --start 2026-04-01 \
  --days 30 \
  --seed 42 \
  --out dataset/output/train_normal_30d.jsonl
```

Ce fichier représente le comportement normal du bâtiment : accès habituels, déplacements utilisateurs, activité réseau normale des caméras, etc.

### 7.3 Générer tous les scénarios d'attaque

```bash
python -m dataset.cli generate-all-scenarios \
  --topology dataset/topology/building_b1.yaml \
  --seed 42 \
  --out-dir dataset/output
```

Cela génère les fichiers suivants :

```text
dataset/output/test_badge_off_hours.jsonl
dataset/output/test_badge_off_hours.truth.json

dataset/output/test_forced_door.jsonl
dataset/output/test_forced_door.truth.json

dataset/output/test_tailgating.jsonl
dataset/output/test_tailgating.truth.json

dataset/output/test_revoked_badge.jsonl
dataset/output/test_revoked_badge.truth.json

dataset/output/test_hybrid_intrusion.jsonl
dataset/output/test_hybrid_intrusion.truth.json

dataset/output/test_camera_compromise.jsonl
dataset/output/test_camera_compromise.truth.json

dataset/output/test_credential_theft.jsonl
dataset/output/test_credential_theft.truth.json
```

Les fichiers `.truth.json` contiennent la vérité terrain : événements réellement liés à l'attaque, fenêtre temporelle, zone ciblée, utilisateur ciblé et score attendu.

### 7.4 Générer un seul scénario

Exemple avec `forced_door` :

```bash
python -m dataset.cli generate-scenario \
  --topology dataset/topology/building_b1.yaml \
  --scenario forced_door \
  --seed 42 \
  --out-dir dataset/output
```

Scénarios disponibles :

```text
badge_off_hours
forced_door
tailgating
revoked_badge
hybrid_intrusion
camera_compromise
credential_theft
```

---

## 8. Extraction des features

Le modèle IA ne s'entraîne pas directement sur les événements JSON bruts. Les événements sont d'abord transformés en colonnes numériques appelées **features**.

Cette transformation est faite par :

```text
features/extractor.py
features/schema.py
features/temporal.py
features/spatial.py
features/frequency.py
features/network.py
```

### 8.1 Apprendre les baselines réseau

Avant d'extraire les features réseau, on calcule les moyennes et écarts-types normaux des équipements réseau à partir de la baseline normale.

```bash
python -m features.cli learn-baselines \
  --events dataset/output/train_normal_30d.jsonl \
  --out features/output/baselines.json
```

Le fichier `baselines.json` contient les profils réseau normaux, par exemple pour chaque caméra :

```text
volume moyen de bytes_out
volume moyen de bytes_in
nombre moyen de ports destination
écart-type associé
nombre d'observations
```

Ces valeurs servent ensuite à calculer des z-scores réseau.

### 8.2 Extraire les features d'entraînement

```bash
python -m features.cli extract \
  --events dataset/output/train_normal_30d.jsonl \
  --topology dataset/topology/building_b1.yaml \
  --baselines features/output/baselines.json \
  --out features/output/train_features.parquet
```

Le fichier `train_features.parquet` est le vrai fichier utilisé pour entraîner l'Isolation Forest.

### 8.3 Extraire les features d'un scénario

Exemple pour `forced_door` :

```bash
python -m features.cli extract \
  --events dataset/output/test_forced_door.jsonl \
  --topology dataset/topology/building_b1.yaml \
  --baselines features/output/baselines.json \
  --out features/output/test_forced_door.parquet
```

### 8.4 Extraire les features pour tous les scénarios

```bash
for sc in badge_off_hours forced_door tailgating revoked_badge hybrid_intrusion camera_compromise credential_theft; do
  python -m features.cli extract \
    --events dataset/output/test_${sc}.jsonl \
    --topology dataset/topology/building_b1.yaml \
    --baselines features/output/baselines.json \
    --out features/output/test_${sc}.parquet
done
```

---

## 9. Quelles features sont utilisées ?

Les features sont définies dans :

```text
features/schema.py
```

Elles sont organisées en plusieurs familles.

### 9.1 Colonnes d'identité

Elles ne servent pas directement à l'Isolation Forest, mais elles permettent de relier les résultats aux événements d'origine.

```text
event_id
timestamp
event_type
source_layer
zone_id
device_id
user_id
```

### 9.2 Features temporelles

```text
hour_sin
hour_cos
day_of_week
is_weekend
is_within_typical_hours
minutes_off_typical_midshift
```

Elles permettent de détecter des comportements temporellement inhabituels, par exemple un badge à 3h du matin.

### 9.3 Features spatiales

```text
zone_sensitivity_lvl
is_typical_zone_for_user
entity_count
```

Elles indiquent si la zone est sensible, si l'utilisateur est habituellement autorisé ou attendu dans cette zone, et si plusieurs personnes sont détectées par un capteur de mouvement.

### 9.4 Features de fréquence

```text
events_user_last_1h
events_user_last_24h
events_zone_last_5min
events_zone_last_1h
denied_badges_user_last_5min
denied_badges_zone_last_5min
```

Ces features représentent une forme de **mémoire courte**. Le modèle ne lit pas toute la séquence passée, mais il reçoit un résumé de ce qui s'est passé récemment.

### 9.5 Features réseau

```text
bytes_out
bytes_in
distinct_dst_ports
bytes_out_zscore_device
bytes_in_zscore_device
distinct_dst_ports_zscore_device
dst_is_external
```

Ces features servent à repérer des comportements réseau inhabituels : exfiltration, port scan, destination externe, trafic anormal d'une caméra, etc.

---

## 10. Entraînement du modèle IA

### 10.1 Fichier concerné

Le modèle IA est défini dans :

```text
models/isolation_forest.py
```

La classe `IsolationForest` vient de la bibliothèque `scikit-learn` :

```python
from sklearn.ensemble import IsolationForest
```

Le projet ne réimplémente donc pas l'algorithme Isolation Forest. Il utilise l'implémentation de `scikit-learn` et l'adapte au contexte du projet.

### 10.2 Ce qu'on entraîne réellement

On n'entraîne pas le modèle sur les fichiers `.jsonl` bruts.

On entraîne le modèle sur :

```text
features/output/train_features.parquet
```

Ce fichier contient les features numériques extraites depuis :

```text
dataset/output/train_normal_30d.jsonl
```

L'entraînement consiste à apprendre la distribution normale des features.

Exemple :

```text
Alice badge souvent entre 8h et 18h
Bob accède parfois à la server room
une caméra donnée envoie normalement un certain volume réseau
les accès refusés sont rares
les flux vers l'extérieur sont rares
```

Le modèle ne retient pas chaque événement individuellement. Il construit une structure statistique permettant d'identifier les points faciles à isoler, donc potentiellement anormaux.

### 10.3 Commande d'entraînement

```bash
python -m models.cli train \
  --features features/output/train_features.parquet \
  --out models/trained/isoforest.joblib
```

Paramètres optionnels :

```bash
python -m models.cli train \
  --features features/output/train_features.parquet \
  --out models/trained/isoforest.joblib \
  --n-estimators 200 \
  --contamination 0.01 \
  --seed 42
```

Signification :

```text
--n-estimators  : nombre d'arbres dans la forêt
--contamination : proportion attendue d'anomalies dans les données d'entraînement
--seed          : reproductibilité
```

### 10.4 Fichiers générés

Après entraînement :

```text
models/trained/isoforest.joblib
models/trained/isoforest.meta.json
```

`isoforest.joblib` contient le modèle entraîné sauvegardé.

`isoforest.meta.json` contient des métadonnées utiles :

```text
colonnes utilisées pour l'entraînement
nombre d'échantillons d'entraînement
valeurs de calibration
contamination
nombre d'arbres
```

### 10.5 Est-ce que le modèle relit `train_normal_30d.jsonl` à chaque exécution ?

Non.

Il y a deux phases différentes :

```text
Phase 1 — entraînement
train_normal_30d.jsonl → train_features.parquet → isoforest.joblib

Phase 2 — détection
nouveaux événements → features → chargement de isoforest.joblib → score_if
```

Le fichier `train_normal_30d.jsonl` sert à construire le modèle. Une fois le modèle sauvegardé, la détection charge directement :

```text
models/trained/isoforest.joblib
```

---

## 11. Scoring IA et règles

### 11.1 Scorer un scénario

Exemple avec `forced_door` :

```bash
python -m models.cli score \
  --features features/output/test_forced_door.parquet \
  --model models/trained/isoforest.joblib \
  --out models/output/test_forced_door.scored.parquet
```

Le fichier généré contient les colonnes d'origine plus :

```text
score_if
score_rules
rule_hits
```

### 11.2 `score_if`

`score_if` est le score donné par l'Isolation Forest.

```text
0.0 → comportement normal
1.0 → comportement très anormal
```

Techniquement, `scikit-learn` fournit une valeur `decision_function`. Le projet la convertit ensuite en score entre 0 et 1 avec une calibration basée sur la distribution d'entraînement.

### 11.3 `score_rules`

`score_rules` est calculé par :

```text
models/rules_engine.py
```

Ce n'est pas de l'IA. Ce sont des règles explicites codées à la main.

Exemples de logique :

```text
porte forcée                         → score élevé
badge refusé répété                  → score élevé
accès hors horaires en zone sensible → score suspect
trafic réseau externe anormal        → score suspect ou critique
port scan                            → score élevé
exfiltration                         → score élevé
```

### 11.4 `rule_hits`

Cette colonne indique quelles règles ont été activées.

Exemple :

```text
rule:door_forced
rule:tailgating
rule:exfiltration
```

C'est utile pour expliquer pourquoi un événement a été considéré comme suspect ou critique.

### 11.5 Scorer tous les scénarios

```bash
mkdir -p models/output

for sc in badge_off_hours forced_door tailgating revoked_badge hybrid_intrusion camera_compromise credential_theft; do
  python -m models.cli score \
    --features features/output/test_${sc}.parquet \
    --model models/trained/isoforest.joblib \
    --out models/output/test_${sc}.scored.parquet
done
```

---

## 12. Évaluation avant fusion

L'évaluation compare les scores avec les fichiers `.truth.json`.

### 12.1 Évaluer un scénario

```bash
python -m models.cli evaluate \
  --scored models/output/test_forced_door.scored.parquet \
  --truth dataset/output/test_forced_door.truth.json
```

### 12.2 Évaluer tous les scénarios

```bash
python -m models.cli evaluate-all \
  --scored-dir models/output \
  --truth-dir dataset/output \
  --out models/output/eval_summary.csv
```

Métriques calculées :

```text
true_positives
false_positives
false_negatives
precision
recall
f1
scenario_detected
max_attack_score
max_normal_score
```

---

## 13. Fusion cyber-physique

La fusion est gérée par :

```text
fusion/correlator.py
fusion/scorer.py
fusion/cli.py
```

Son objectif est d'améliorer la détection en combinant les signaux physiques et cyber.

Exemple :

```text
porte forcée dans la server room
+
trafic réseau anormal depuis une caméra de la même zone
+
fenêtre temporelle proche
=
risque final renforcé
```

### 13.1 Principe de scoring

Le moteur commence par combiner l'IA et les règles :

```text
score_combined = max(score_if, score_rules)
```

Puis il cherche un événement suspect dans l'autre couche :

```text
PHYSICAL suspect ↔ CYBER suspect
même zone
fenêtre temporelle proche
```

Si une corrélation est trouvée, un bonus est appliqué :

```text
score_final = min(1.0, score_combined + bonus_correlation)
```

La classification finale est ensuite :

```text
score_final < 0.3           → NORMAL
0.3 <= score_final < 0.7    → SUSPECT
score_final >= 0.7          → CRITICAL
```

### 13.2 Fusionner un scénario

```bash
python -m fusion.cli fuse \
  --scored models/output/test_forced_door.scored.parquet \
  --out fusion/output/test_forced_door.fused.parquet
```

### 13.3 Paramètres optionnels

```bash
python -m fusion.cli fuse \
  --scored models/output/test_forced_door.scored.parquet \
  --out fusion/output/test_forced_door.fused.parquet \
  --correlation-weight 0.30 \
  --window-seconds 60 \
  --min-peer 0.30
```

Signification :

```text
--correlation-weight : bonus ajouté lorsqu'une corrélation cyber-physique est trouvée
--window-seconds     : fenêtre temporelle de corrélation
--min-peer           : score minimum de l'événement corrélé pour compter comme suspect
```

### 13.4 Fusionner tous les scénarios

```bash
python -m fusion.cli fuse-all \
  --scored-dir models/output \
  --out-dir fusion/output
```

---

## 14. Évaluation après fusion

L'évaluation finale utilise `score_final` et compare les résultats aux fichiers `.truth.json`.

```bash
python -m fusion.cli evaluate-all \
  --fused-dir fusion/output \
  --truth-dir dataset/output \
  --out fusion/output/eval_summary.csv
```

Ce fichier permet de comparer :

```text
score_combined → score IA + règles sans corrélation
score_final    → score après fusion cyber-physique
```

L'objectif est de vérifier si la fusion améliore la détection des scénarios hybrides.

---

## 15. Pipeline complet en une seule séquence

Depuis le dossier `ai-engine/` :

```bash
mkdir -p dataset/output features/output models/trained models/output fusion/output

# 1. Génération de la baseline normale
python -m dataset.cli generate-baseline \
  --topology dataset/topology/building_b1.yaml \
  --start 2026-04-01 \
  --days 30 \
  --seed 42 \
  --out dataset/output/train_normal_30d.jsonl

# 2. Génération des scénarios d'attaque
python -m dataset.cli generate-all-scenarios \
  --topology dataset/topology/building_b1.yaml \
  --seed 42 \
  --out-dir dataset/output

# 3. Apprentissage des baselines réseau
python -m features.cli learn-baselines \
  --events dataset/output/train_normal_30d.jsonl \
  --out features/output/baselines.json

# 4. Extraction des features d'entraînement
python -m features.cli extract \
  --events dataset/output/train_normal_30d.jsonl \
  --topology dataset/topology/building_b1.yaml \
  --baselines features/output/baselines.json \
  --out features/output/train_features.parquet

# 5. Entraînement de l'Isolation Forest
python -m models.cli train \
  --features features/output/train_features.parquet \
  --out models/trained/isoforest.joblib \
  --n-estimators 200 \
  --contamination 0.01 \
  --seed 42

# 6. Extraction des features + scoring pour chaque scénario
for sc in badge_off_hours forced_door tailgating revoked_badge hybrid_intrusion camera_compromise credential_theft; do
  python -m features.cli extract \
    --events dataset/output/test_${sc}.jsonl \
    --topology dataset/topology/building_b1.yaml \
    --baselines features/output/baselines.json \
    --out features/output/test_${sc}.parquet

  python -m models.cli score \
    --features features/output/test_${sc}.parquet \
    --model models/trained/isoforest.joblib \
    --out models/output/test_${sc}.scored.parquet
done

# 7. Évaluation IA + règles avant fusion
python -m models.cli evaluate-all \
  --scored-dir models/output \
  --truth-dir dataset/output \
  --out models/output/eval_summary.csv

# 8. Fusion cyber-physique
python -m fusion.cli fuse-all \
  --scored-dir models/output \
  --out-dir fusion/output

# 9. Évaluation finale après fusion
python -m fusion.cli evaluate-all \
  --fused-dir fusion/output \
  --truth-dir dataset/output \
  --out fusion/output/eval_summary.csv
```

---

## 16. Comment interpréter les résultats ?

### 16.1 Fichiers importants

```text
models/output/eval_summary.csv
fusion/output/eval_summary.csv
```

Le premier fichier évalue :

```text
score_if
score_rules
```

Le second fichier évalue :

```text
score_combined
score_final
```

### 16.2 Lecture des métriques

```text
precision : parmi les alertes levées, combien étaient de vraies attaques ?
recall    : parmi les vraies attaques, combien ont été détectées ?
f1        : compromis entre precision et recall
```

### 16.3 Interprétation attendue

Un bon résultat doit montrer :

```text
score élevé sur les événements d'attaque
score faible sur les événements normaux
peu de faux positifs
scénario détecté au seuil attendu
```

Si `max_normal_score` est supérieur à `max_attack_score`, cela indique que le modèle ou les règles génèrent des faux positifs importants.

---

## 17. Différence entre IA, règles et fusion

### 17.1 Isolation Forest

Fichier :

```text
models/isolation_forest.py
```

Rôle :

```text
apprendre la normalité à partir des features normales
attribuer un score d'anomalie aux nouveaux événements
```

Sortie :

```text
score_if
```

### 17.2 Moteur de règles

Fichier :

```text
models/rules_engine.py
```

Rôle :

```text
détecter directement des comportements suspects connus
```

Sorties :

```text
score_rules
rule_hits
```

### 17.3 Fusion cyber-physique

Fichiers :

```text
fusion/correlator.py
fusion/scorer.py
```

Rôle :

```text
renforcer le risque lorsqu'un signal physique et un signal cyber sont liés
```

Sorties :

```text
score_combined
score_correlation_peer
score_final
ai_classification
```

---

## 18. Exemple concret : scénario `hybrid_intrusion`

Le scénario `hybrid_intrusion` représente une attaque combinée :

```text
intrusion physique
+
anomalie réseau dans une zone proche ou identique
```

Pipeline appliqué :

```bash
python -m dataset.cli generate-scenario \
  --topology dataset/topology/building_b1.yaml \
  --scenario hybrid_intrusion \
  --seed 42 \
  --out-dir dataset/output

python -m features.cli extract \
  --events dataset/output/test_hybrid_intrusion.jsonl \
  --topology dataset/topology/building_b1.yaml \
  --baselines features/output/baselines.json \
  --out features/output/test_hybrid_intrusion.parquet

python -m models.cli score \
  --features features/output/test_hybrid_intrusion.parquet \
  --model models/trained/isoforest.joblib \
  --out models/output/test_hybrid_intrusion.scored.parquet

python -m fusion.cli fuse \
  --scored models/output/test_hybrid_intrusion.scored.parquet \
  --out fusion/output/test_hybrid_intrusion.fused.parquet
```

Dans ce cas, la fusion est particulièrement importante, car un événement physique seul peut être suspect, un événement réseau seul peut être suspect, mais leur proximité temporelle et spatiale rend le scénario beaucoup plus critique.

---

## 19. Tests

Pour lancer tous les tests :

```bash
pytest
```

Pour lancer uniquement les tests du dataset :

```bash
pytest dataset/tests
```

Pour lancer les tests des features :

```bash
pytest features/tests
```

Pour lancer les tests des modèles :

```bash
pytest models/tests
```

Pour lancer les tests de fusion :

```bash
pytest fusion/tests
```

---

## 20. Ce qui est versionné ou non

Le dépôt Git doit contenir :

```text
code source Python
topologies YAML
schemas
scénarios
fichiers de configuration
tests
README
```

Le dépôt Git ne doit normalement pas contenir :

```text
__pycache__/
.pytest_cache/
*.egg-info/
dataset/output/
features/output/
models/output/
models/trained/
fusion/output/
*.jsonl
*.parquet
*.joblib
```

Ces fichiers sont générés localement avec les commandes documentées ci-dessus.

---

## 21. Limites actuelles

La version actuelle constitue une base fonctionnelle pour l'expérimentation IA, mais elle a encore plusieurs limites :

1. **Pas encore de service temps réel Kafka**  
   Le pipeline fonctionne principalement en offline via des fichiers.

2. **Isolation Forest non supervisé**  
   Le modèle apprend uniquement la normalité. Il ne connaît pas explicitement les classes d'attaque.

3. **Pas encore de modèle séquentiel**  
   La mémoire temporelle est représentée par des features agrégées, pas par un LSTM ou un Transformer.

4. **Calibration encore perfectible**  
   Les seuils `0.3`, `0.5`, `0.7` peuvent nécessiter des ajustements selon les résultats.

5. **Risque de faux positifs**  
   L'Isolation Forest peut parfois donner un score élevé à des événements rares mais légitimes.

---

## 22. Évolutions possibles

Pistes d'amélioration :

```text
ajouter un service Kafka Consumer pour scorer en temps réel
ajouter une API FastAPI pour exposer les scores
améliorer les features de séquence : last_zone, time_since_last_badge, transition habituelle
ajouter un modèle supervisé si assez de scénarios annotés sont disponibles
ajouter un LSTM ou un autoencoder séquentiel en v2
calibrer automatiquement les seuils selon les métriques d'évaluation
intégrer les alertes finales dans le dashboard SOC
```

---

## 23. Résumé rapide

Le dossier `ai-engine/` implémente la partie IA du projet Smart Intrusion Detection.

Il permet de :

```text
générer une baseline normale
générer des scénarios d'attaque
extraire des features temporelles, spatiales, fréquentielles et réseau
entraîner un modèle Isolation Forest
scorer les événements avec IA + règles
fusionner les signaux cyber et physiques
évaluer les performances avec les fichiers truth.json
```

La contribution principale de cette partie n'est pas seulement l'utilisation d'Isolation Forest, mais surtout la construction d'un pipeline complet autour du modèle : données simulées, features adaptées au contexte cyber-physique, règles explicables, corrélation multi-couche et évaluation quantitative.
