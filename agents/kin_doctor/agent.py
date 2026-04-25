import os
import sys
import json
from datetime import datetime, timezone
from uuid import uuid4

import requests as http_requests
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from common.asi import asi_chat
from common.telemetry import beacon

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# City bounding boxes: (south, west, north, east)
CITY_BBOXES = {
    "mumbai": (18.89, 72.77, 19.27, 72.99),
    "mexico city": (19.26, -99.30, 19.59, -98.96),
    "delhi": (28.40, 76.84, 28.88, 77.35),
    "los angeles": (33.70, -118.67, 34.34, -118.15),
    "new york": (40.49, -74.26, 40.92, -73.70),
}

agent = Agent(
    name="kin-doctor",
    seed="kin-doctor-seedphrase-CHANGE-ME-3",
    port=8003,
    mailbox=True,
    publish_agent_details=True,
)

protocol = Protocol(spec=chat_protocol_spec)


def find_city_bbox(location: str) -> tuple | None:
    """Match a location string to a known city bounding box."""
    loc_lower = location.lower()
    for city, bbox in CITY_BBOXES.items():
        if city in loc_lower:
            return bbox
    return None


def query_hospitals(bbox: tuple, limit: int = 10) -> list[dict]:
    """Fetch hospitals from OpenStreetMap Overpass API."""
    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="hospital"]({s},{w},{n},{e});
      way["amenity"="hospital"]({s},{w},{n},{e});
      relation["amenity"="hospital"]({s},{w},{n},{e});
    );
    out center;
    """
    try:
        r = http_requests.get(OVERPASS_URL, params={"data": query}, timeout=30)
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception:
        return []

    hospitals = []
    for el in elements[:limit]:
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not (lat and lon):
            continue
        tags = el.get("tags", {})
        hospitals.append({
            "name": tags.get("name", "Unnamed Hospital"),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "address": tags.get("addr:full") or tags.get("addr:street"),
            "lat": lat,
            "lon": lon,
            "emergency": tags.get("emergency", "unknown"),
        })
    return hospitals


def get_eta(orig_lat: float, orig_lon: float, dest_lat: float, dest_lon: float) -> dict | None:
    """Get driving ETA via Google Maps Routes API."""
    if not GOOGLE_MAPS_API_KEY:
        return None
    body = {
        "origin": {"location": {"latLng": {"latitude": orig_lat, "longitude": orig_lon}}},
        "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lon}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }
    try:
        r = http_requests.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
            },
            timeout=10,
        )
        r.raise_for_status()
        route = r.json()["routes"][0]
        return {"duration": route["duration"], "distance_m": route["distanceMeters"]}
    except Exception:
        return None


@protocol.on_message(ChatMessage)
async def handle(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    raw = "".join(i.text for i in msg.content if isinstance(i, TextContent))
    ctx.logger.info(f"Received: {raw[:100]}...")

    # Parse task from kin-triage
    try:
        task = json.loads(raw)
        params = task.get("params", {})
        location = params.get("location", "")
        symptom = params.get("symptom", "")
        patient_lat = params.get("patient_lat")
        patient_lon = params.get("patient_lon")
    except (json.JSONDecodeError, AttributeError):
        location = raw
        symptom = ""
        patient_lat = None
        patient_lon = None

    # Find hospitals via Overpass
    bbox = find_city_bbox(location)
    if bbox:
        hospitals = query_hospitals(bbox)
        beacon("kin-doctor", "overpass", "HospitalQuery", {"location": location, "count": len(hospitals)})
    else:
        hospitals = []

    if not hospitals:
        response = f"Could not find hospitals near '{location}'. Please provide a more specific city name."
    else:
        # Ask ASI:One to pick the best hospital given the symptom
        hospital_summary = json.dumps(hospitals[:5], indent=2)
        pick = asi_chat(
            "You are a medical facility advisor. Given a list of nearby hospitals and the "
            "patient's symptoms, pick the single best hospital. Respond with ONLY a JSON object: "
            '{"pick": 0, "reason": "..."}  where pick is the 0-based index.',
            f"Symptom: {symptom or 'general emergency'}\n\nHospitals:\n{hospital_summary}",
        )

        # Parse the pick
        try:
            pick_json = json.loads(pick[pick.find("{"):pick.rfind("}") + 1])
            idx = pick_json.get("pick", 0)
            reason = pick_json.get("reason", "")
        except Exception:
            idx = 0
            reason = "Closest available hospital"

        chosen = hospitals[min(idx, len(hospitals) - 1)]

        # Get ETA if patient coordinates provided
        eta_info = ""
        if patient_lat and patient_lon:
            eta = get_eta(patient_lat, patient_lon, chosen["lat"], chosen["lon"])
            if eta:
                eta_info = f"\nETA: {eta['duration']} ({eta['distance_m']}m)"
                beacon("kin-doctor", "google-maps", "ETA", eta)

        response = (
            f"Recommended: {chosen['name']}\n"
            f"Phone: {chosen.get('phone') or 'Not listed'}\n"
            f"Address: {chosen.get('address') or 'See coordinates'}\n"
            f"Coordinates: {chosen['lat']}, {chosen['lon']}\n"
            f"Reason: {reason}"
            f"{eta_info}\n\n"
            f"Total hospitals found nearby: {len(hospitals)}"
        )

    beacon("kin-doctor", "kin-triage", "Response", {"hospital": response[:200]})

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=response),
                EndSessionContent(type="end-session"),
            ],
        ),
    )


@protocol.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(protocol, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
