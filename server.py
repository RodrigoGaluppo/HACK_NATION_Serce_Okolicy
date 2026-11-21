"""Local Odblokuj AED dashboard and bounded lookup API."""
import argparse
from contextlib import closing
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
import secrets
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

from prepare_data import DB, build, distance, normalize
import operations

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_LAT, DEFAULT_LON = 52.2297, 21.0122
MAX_LIMIT = 80
MODE = "local"
CITIES = {
    "warszawa": (52.2297, 21.0122),
    "krakow": (50.0647, 19.9450),
    "wroclaw": (51.1079, 17.0385),
    "poznan": (52.4064, 16.9252),
    "gdansk": (54.3520, 18.6466),
    "lodz": (51.7592, 19.4560),
    "krosno": (49.6884, 21.7706),
    "przemysl": (49.7835, 22.7678),
    "marki": (52.3215, 21.1050),
    "bydgoszcz": (53.1235, 18.0084),
}


def connection():
    db = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def get_number(params, key, default, low, high, converter=float):
    value = converter(params.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Nieprawidłowa wartość pola {key}.")
    return value


def lookup(db, params, *, offline=False):
    query = params.get("q", "").strip()
    if len(query) > 100:
        raise ValueError("Wpisz nie więcej niż 100 znaków.")
    normalized = normalize(query)
    city = CITIES.get(normalized) if "lat" not in params else None
    tokens = normalized.split() if not city else []
    limit = 8000 if offline else min(MAX_LIMIT, get_number(params, "limit", 50, 1, 10000, int))
    radius = get_number(params, "radius_km", 30, 0.1, 100)
    if ("lat" in params) != ("lon" in params):
        raise ValueError("Podaj szerokość i długość geograficzną.")
    location = "lat" in params or not tokens
    filters = ["s.search_text LIKE ?" for _ in tokens]
    arguments = [f"%{token}%" for token in tokens]
    available = params.get("available") == "1"
    if available:
        filters.append("s.access IN ('yes','designated','public')")
    if location:
        center = city or (DEFAULT_LAT, DEFAULT_LON)
        lat = get_number(params, "lat", center[0], -90, 90)
        lon = get_number(params, "lon", center[1], -180, 180)
        lat_delta = radius / 110
        nearest_pole = abs(lat) + lat_delta
        lon_delta = 180 if nearest_pole >= 90 else min(180, radius / (110 * math.cos(math.radians(nearest_pole))))
        low, high = lon - lon_delta, lon + lon_delta
        filters += ["g.min_lat <= ?", "g.max_lat >= ?"]
        arguments += [lat + lat_delta, lat - lat_delta]
        if low < -180:
            filters.append("(g.min_lon <= ? OR g.max_lon >= ?)")
            arguments += [high, low + 360]
        elif high > 180:
            filters.append("(g.max_lon >= ? OR g.min_lon <= ?)")
            arguments += [low, high - 360]
        else:
            filters += ["g.min_lon <= ?", "g.max_lon >= ?"]
            arguments += [high, low]
        sql = "SELECT s.* FROM sites_geo g JOIN sites s ON s.rowid = g.rowid WHERE " + " AND ".join(filters)
        nearby = []
        for row in db.execute(sql, arguments):
            separation = distance(lat, lon, row["lat"], row["lon"])
            if separation <= radius:
                nearby.append((separation, row))
        nearby.sort(key=lambda item: (item[0], item[1]["id"]))
        selected = nearby[:limit]
        count = len(nearby)
    else:
        where = " WHERE " + " AND ".join(filters)
        count = db.execute("SELECT count(*) FROM sites s" + where, arguments).fetchone()[0]
        selected = [(None, row) for row in db.execute(
            "SELECT s.* FROM sites s" + where + " ORDER BY s.name COLLATE NOCASE, s.id LIMIT ?",
            [*arguments, limit],
        )]
    items = []
    for separation, row in selected:
        item = dict(row)
        item.pop("rowid")
        item.pop("search_text")
        item["sources"] = json.loads(item["sources"])
        item["field_sources"] = json.loads(item["field_sources"])
        item["distance_km"] = round(separation, 2) if separation is not None else None
        items.append(item)
    source_count = count
    for row in operations.published():
        if row["coordinate_status"] != "located" or (available and row["access_type"] != "public"):
            continue
        address = " ".join(row[k] for k in ("street", "house_number", "municipality") if row[k])
        if tokens and not all(token in normalize(row["site_name"] + " " + address) for token in tokens):
            continue
        separation = distance(lat, lon, row["latitude"], row["longitude"]) if location else None
        if separation is not None and separation > radius:
            continue
        source_count += 1
        items.append({"id": row["aed_id"], "name": row["site_name"], "lat": row["latitude"],
                      "lon": row["longitude"], "address": address, "municipality": row["municipality"],
                      "placement": row["placement"], "access_instructions": row["access_instructions"],
                      "level": row["level"], "access": row["access_type"], "hours": row["opening_hours"],
                      "checked_on": row["access_checked_on"] or row["location_checked_on"],
                      "sources": row["source_ids"], "field_sources": row["field_sources"],
                      "distance_km": round(separation, 2) if separation is not None else None})
    if location:
        items.sort(key=lambda item: (item["distance_km"], item["id"]))
    else:
        items.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    items = items[:limit]
    for item in items:
        score = 25
        reasons = ["Zapisane współrzędne"]
        evidence_date = item.get("checked_on")
        if len(set(item["sources"])) > 1:
            score += 30
            reasons.append("Dopasowanie co najmniej dwóch źródeł")
        if item.get("placement") or item.get("address"):
            score += 15
            reasons.append("Opis miejsca lub adres")
        if item.get("access") not in ("", None, "unknown"):
            score += 10
            reasons.append("Informacja o rodzaju dostępu")
        if evidence_date:
            from datetime import date
            try:
                age = (date.today() - date.fromisoformat(evidence_date)).days
                if 0 <= age <= 365:
                    score += 20
                    reasons.append("Data sprawdzenia z ostatnich 365 dni")
            except ValueError:
                pass
        item.update(confidence=score, confidence_reasons=reasons)
    result = {"items": items, "count": source_count}
    if location:
        result["center"] = {"lat": lat, "lon": lon}
    return result


class Dashboard(BaseHTTPRequestHandler):
    def reply(self, status, payload, content_type, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        if payload and self.command != "HEAD":
            self.wfile.write(payload)

    def json(self, status, body):
        self.reply(status, json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        try:
            path = urlsplit(self.path)
            if path.path.startswith("/api/"):
                self.api(path)
            else:
                self.asset(path.path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OverflowError):
            self.json(400, {"error": "Sprawdź współrzędne, obszar wyszukiwania i limit wyników."})
        except sqlite3.Error as exc:
            self.log_error("SQLite: %s", exc)
            self.json(503, {"error": "Lokalny indeks danych jest niedostępny."})

    def do_HEAD(self):
        self.do_GET()

    def authorized(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").encode()
        if secrets.compare_digest(supplied, operations.admin_token().encode()):
            return True
        self.json(401, {"error": "Podaj poprawny token panelu."})
        return False

    def do_POST(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/admin/") and not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_500_000 or self.headers.get_content_type() != "application/json":
                return self.json(400, {"error": "Oczekiwano JSON o rozmiarze do 2,5 MB."})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Oczekiwano obiektu JSON.")
            if path == "/api/admin/connectors":
                return self.json(202 if operations.start_refresh(body.get("source")) else 409,
                                 {"message": "Sprawdź status synchronizacji."})
            if path == "/api/admin/decision":
                ok = operations.decide(body.get("id"), body.get("status"))
                return self.json(200 if ok else 409, {"updated": ok})
            if path in {"/api/submit", "/api/submit/preview"}:
                rows, errors = operations.validate(body)
                if errors or path.endswith("/preview"):
                    return self.json(200, {"valid": len(rows), "errors": errors, "sample": rows[:4]})
                return self.json(201, {"accepted": operations.submit(rows)})
            self.json(404, {"error": "Nie znaleziono zasobu."})
        except ModuleNotFoundError:
            self.json(503, {"error": "Obsługa XLSX wymaga openpyxl."})
        except (ValueError, csv.Error, TypeError, KeyError) as exc:
            self.json(400, {"error": str(exc)})
        except sqlite3.Error:
            self.json(503, {"error": "Baza operacji jest chwilowo niedostępna."})

    def api(self, path):
        if path.path.startswith("/api/admin/"):
            if not self.authorized():
                return
            if path.path == "/api/admin/queue":
                return self.json(200, {"items": operations.queue()})
            if path.path == "/api/admin/export":
                return self.reply(200, operations.export_pack(), "application/zip")
            if path.path == "/api/admin/connectors":
                with closing(connection()) as db:
                    return self.json(200, operations.connectors([dict(row) for row in db.execute("SELECT * FROM sources")]))
        if path.path == "/api/template.csv":
            return self.reply(200, operations.template().encode(), "text/csv; charset=utf-8")
        if path.path == "/api/template.xlsx":
            try:
                return self.reply(200, operations.xlsx_template(),
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except ModuleNotFoundError:
                return self.json(503, {"error": "Zainstaluj openpyxl."})
        if path.path == "/api/config":
            return self.json(200, {
                "google_maps_key": os.getenv("GOOGLE_MAPS_BROWSER_KEY", ""),
                "google_maps_map_id": os.getenv("GOOGLE_MAPS_MAP_ID", ""),
                "mode": MODE,
            })
        if path.path not in {"/api/aeds", "/api/offline", "/api/sources", "/api/review"}:
            return self.json(404, {"error": "Nie znaleziono zasobu."})
        with closing(connection()) as db:
            if path.path in {"/api/aeds", "/api/offline"}:
                query = parse_qs(path.query, keep_blank_values=True, max_num_fields=12)
                params = {key: values[-1] for key, values in query.items()}
                offline = path.path.endswith("/offline")
                if offline and not {"lat", "lon"} <= params.keys():
                    raise ValueError("Podaj środek pobranego obszaru.")
                return self.json(200, lookup(db, params, offline=offline))
            if path.path == "/api/review":
                items = db.execute("SELECT source, ref, name, reason, address FROM review ORDER BY source, ref LIMIT 100")
                return self.json(200, {"items": [dict(item) for item in items]})
            sources = [dict(row) for row in db.execute("SELECT id, name, count, url FROM sources ORDER BY rowid")]
            return self.json(200, {
                "sources": sources, "mode": MODE,
                "site_count": db.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
                              + sum(row["coordinate_status"] == "located" for row in operations.published()),
                "review_count": db.execute("SELECT COUNT(*) FROM review").fetchone()[0],
                "generated_at": db.execute("SELECT generated_at FROM metadata").fetchone()[0],
            })

    def asset(self, path):
        relative = unquote(path).lstrip("/") or "index.html"
        if relative in {"mapa", "zglos", "panel"}:
            relative += ".html" if relative != "mapa" else ""
            if relative == "mapa":
                relative = "index.html"
        asset = (STATIC / relative).resolve()
        if not asset.is_relative_to(STATIC) or not asset.is_file():
            return self.json(404, {"error": "Nie znaleziono zasobu."})
        content_type = mimetypes.guess_type(asset)[0] or "application/octet-stream"
        self.reply(200, asset.read_bytes(), content_type, "no-cache")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    if not DB.is_file():
        build()
    operations.admin_token()
    with ThreadingHTTPServer((args.host, args.port), Dashboard) as server:
        print(f"Odblokuj AED: http://{args.host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
