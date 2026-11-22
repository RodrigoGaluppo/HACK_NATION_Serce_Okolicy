"""Local Odblokuj AED · Serce Okolicy dashboard, canonical JSON/GeoJSON/CSV endpoints and bounded lookup API."""
import argparse
from contextlib import closing
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
import secrets
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit
from zipfile import ZipFile

from prepare_data import (
    DB, PORTAL_METADATA_JSON, PUBLIC_CSV, PUBLIC_GEOJSON, REGISTRY_JSON,
    ROOT, SOURCE_METADATA, build, distance, normalize,
)
import operations
import map_data

STATIC = ROOT / "static"
VIDEO = ROOT / "video"
BRAND_ZIP = ROOT / "Odblokuj-AED-identyfikacja.zip"
DEFAULT_LAT, DEFAULT_LON = 52.2297, 21.0122
MAX_LIMIT = 120
MODE = "local"
CITIES = {
    "warszawa": (52.2297, 21.0122),
    "krakow": (50.0647, 19.9450),
    "wroclaw": (51.1079, 17.0385),
    "poznan": (52.4064, 16.9252),
    "gdansk": (54.3520, 18.6466),
    "gdynia": (54.5189, 18.5305),
    "sopot": (54.4416, 18.5601),
    "trojmiasto": (54.3950, 18.5900),
    "lodz": (51.7592, 19.4560),
    "katowice": (50.2649, 19.0238),
    "krosno": (49.6884, 21.7706),
    "przemysl": (49.7835, 22.7678),
    "marki": (52.3215, 21.1050),
    "bydgoszcz": (53.1235, 18.0084),
    "szczecin": (53.4285, 14.5528),
    "lublin": (51.2465, 22.5684),
    "bialystok": (53.1325, 23.1688),
    "rzeszow": (50.0412, 21.9991),
    "torun": (53.0138, 18.5984),
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
    limit = 10000 if offline else min(MAX_LIMIT, get_number(params, "limit", 60, 1, 10000, int))
    radius = get_number(params, "radius_km", 30, 0.1, 600)
    min_confidence = get_number(params, "min_confidence", 0, 0, 100, int)
    source_filter = params.get("source", "").strip()
    bounds = None
    bbox_keys = {"west", "east", "south", "north"}
    if bbox_keys & params.keys():
        if not bbox_keys <= params.keys():
            raise ValueError("Podaj pełne granice widoku.")
        west = get_number(params, "west", 0, -180, 180)
        east = get_number(params, "east", 0, -180, 180)
        south = get_number(params, "south", 0, -90, 90)
        north = get_number(params, "north", 0, -90, 90)
        if west >= east or south >= north:
            raise ValueError("Nieprawidłowe granice widoku.")
        bounds = west, south, east, north
    if ("lat" in params) != ("lon" in params):
        raise ValueError("Podaj szerokość i długość geograficzną.")
    location = "lat" in params or not tokens
    filters = ["s.search_text LIKE ?" for _ in tokens]
    arguments = [f"%{token}%" for token in tokens]
    if bounds:
        filters.extend(["s.lon >= ?", "s.lat >= ?", "s.lon <= ?", "s.lat <= ?"])
        arguments.extend(bounds)
    available = params.get("available") == "1"
    if available:
        filters.append("s.access IN ('yes','designated','public')")
    if min_confidence > 0:
        filters.append("s.confidence >= ?")
        arguments.append(min_confidence)
    if source_filter:
        filters.append("s.sources LIKE ?")
        arguments.append(f'%"{source_filter}"%')
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
        nearby.sort(key=lambda item: (item[0], -item[1]["confidence"], item[1]["id"]))
        selected = nearby[:limit]
        count = len(nearby)
    else:
        where = (" WHERE " + " AND ".join(filters)) if filters else ""
        count = db.execute("SELECT count(*) FROM sites s" + where, arguments).fetchone()[0]
        selected = [(None, row) for row in db.execute(
            "SELECT s.* FROM sites s" + where + " ORDER BY s.confidence DESC, s.name COLLATE NOCASE, s.id LIMIT ?",
            [*arguments, limit],
        )]
    items = []
    for separation, row in selected:
        try:
            item = json.loads(row["canonical_json"])
        except Exception:
            item = dict(row)
            item.pop("rowid", None)
            item.pop("search_text", None)
            item.pop("canonical_json", None)
            item["sources"] = json.loads(item["sources"])
            item["field_sources"] = json.loads(item["field_sources"])
            item["confidence_reasons"] = json.loads(item.get("confidence_reasons") or "[]")
        item["distance_km"] = round(separation, 2) if separation is not None else None
        items.append(item)
    source_count = count
    for row in operations.published():
        if row["coordinate_status"] != "located" or (available and row["access_type"] != "public"):
            continue
        if min_confidence > 0 and row.get("confidence", 0) < min_confidence:
            continue
        if source_filter and source_filter not in row.get("source_ids", ()):
            continue
        address = " ".join(str(row[k]) for k in ("street", "house_number", "postcode", "municipality") if row.get(k))
        if tokens and not all(token in normalize(f"{row['site_name']} {address} {row.get('placement', '')}") for token in tokens):
            continue
        if bounds and not (bounds[0] <= row["longitude"] <= bounds[2] and bounds[1] <= row["latitude"] <= bounds[3]):
            continue
        separation = distance(lat, lon, row["latitude"], row["longitude"]) if location else None
        if separation is not None and separation > radius:
            continue
        source_count += 1
        items.append({
            **row,
            "id": row["aed_id"],
            "name": row["site_name"],
            "lat": row["latitude"],
            "lon": row["longitude"],
            "address": address,
            "access": row["access_type"],
            "hours": row["opening_hours"],
            "checked_on": row["access_checked_on"] or row["location_checked_on"],
            "sources": row["source_ids"],
            "distance_km": round(separation, 2) if separation is not None else None,
        })
    if location:
        items.sort(key=lambda item: (item["distance_km"], -item.get("confidence", 0), item["id"]))
    else:
        items.sort(key=lambda item: (-item.get("confidence", 0), item["name"].casefold(), item["id"]))
    items = items[:limit]
    result = {"items": items, "count": source_count, "schema": "dane.gov.pl/odblokuj-aed/v1"}
    if location:
        result["center"] = {"lat": lat, "lon": lon}
    return result


class Dashboard(BaseHTTPRequestHandler):
    def reply(self, status, payload, content_type, cache="no-store", filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
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
            if path == "/api/admin/sources":
                return self.json(201, {"item": operations.register_source(body)})
            if path == "/api/admin/connectors":
                return self.json(
                    202 if operations.start_refresh(body.get("source")) else 409,
                    {"message": "Sprawdź status synchronizacji."},
                )
            if path == "/api/admin/decision":
                ok = operations.decide(body.get("id"), body.get("status"))
                return self.json(200 if ok else 409, {"updated": ok})
            if path == "/api/tag":
                record = operations.tag_location(body)
                return self.json(201, {"tagged": True, "status": "pending", "item": record})
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
                return self.reply(200, operations.export_pack(), "application/zip", filename="odblokuj-aed-pakiet-portalu.zip")
            if path.path == "/api/admin/connectors":
                with closing(connection()) as db:
                    return self.json(200, operations.connectors([dict(row) for row in db.execute("SELECT * FROM sources")]))
        release_routes = {
            "/api/aed.geojson": ("aed.geojson", "application/geo+json; charset=utf-8"),
            "/api/aed.json": ("aed.json", "application/json; charset=utf-8"),
            "/api/aed.csv": ("aed.csv", "text/csv; charset=utf-8"),
            "/api/portal-metadata.json": ("portal-metadata.json", "application/json; charset=utf-8"),
        }
        if path.path in release_routes:
            filename, content_type = release_routes[path.path]
            return self.reply(200, operations.public_release_files()[filename], content_type, filename=filename)
        if path.path == "/api/template.csv":
            return self.reply(200, operations.template().encode(), "text/csv; charset=utf-8", filename="wzorcowy-zakres-aed.csv")
        if path.path == "/api/brand-book.pdf" and BRAND_ZIP.is_file():
            with ZipFile(BRAND_ZIP) as archive:
                return self.reply(200, archive.read("pdf/brand-book.pdf"), "application/pdf")
        if path.path == "/api/poster.pdf" and BRAND_ZIP.is_file():
            with ZipFile(BRAND_ZIP) as archive:
                return self.reply(200, archive.read("pdf/poster.pdf"), "application/pdf")
        if path.path == "/api/identyfikacja.zip" and BRAND_ZIP.is_file():
            return self.reply(200, BRAND_ZIP.read_bytes(), "application/zip")
        if path.path == "/api/template.xlsx":
            try:
                return self.reply(
                    200,
                    operations.xlsx_template(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    filename="wzorcowy-zakres-aed.xlsx",
                )
            except ModuleNotFoundError:
                return self.json(503, {"error": "Zainstaluj openpyxl."})
        if path.path == "/api/map-pack":
            query = parse_qs(path.query, max_num_fields=4)
            params = {key: values[-1] for key, values in query.items()}
            lat = get_number(params, "lat", DEFAULT_LAT, 48.9, 55)
            lon = get_number(params, "lon", DEFAULT_LON, 14, 24.2)
            radius = get_number(params, "radius_km", 1, 0.5, 3)
            try:
                payload = map_data.extract(lat, lon, radius)
            except ValueError as exc:
                return self.json(503, {"error": str(exc)})
            return self.reply(200, payload, "application/geo+json; charset=utf-8")
        if path.path == "/api/config":
            return self.json(200, {
                "google_maps_key": os.getenv("GOOGLE_MAPS_BROWSER_KEY", ""),
                "google_maps_map_id": os.getenv("GOOGLE_MAPS_MAP_ID", ""),
                "mode": MODE,
                "sync_schedule": operations.RUN.get("schedule", "codziennie (24h)"),
                "next_sync_at": operations.RUN.get("next_sync_at"),
            })
        if path.path not in {"/api/aeds", "/api/offline", "/api/sources", "/api/review"}:
            return self.json(404, {"error": "Nie znaleziono zasobu."})
        with closing(connection()) as db:
            if path.path in {"/api/aeds", "/api/offline"}:
                query = parse_qs(path.query, keep_blank_values=True, max_num_fields=16)
                params = {key: values[-1] for key, values in query.items()}
                offline = path.path.endswith("/offline")
                if offline and not {"lat", "lon"} <= params.keys():
                    raise ValueError("Podaj środek pobranego obszaru.")
                return self.json(200, lookup(db, params, offline=offline))
            if path.path == "/api/review":
                items = db.execute("SELECT source, ref, name, reason, address FROM review ORDER BY source, ref LIMIT 200")
                return self.json(200, {"items": [dict(item) for item in items]})
            inventory = [{**dict(row), **SOURCE_METADATA.get(row["id"], {})} for row in db.execute("SELECT id, name, count, url FROM sources ORDER BY rowid")]
            sources = [source for source in inventory if source.get("count", 0) > 0] + operations.approved_sources()
            return self.json(200, {
                "sources": sources,
                "planned_source_count": sum(source.get("count", 0) == 0 for source in inventory),
                "mode": MODE,
                "storage_engine": "Canonical JSON/GeoJSON (dane.gov.pl) + SQLite R-Tree Spatial Index",
                "sync_schedule": operations.RUN.get("schedule", "codziennie (co 24h)"),
                "next_sync_at": operations.RUN.get("next_sync_at"),
                "site_count": db.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
                              + sum(row["coordinate_status"] == "located" for row in operations.published()),
                "review_count": db.execute("SELECT COUNT(*) FROM review").fetchone()[0],
                "generated_at": db.execute("SELECT generated_at FROM metadata").fetchone()[0],
            })

    def asset(self, path):
        relative = unquote(path).lstrip("/")
        if relative.startswith("video/"):
            target = (VIDEO / relative.removeprefix("video/")).resolve()
            if not target.is_relative_to(VIDEO) or not target.is_file():
                return self.json(404, {"error": "Nie znaleziono pliku wideo."})
            content_type = mimetypes.guess_type(target)[0] or "application/octet-stream"
            if target.suffix in {".js", ".png", ".jpg", ".jpeg", ".svg", ".webp"}:
                return self.reply(200, target.read_bytes(), content_type, "no-cache")
            size = target.stat().st_size
            range_header = self.headers.get("Range", "")
            if range_header.startswith("bytes="):
                try:
                    start_s, end_s = range_header.removeprefix("bytes=").split("-", 1)
                    start = int(start_s) if start_s else 0
                    end = min(size - 1, int(end_s)) if end_s else size - 1
                    if 0 <= start <= end < size:
                        with open(target, "rb") as f:
                            f.seek(start)
                            chunk = f.read(end - start + 1)
                        self.send_response(206)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(chunk)))
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        if self.command != "HEAD":
                            self.wfile.write(chunk)
                        return
                except ValueError:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(target.read_bytes())
            return
        if not relative or relative in {"kampania", "promo", "o-projekcie"}:
            relative = "promo.html"
        elif relative in {"app", "mapa-aed", "mapa"}:
            relative = "index.html"
        elif relative in {"zglos", "panel"}:
            relative += ".html"
        asset = (STATIC / relative).resolve()
        if not asset.is_relative_to(STATIC) or not asset.is_file():
            return self.json(404, {"error": "Nie znaleziono zasobu."})
        content_type = mimetypes.guess_type(asset)[0] or "application/octet-stream"
        if relative == "sw.js":
            # Clearing all origin caches here erases the very PWA data being installed.
            return self.reply(200, asset.read_bytes(), content_type, "no-cache, no-store")
        if relative in {"promo.html", "promo.css", "promo.js"}:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            payload = asset.read_bytes()
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Clear-Site-Data", '"cache"')
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            return
        self.reply(200, asset.read_bytes(), content_type, "no-cache")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    if not DB.is_file() or not REGISTRY_JSON.is_file():
        build()
    operations.admin_token()
    operations.start_daily_scheduler()
    with ThreadingHTTPServer((args.host, args.port), Dashboard) as server:
        print(f"Odblokuj AED · Serce Okolicy: http://{args.host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
