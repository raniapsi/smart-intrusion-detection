"""
IoT Device Simulator
Generates realistic events and publishes them via MQTT.
Usage: python -m scripts.simulate_iot
"""

import json
import os
import random
import time
import uuid
import paho.mqtt.client as mqtt
from datetime import datetime, timezone

MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "9001"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "events.raw")


DEVICE_TYPES = [
    {
        "event_type": "badge_access",
        "source_device": "badge-reader-01",
        "location": "zone-A",
        "details_fn": lambda: {
            "badge_id": f"B-{random.randint(1000, 9999)}",
            "access": random.choice(["granted", "denied"]),
        },
    },
    {
        "event_type": "door_sensor",
        "source_device": "door-sensor-01",
        "location": "Z1",
        "details_fn": lambda: {
            "state": random.choice(["open", "closed"]),
        },
    },
    {
        "event_type": "motion_detected",
        "source_device": "motion-sensor-01",
        "location": "Z3",
        "details_fn": lambda: {
            "confidence": round(random.uniform(0.5, 1.0), 2),
        },
    },
    {
        "event_type": "network_anomaly",
        "source_device": "ids-probe-01",
        "location": "Z8",
        "details_fn": lambda: {
            "src_ip": f"192.168.1.{random.randint(1, 254)}",
            "dst_port": random.choice([22, 443, 8080, 3389]),
            "packet_count": random.randint(100, 10000),
        },
    },
    {
        "event_type": "iot_traffic",
        "source_device": f"iot-device-{random.randint(1, 10):02d}",
        "location": "Z5",
        "details_fn": lambda: {
            "bytes_sent": random.randint(500, 50000),
            "protocol": random.choice(["MQTT", "HTTP", "CoAP", "unknown"]),
        },
    },
]


def generate_event() -> dict:
    """Generate a single random IoT/cyber event."""
    device = random.choice(DEVICE_TYPES)
    return {
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
        "event_type": device["event_type"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_device": device["source_device"],
        "location": device["location"],
        "zone_id": device["location"],
        "details": device["details_fn"](),
    }


if __name__ == "__main__":
    print("=== IoT Device Simulator ===")
    print(f"Connecting to MQTT {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT} over WebSockets...")

    client = mqtt.Client(transport="websockets")
    try:
        client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
        client.loop_start()
        print("Connected! Generating sample events (Ctrl+C to stop)\n")
    except Exception as e:
        print(f"Failed to connect to MQTT broker: {e}")
        exit(1)

    try:
        while True:
            event = generate_event()
            
            # Map event to Node-RED topic
            topic = "building/B1/network/flow"
            etype = event["event_type"]
            loc = event["location"]
            dev = event["source_device"]
            
            if etype == "badge_access":
                topic = f"building/B1/zone/{loc}/badge/{dev}"
            elif etype == "door_sensor":
                topic = f"building/B1/zone/{loc}/door/{dev}"
            elif etype == "motion_detected":
                topic = f"building/B1/zone/{loc}/motion/{dev}"
            elif etype == "network_anomaly":
                topic = "building/B1/network/alert"
            elif etype == "iot_traffic":
                topic = "building/B1/network/flow"
            
            payload = json.dumps(event)
            client.publish(topic, payload)
            print(f"Published to {topic}: {event['event_id']}")
            time.sleep(random.uniform(1.0, 3.0))
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
        client.loop_stop()
        client.disconnect()
