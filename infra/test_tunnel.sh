#!/bin/bash

echo "=========================================="
echo "   Test du Tunnel PQC (MQTT over TLS)     "
echo "=========================================="

echo "[1/2] Envoi d'un message depuis le réseau isolé iot-net vers la Gateway Edge..."
echo "Le proxy local (forward-proxy-edge) va chiffrer en PQC et l'envoyer vers Oracle."

docker run --rm --network infra_iot-net eclipse-mosquitto:2 mosquitto_pub -h forward-proxy-edge -p 9001 -t "pqc/test" -m "Message PQC Sécurisé !" --ws -d

echo ""
echo "[2/2] Vérification :"
echo "Si vous voyez 'Client null received CONNACK (0)', le message a bien traversé le tunnel PQC jusqu'à Oracle !"
echo "=========================================="
echo "Terminé."
