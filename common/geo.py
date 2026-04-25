"""Approximate ETA helper — straight-line distance + assumed city speed.

No external API or key. Used by swarm-finder to rank clinics after the
2dsphere $near query narrows candidates by proximity to the patient.

Tradeoff vs Google Routes API:
- pro: zero deps, no card-on-file, deterministic, instant
- con: ignores actual road geometry and live traffic; circuity factor
  approximates "roads are ~30% longer than straight-line" for urban grids

Same function signature as a Google Routes wrapper would have, so we can
swap the impl later without changing callers.
"""
from __future__ import annotations

import math

# Average urban driving speed (LA / Mexico City weekday) in km/h.
# Conservative — accounts for lights, congestion, parking hunt.
CITY_KPH = 30.0
CITY_MPS = CITY_KPH * 1000 / 3600  # ≈ 8.33 m/s

# Multiplier from straight-line distance to road distance for grid cities.
# Empirically ~1.3 for LA, ~1.4 for older Mexico City core.
CIRCUITY = 1.3


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in meters."""
    R = 6_371_000  # Earth radius in meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def get_eta(orig_lat: float, orig_lon: float,
            dest_lat: float, dest_lon: float) -> dict:
    """Approximate driving ETA between two points.

    Returns {"duration_s": int, "distance_m": int}.
    distance_m is the road-adjusted distance (haversine × circuity).
    """
    straight = haversine_m(orig_lat, orig_lon, dest_lat, dest_lon)
    road_m = straight * CIRCUITY
    return {
        "duration_s": int(round(road_m / CITY_MPS)),
        "distance_m": int(round(road_m)),
    }


def eta_from_geojson(orig: dict, dest: dict) -> dict:
    """Convenience for GeoJSON Point docs as stored in MongoDB.

    Each arg must have shape {"coordinates": [lon, lat]}.
    """
    o_lon, o_lat = orig["coordinates"]
    d_lon, d_lat = dest["coordinates"]
    return get_eta(o_lat, o_lon, d_lat, d_lon)


if __name__ == "__main__":
    # Smoke test: Joon Kim (Koreatown) → Your Laser Skin Care (Wilshire)
    # roughly 0.5–1 km apart depending on exact address geocoding
    joon = (34.0577, -118.3004)
    skin_care = (34.0626, -118.3067)
    eta = get_eta(*joon, *skin_care)
    print(f"Joon → Skin Care: {eta['distance_m']/1000:.2f} km, "
          f"{eta['duration_s']//60} min {eta['duration_s']%60}s")

    # Maria (Boyle Heights) → Joon (Koreatown), ~7 km
    maria = (34.0335, -118.2283)
    eta2 = get_eta(*maria, *joon)
    print(f"Maria → Koreatown: {eta2['distance_m']/1000:.2f} km, "
          f"{eta2['duration_s']//60} min {eta2['duration_s']%60}s")
