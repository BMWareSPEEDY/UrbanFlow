"""Multi-source Bengaluru POI & Infrastructure Scraper for UrbanFLOW.

Combines:
  1. Overpass API (multiple mirrors) — hospitals, clinics, fire stations, transit hubs,
     power substations, underpasses/tunnels, and lakes/weirs per catchment bbox.
  2. Nominatim Search API — Bengaluru flood-prone underpasses, lakes, TTMCs, flyovers.
  3. Wikidata SPARQL API — geolocated Bengaluru hospitals, transit stations, and lakes.
  4. Local GraphML Street Network — named multi-street intersections (`Road A × Road B`).
  5. Curated Municipal Baseline (`CURATED_POIS` from `prepare_data.py`).

Deduplicates by normalized (category, name) and spatial proximity, snaps to nearest
catchment graph nodes, and writes:
  - `data/command/scraped_bengaluru_pois.json` (master combined dataset)
  - `data/command/pois.json` (live app POI registry)

Run:
  .venv/bin/python scripts/command/scrape_bengaluru_pois.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
from pyproj import Transformer

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from command.config import CATCHMENTS, GRAPHS_DIR  # noqa: E402
DATA_COMMAND_DIR = os.path.join(ROOT_DIR, "data", "command")
from scripts.command.prepare_data import _extract_intersection_pois  # noqa: E402


def _snap_to_nearest_node(
    raw_nodes: List[Tuple[str, float, float]], ux: float, uy: float
) -> Tuple[str, float]:
    best_id, best_d2 = raw_nodes[0][0], float("inf")
    for nid, nx_v, ny_v in raw_nodes:
        d2 = (nx_v - ux) ** 2 + (ny_v - uy) ** 2
        if d2 < best_d2:
            best_id, best_d2 = nid, d2
    return best_id, math.sqrt(best_d2)

TRANSFORMER = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
INV_TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

USER_AGENT = "UrbanFLOW-Bengaluru-FloodCommand/1.0 (hackathon-research)"


def _http_get_json(url: str, timeout: float = 12.0) -> Optional[Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _http_post_json(url: str, data: bytes, timeout: float = 15.0) -> Optional[Any]:
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _catchment_bbox(G: nx.MultiDiGraph, pad_deg: float = 0.008) -> Tuple[float, float, float, float]:
    lats, lons = [], []
    for _, d in G.nodes(data=True):
        lon, lat = TRANSFORMER.transform(float(d["x"]), float(d["y"]))
        lats.append(lat)
        lons.append(lon)
    return (
        min(lats) - pad_deg,
        min(lons) - pad_deg,
        max(lats) + pad_deg,
        max(lons) + pad_deg,
    )


def _classify_osm_tags(tags: Dict[str, Any]) -> Optional[str]:
    amenity = str(tags.get("amenity", "")).lower()
    healthcare = str(tags.get("healthcare", "")).lower()
    railway = str(tags.get("railway", "")).lower()
    highway = str(tags.get("highway", "")).lower()
    power = str(tags.get("power", "")).lower()
    water = str(tags.get("water", "")).lower()
    natural = str(tags.get("natural", "")).lower()
    tunnel = str(tags.get("tunnel", "")).lower()

    if amenity in ("hospital", "clinic") or healthcare in ("hospital", "clinic"):
        return "hospital"
    if amenity == "fire_station":
        return "fire_station"
    if amenity == "bus_station" or highway == "bus_stop" or railway in ("station", "subway_entrance"):
        return "transit_hub"
    if power == "substation":
        return "substation"
    if tunnel in ("yes", "culvert", "building_passage"):
        return "underpass"
    if natural == "water" or water in ("lake", "reservoir", "pond"):
        return "lake_weir"
    return None


def scrape_overpass_for_catchment(r_key: str, bbox: Tuple[float, float, float, float]) -> List[dict]:
    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:12];
    (
      node["amenity"~"hospital|clinic|fire_station|bus_station"]({s},{w},{n},{e});
      way["amenity"~"hospital|fire_station|bus_station"]({s},{w},{n},{e});
      node["railway"="station"]({s},{w},{n},{e});
      node["power"="substation"]({s},{w},{n},{e});
      way["power"="substation"]({s},{w},{n},{e});
      way["tunnel"="yes"]["highway"]({s},{w},{n},{e});
      way["natural"="water"]["name"]({s},{w},{n},{e});
    );
    out center 120;
    """
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    for mirror in OVERPASS_MIRRORS:
        data = _http_post_json(mirror, payload, timeout=14.0)
        if data and isinstance(data.get("elements"), list):
            out = []
            for el in data["elements"]:
                tags = el.get("tags") or {}
                name = str(tags.get("name") or "").strip()
                if not name:
                    continue
                cat = _classify_osm_tags(tags)
                if not cat:
                    continue
                lat = el.get("lat") or (el.get("center") or {}).get("lat")
                lon = el.get("lon") or (el.get("center") or {}).get("lon")
                if lat is None or lon is None:
                    continue
                out.append({
                    "name": name,
                    "category": cat,
                    "lat": float(lat),
                    "lng": float(lon),
                    "source": f"overpass:{urllib.parse.urlparse(mirror).netloc}",
                })
            return out
    return []


