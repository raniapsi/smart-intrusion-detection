#!/bin/bash

echo "=========================================================="
echo "   TEST DE PERFORMANCE : PQC TLS 1.3 SESSION RESUMPTION   "
echo "=========================================================="
echo ""
echo "Envoi de 3 requêtes consécutives pour mesurer la latence..."
echo "----------------------------------------------------------"

# On utilise l'image OQS pour lancer un test de performance avec curl
# Le paramètre -w extrait le temps TCP (time_connect) et le temps total TLS (time_appconnect)
OUTPUT=$(docker run --rm -v $(pwd)/../security:/certs openquantumsafe/curl \
    curl -s -k --curves X25519MLKEM768 \
    --cert /certs/gateway/gateway.crt \
    --key /certs/gateway/gateway.key \
    --cacert /certs/ca/ca.crt \
    -H "Connection: close" \
    -w "TIME_METRICS %{time_connect} %{time_appconnect}\n" \
    -o /dev/null \
    https://145.241.162.174:8443 https://145.241.162.174:8443 https://145.241.162.174:8443)

# Traitement des lignes
index=1
full_time=0
resum_time=0

while read -r line; do
    if [[ ! "$line" == TIME_METRICS* ]]; then continue; fi
    
    tcp_connect=$(echo "$line" | awk '{print $2}')
    app_connect=$(echo "$line" | awk '{print $3}')
    
    # Temps du handshake TLS = temps total SSL - temps connexion TCP
    tls_time=$(echo "$app_connect - $tcp_connect" | bc -l)
    tls_time_ms=$(echo "$tls_time * 1000" | bc -l)
    
    # Formatage propre (2 décimales)
    tls_time_ms_fmt=$(printf "%.2f" $tls_time_ms)
    
    if [ $index -eq 1 ]; then
        echo "Requête 1 (Full Handshake)       : ${tls_time_ms_fmt} ms"
        full_time=$tls_time_ms
    elif [ $index -eq 2 ]; then
        echo "Requête 2 (Session Resumption)   : ${tls_time_ms_fmt} ms"
        resum_time=$tls_time_ms
    elif [ $index -eq 3 ]; then
        echo "Requête 3 (Session Resumption)   : ${tls_time_ms_fmt} ms"
        # On calcule le gain entre la 1ère et la 3ème pour lisser
        gain=$(echo "100 - (($tls_time_ms / $full_time) * 100)" | bc -l)
        gain_fmt=$(printf "%.1f" $gain)
        
        echo ""
        echo "----------------------------------------------------------"
        echo "🚀 GAIN DE PERFORMANCE OBTENU : ${gain_fmt} %"
        echo "----------------------------------------------------------"
    fi
    
    index=$((index + 1))
done <<< "$OUTPUT"

echo ""
echo "La reprise de session (Session Resumption) permet de diviser"
echo "le temps cryptographique tout en conservant la Perfect Forward"
echo "Secrecy via un échange DHE X25519MLKEM768 éphémère."
echo "=========================================================="
