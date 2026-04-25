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
from common.telemetry import beacon

load_dotenv()

DUFFEL_TOKEN = os.getenv("DUFFEL_TOKEN", "")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

DUFFEL_HEADERS = {
    "Authorization": f"Bearer {DUFFEL_TOKEN}",
    "Duffel-Version": "v2",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

agent = Agent(
    name="kin-logistics",
    seed="kin-logistics-seedphrase-CHANGE-ME-5",
    port=8005,
    mailbox=True,
    publish_agent_details=True,
)

protocol = Protocol(spec=chat_protocol_spec)


def search_flights(origin: str, destination: str, date: str, adults: int = 1) -> list[dict]:
    """Search flights via Duffel sandbox API."""
    if not DUFFEL_TOKEN:
        return []
    body = {
        "data": {
            "slices": [{"origin": origin, "destination": destination, "departure_date": date}],
            "passengers": [{"type": "adult"}] * adults,
            "cabin_class": "economy",
        }
    }
    try:
        r = http_requests.post(
            "https://api.duffel.com/air/offer_requests?return_offers=true",
            json=body,
            headers=DUFFEL_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        offers = r.json()["data"]["offers"]
        # Return top 3 simplified
        results = []
        for offer in offers[:3]:
            slices = offer.get("slices", [])
            segments = slices[0].get("segments", []) if slices else []
            results.append({
                "airline": segments[0].get("operating_carrier", {}).get("name", "Unknown") if segments else "Unknown",
                "departure": segments[0].get("departing_at", "") if segments else "",
                "arrival": segments[-1].get("arriving_at", "") if segments else "",
                "stops": len(segments) - 1,
                "price": f"{offer.get('total_amount', '?')} {offer.get('total_currency', '')}",
                "duration": slices[0].get("duration", "") if slices else "",
            })
        return results
    except Exception:
        return []


def get_ground_eta(
    orig_lat: float, orig_lon: float, dest_lat: float, dest_lon: float
) -> dict | None:
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

    # Parse structured task from kin-triage
    try:
        task = json.loads(raw)
        params = task.get("params", {})
        action = task.get("action", "")
    except (json.JSONDecodeError, AttributeError):
        params = {}
        action = raw

    results = {}

    # Flight search
    origin_iata = params.get("origin", "")
    dest_iata = params.get("destination", "")
    date = params.get("date", "")
    if origin_iata and dest_iata and date:
        flights = search_flights(origin_iata, dest_iata, date)
        results["flights"] = flights
        beacon("kin-logistics", "duffel", "FlightSearch", {
            "origin": origin_iata, "destination": dest_iata, "count": len(flights),
        })

    # Ground ETA
    orig_lat = params.get("origin_lat")
    orig_lon = params.get("origin_lon")
    dest_lat = params.get("dest_lat")
    dest_lon = params.get("dest_lon")
    if all([orig_lat, orig_lon, dest_lat, dest_lon]):
        eta = get_ground_eta(orig_lat, orig_lon, dest_lat, dest_lon)
        if eta:
            results["ground_eta"] = eta
            beacon("kin-logistics", "google-maps", "ETA", eta)

    # Format response
    if results:
        response = json.dumps(results, indent=2)
    elif "flight" in action.lower():
        response = "Missing parameters for flight search. Need: origin, destination, date (IATA codes + YYYY-MM-DD)."
    elif "eta" in action.lower() or "drive" in action.lower():
        response = "Missing coordinates for ETA calculation. Need: origin_lat, origin_lon, dest_lat, dest_lon."
    else:
        response = f"Could not process logistics request: {action}"

    beacon("kin-logistics", "kin-triage", "Response", {"length": len(response)})

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
