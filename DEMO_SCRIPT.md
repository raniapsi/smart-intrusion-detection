# 🎤 Smart Intrusion Detection - Live Demo Script (2min30)

**Context**: 
- **Time limit**: 2 minutes 30 seconds.
- **Setup**: Have several terminals ready. One for local Mac commands, one for VM commands, and three others for the Kafka consumers.

---

## ⏱️ 0:00 - Introduction (10s)
> *"Hello everyone. Today I'm presenting our Smart Intrusion Detection architecture. I will demonstrate our secure Post-Quantum Cryptography tunnel connecting our Edge IoT network to the Oracle Cloud, followed by our real-time AI event processing."*

---

## ⏱️ 0:10 - Part 1: End-to-End PQC Tunnel Verification (1min30s)

### Action 1: Edge Proxy Active Connections
**Run in Terminal 1 (Mac):**
```bash
docker exec forward-proxy-edge netstat -anp | grep ESTABLISHED
```
**What to say**:
> *"Our physical sensors and IoT simulators are confined to an isolated local network. If we check the established connections on our Edge Proxy, we see two active sockets. The first is the internal reception from the simulator. The second is the outgoing Post-Quantum WebSocket tunnel to our Oracle Cloud VM on port 8443."*

### Action 2: Forcing Local Proxy Logs
**Run in Terminal 1 (Mac):**
```bash
docker logs -f forward-proxy-edge
```
*(Open a new local tab quickly to stop and restart the simulator:)*
```bash
docker compose -f docker-compose-edge.yml stop iot-simulator
docker compose -f docker-compose-edge.yml start iot-simulator
```
**What to say**:
> *"Because WebSockets are persistent, Nginx only logs the traffic when the connection drops. By momentarily restarting the simulator, we can force the proxy to flush its logs. As you can see, we get a '101 Switching Protocols' status, confirming the MQTT telemetry was successfully encapsulated and transmitted."*

### Action 3: Cloud Proxy Reception & Security
**Run in Terminal 2 (Cloud VM):**
```bash
sudo docker logs reverse-proxy-cloud --tail 10
```
**What to say**:
> *"On the Cloud VM, the Reverse Proxy logs confirm the reception of the encrypted traffic from my laptop's public IP.*
> *More importantly, you can see 'no suitable key share' errors. This proves our Post-Quantum port 8443 actively rejects standard Internet bots and scanners because they lack the required Kyber encryption algorithms."*

### Action 4: Live Payload Interception
**Run in Terminal 2 (Cloud VM):**
```bash
sudo docker exec -it smart-middleware python -c "
import paho.mqtt.subscribe as subscribe
print('🎧 En écoute de Mosquitto (WebSocket) sur mosquitto:9001...')
def print_msg(client, userdata, message):
    print(f'📦 Alerte reçue sur {message.topic} : {message.payload.decode()}')
subscribe.callback(print_msg, 'building/#', hostname='mosquitto', port=9001, transport='websockets')
"
```
**What to say**:
> *"To prove the data safely reached its destination after crossing the Internet, we run a Python listener directly inside the Cloud middleware. As you can see, the live JSON telemetry from the sensors is arriving perfectly intact."*

---

## ⏱️ 1:40 - Part 2: Kafka & AI Processing (50s)
> *"Now that the data is securely in the Cloud, it is ingested into our event-driven architecture. I have three Kafka consumers running here."*

### 1️⃣ Raw Events
**Point to Terminal 3 (already running on VM):**
```bash
sudo docker exec smart-kafka kafka-console-consumer --bootstrap-server kafka:9092 --topic events.raw --from-beginning
```
**What to say**:
> *"The first terminal listens to `events.raw`. Here we see the raw physical and cyber telemetry arriving safely from the PQC tunnel."*

### 2️⃣ Enriched Events (AI Engine)
**Point to Terminal 4 (already running on VM):**
```bash
sudo docker exec smart-kafka kafka-console-consumer --bootstrap-server kafka:9092 --topic events.enriched --from-beginning
```
**What to say**:
> *"The second terminal is `events.enriched`. Our Python AI Engine consumes the raw data, evaluates the threat level using Machine Learning, and appends an anomaly score to each event."*

### 3️⃣ Critical Alerts
**Point to Terminal 5 (already running on VM):**
```bash
sudo docker exec smart-kafka kafka-console-consumer --bootstrap-server kafka:9092 --topic alerts.critical --from-beginning
```
**What to say**:
> *"Finally, `alerts.critical` filters the stream and only publishes events with a high threat score, which are instantly pushed to our security Dashboard."*

---

## ⏱️ 2:30 - Conclusion
> *"By combining isolated IoT networks, PQC encryption, and real-time AI threat scoring, we provide a fully secure, end-to-end architecture. Thank you!"*
