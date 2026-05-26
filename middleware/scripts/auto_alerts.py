"""
Send random alert scenarios to the middleware at a fixed interval.

Usage:
    python3 scripts/auto_alerts.py --interval 5
    python3 scripts/auto_alerts.py --interval 3 --count 20
"""

from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_URL = "http://127.0.0.1:8010/api/events"
DEFAULT_SCENARIOS = [
    "forced_door",
    "network_port_scan",
    "network_exfiltration",
    "tailgating",
    "badge_off_hours",
]


def _event_id(name: str) -> str:
    return f"evt-{name}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _off_hours_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=3, minute=random.randint(0, 59), second=0, microsecond=0).isoformat()


def forced_door() -> dict[str, Any]:
    return {
        "event_id": _event_id("forced-door"),
        "event_type": "door_sensor",
        "timestamp": _now(),
        "source_device": "D-Z2-Z8",
        "location": "Z8",
        "details": {
            "state": "forced",
            "door_id": "D-Z2-Z8",
            "zone_id": "Z8",
            "no_badge_window_seconds": random.choice([8.0, 10.0, 15.0]),
        },
    }


def network_port_scan() -> dict[str, Any]:
    host = random.randint(10, 240)
    return {
        "event_id": _event_id("port-scan"),
        "event_type": "network_anomaly",
        "timestamp": _now(),
        "source_device": "ids-probe-01",
        "location": "Z8",
        "details": {
            "zone_id": "Z8",
            "anomaly_label": "PORT_SCAN",
            "src_ip": f"10.42.8.{host}",
            "severity_hint": round(random.uniform(0.75, 0.95), 2),
        },
    }


def network_exfiltration() -> dict[str, Any]:
    host = random.randint(10, 240)
    return {
        "event_id": _event_id("exfiltration"),
        "event_type": "network_anomaly",
        "timestamp": _now(),
        "source_device": "ids-probe-01",
        "location": "Z8",
        "details": {
            "zone_id": "Z8",
            "anomaly_label": "EXFILTRATION",
            "src_ip": f"10.42.8.{host}",
            "severity_hint": round(random.uniform(0.8, 0.98), 2),
        },
    }


def tailgating() -> dict[str, Any]:
    zone = random.choice(["Z7", "Z8"])
    detector = "M-Z7-01" if zone == "Z7" else "M-Z8-01"
    return {
        "event_id": _event_id("tailgating"),
        "event_type": "motion_detected",
        "timestamp": _now(),
        "source_device": detector,
        "location": zone,
        "details": {
            "zone_id": zone,
            "entity_count": random.choice([2, 3]),
        },
    }


def badge_off_hours() -> dict[str, Any]:
    user_id = random.choice(["u001", "u003", "u005", "u007"])
    badge_id = f"b{int(user_id[1:]):03d}"
    return {
        "event_id": _event_id("badge-off-hours"),
        "event_type": "badge_access",
        "timestamp": _off_hours_timestamp(),
        "source_device": "R-Z8-01",
        "location": "Z8",
        "details": {
            "zone_id": "Z8",
            "user_id": user_id,
            "badge_id": badge_id,
            "access_result": "GRANTED",
            "door_id": "D-Z2-Z8",
        },
    }


SCENARIOS: dict[str, Callable[[], dict[str, Any]]] = {
    "forced_door": forced_door,
    "network_port_scan": network_port_scan,
    "network_exfiltration": network_exfiltration,
    "tailgating": tailgating,
    "badge_off_hours": badge_off_hours,
}


def post_event(url: str, event: dict[str, Any]) -> tuple[int, str]:
    body = json.dumps(event).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send random intrusion scenarios to the middleware.",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Middleware /api/events URL")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between events")
    parser.add_argument("--jitter", type=float, default=0.0, help="+/- random seconds around interval")
    parser.add_argument("--count", type=int, default=0, help="Number of events; 0 means forever")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help="Scenario to include; repeatable. Defaults to all scenarios.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    scenario_names = args.scenario or DEFAULT_SCENARIOS
    sent = 0
    print(f"Posting to {args.url}")
    print(f"Scenarios: {', '.join(scenario_names)}")
    print("Press Ctrl+C to stop.\n")

    try:
        while args.count <= 0 or sent < args.count:
            name = random.choice(scenario_names)
            event = SCENARIOS[name]()
            try:
                status, _ = post_event(args.url, event)
                sent += 1
                print(
                    f"[{sent:04d}] {status} {name} "
                    f"{event['event_id']} zone={event['location']}"
                )
            except HTTPError as exc:
                print(f"HTTP {exc.code} for {name}: {exc.read().decode('utf-8')}")
            except URLError as exc:
                print(f"Cannot reach middleware: {exc.reason}")

            delay = args.interval
            if args.jitter > 0:
                delay += random.uniform(-args.jitter, args.jitter)
            time.sleep(max(0.0, delay))
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
