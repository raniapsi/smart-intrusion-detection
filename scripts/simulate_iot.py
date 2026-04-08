"""
IoT Device Simulator
Generates realistic events and publishes them via MQTT.
Usage: python -m scripts.simulate_iot
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone


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
        "location": "zone-A",
        "details_fn": lambda: {
            "state": random.choice(["open", "closed"]),
        },
    },
    {
        "event_type": "motion_detected",
        "source_device": "motion-sensor-01",
        "location": "zone-B",
        "details_fn": lambda: {
            "confidence": round(random.uniform(0.5, 1.0), 2),
        },
    },
    {
        "event_type": "network_anomaly",
        "source_device": "ids-probe-01",
        "location": "server-room",
        "details_fn": lambda: {
            "src_ip": f"192.168.1.{random.randint(1, 254)}",
            "dst_port": random.choice([22, 443, 8080, 3389]),
            "packet_count": random.randint(100, 10000),
        },
    },
    {
        "event_type": "iot_traffic",
        "source_device": f"iot-device-{random.randint(1, 10):02d}",
        "location": "zone-C",
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
        "details": device["details_fn"](),
    }


if __name__ == "__main__":
    print("=== IoT Device Simulator ===")
    print("Generating sample events (Ctrl+C to stop)\n")

    try:
        while True:
            event = generate_event()
            print(json.dumps(event, indent=2))
            print("---")
            time.sleep(random.uniform(1.0, 3.0))
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