def scrape_wikidata_bengaluru() -> List[dict]:
    sparql = """
    SELECT ?item ?itemLabel ?coord ?type WHERE {
      VALUES ?type { wd:Q16917 wd:Q55488 wd:Q928830 wd:Q23397 }
      ?item wdt:P31/wdt:P279* ?type .
      ?item wdt:P131* wd:Q1355 .
      ?item wdt:P625 ?coord .
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    } LIMIT 250
    """
    url = f"{WIKIDATA_SPARQL_URL}?format=json&query={urllib.parse.quote(sparql)}"
    data = _http_get_json(url, timeout=14.0)
    if not data:
        return []
    out = []
    for row in data.get("results", {}).get("bindings", []):
        label = (row.get("itemLabel") or {}).get("value", "").strip()
        coord_str = (row.get("coord") or {}).get("value", "")
        type_uri = (row.get("type") or {}).get("value", "")
        if not label or not coord_str.startswith("Point("):
            continue
        try:
            lon_s, lat_s = coord_str[6:-1].split()
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            continue
        if type_uri.endswith("Q16917"):
            cat = "hospital"
        elif type_uri.endswith(("Q55488", "Q928830")):
            cat = "transit_hub"
        else:
            cat = "lake_weir"
        out.append({"name": label, "category": cat, "lat": lat, "lng": lon, "source": "wikidata_sparql"})
    return out


def scrape_nominatim_landmarks() -> List[dict]:
    queries = [
        ("Silk Board Junction Bengaluru", "underpass"),
        ("Agara Flyover Bengaluru", "underpass"),
        ("Iblur Junction Bengaluru", "underpass"),
        ("Bellandur Lake Bengaluru", "lake_weir"),
        ("Agara Lake Bengaluru", "lake_weir"),
        ("Varthur Lake Bengaluru", "lake_weir"),
        ("Madiwala Lake Bengaluru", "lake_weir"),
        ("ITPL Whitefield Bengaluru", "transit_hub"),
        ("Electronic City Phase 1 Bengaluru", "transit_hub"),
        ("Koramangala Sony World Junction", "transit_hub"),
    ]
    out = []
    for q, cat in queries:
        url = f"{NOMINATIM_URL}?q={urllib.parse.quote(q)}&format=json&limit=1"
        res = _http_get_json(url, timeout=6.0)
        if res and isinstance(res, list) and res[0].get("lat") and res[0].get("lon"):
            out.append({
                "name": q.replace(" Bengaluru", ""),
                "category": cat,
                "lat": float(res[0]["lat"]),
                "lng": float(res[0]["lon"]),
                "source": "nominatim_search",
            })
        time.sleep(0.25)
    return out


def main() -> None:
    t0 = time.perf_counter()
    print("1/4 Querying Wikidata SPARQL for Bengaluru infrastructure...")
    wikidata_pois = scrape_wikidata_bengaluru()
    print(f"    -> {len(wikidata_pois)} Wikidata records")

    print("2/4 Querying Nominatim for Bengaluru landmarks...")
    nominatim_pois = scrape_nominatim_landmarks()
    print(f"    -> {len(nominatim_pois)} Nominatim records")

    pois_path = os.path.join(DATA_COMMAND_DIR, "pois.json")
    with open(pois_path, "r", encoding="utf-8") as f:
        existing_pois_doc = json.load(f)

    master_records: List[dict] = []
    source_counts: Dict[str, int] = {}

    for r_key in CATCHMENTS:
        G = nx.read_graphml(os.path.join(GRAPHS_DIR, CATCHMENTS[r_key]["file"]))
        raw_nodes = [(str(nid), float(d["x"]), float(d["y"])) for nid, d in G.nodes(data=True)]
        bbox = _catchment_bbox(G)
        print(f"3/4 Scraping Overpass for {r_key} bbox={tuple(round(x, 4) for x in bbox)}...")
        overpass_pois = scrape_overpass_for_catchment(r_key, bbox)
        print(f"    -> {len(overpass_pois)} Overpass records for {r_key}")

        existing_list = existing_pois_doc["catchments"][r_key]["pois"]
        seen_names = {(p["category"], p["name"].strip().lower()) for p in existing_list}
        seen_coords = [(float(p["lat"]), float(p["lng"])) for p in existing_list]

        candidates = list(overpass_pois) + list(wikidata_pois) + list(nominatim_pois)
        added = 0
        for cand in candidates:
            lat, lon = float(cand["lat"]), float(cand["lng"])
            if not (bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]):
                continue
            key = (cand["category"], cand["name"].strip().lower())
            if key in seen_names:
                continue
            ux, uy = INV_TRANSFORMER.transform(lon, lat)
            nid, dist_m = _snap_to_nearest_node(raw_nodes, ux, uy)
            if dist_m > 600.0:
                continue
            if any(math.hypot(lat - clat, lon - clon) < 0.0008 for clat, clon in seen_coords):
                continue
            seen_names.add(key)
            seen_coords.append((lat, lon))
            n_obj = G.nodes[nid]
            n_lon, n_lat = TRANSFORMER.transform(float(n_obj["x"]), float(n_obj["y"]))
            rec = {
                "id": f"POI-{r_key.upper()}-{len(existing_list) + 1:03d}",
                "name": cand["name"],
                "category": cand["category"],
                "catchment": r_key,
                "node_id": nid,
                "lat": round(n_lat, 6),
                "lng": round(n_lon, 6),
                "snap_m": round(dist_m, 1),
                "source": cand["source"],
            }
            existing_list.append(rec)
            added += 1

        # Also ensure up to 60 named street intersections are included
        seen_node_cat = {(p["node_id"], p["category"]) for p in existing_list}
        seen_utm = [INV_TRANSFORMER.transform(float(p["lng"]), float(p["lat"])) for p in existing_list]
        extra_intersections = _extract_intersection_pois(G, r_key, seen_node_cat, seen_utm, limit=60)
        for p in extra_intersections:
            p["id"] = f"POI-{r_key.upper()}-{len(existing_list) + 1:03d}"
            existing_list.append(p)

        existing_pois_doc["catchments"][r_key]["pois"] = existing_list
        existing_pois_doc["summary"][r_key]["poi_count"] = len(existing_list)
        for p in existing_list:
            src = p.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
            master_records.append(p)
        print(f"    -> {r_key}: +{added} web-scraped POIs (total {len(existing_list)})")

    print("4/4 Writing combined datasets...")
    with open(pois_path, "w", encoding="utf-8") as f:
        json.dump(existing_pois_doc, f, indent=2)

    master_path = os.path.join(DATA_COMMAND_DIR, "scraped_bengaluru_pois.json")
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_pois": len(master_records),
                "sources": source_counts,
                "pois": master_records,
            },
            f,
            indent=2,
        )
    print(f"Done in {time.perf_counter() - t0:.2f}s | Total combined POIs: {len(master_records)} | Sources: {source_counts}")


if __name__ == "__main__":
    main()
