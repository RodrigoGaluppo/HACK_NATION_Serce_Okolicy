"""Download, normalize and reconcile the local AED snapshot into SQLite."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
DB = DATA / "aed.sqlite3"
SOURCES = {
    "osm": ("OpenAEDMap / OpenStreetMap", "https://openaedmap.org/api/v1/countries/PL.geojson", "osm.geojson"),
    "krosno": ("Miasto Krosno", "https://api.dane.gov.pl/media/resources/20240219/Defibrylator_jAmxQcp.csv", "krosno.csv"),
    "przemysl": ("Miasto Przemyśl", "https://api.dane.gov.pl/media/resources/20241106/1730818801_b50R6UVxPgoVdBbq.geojson", "przemysl.geojson"),
    "marki": ("Miasto Marki", "https://api.dane.gov.pl/media/resources/20250710/Defibrylator_GminaMiastoMarki_1.csv", "marki.csv"),
}
CITIES = {"krosno": "Krosno", "przemysl": "Przemyśl", "marki": "Marki"}
MARKI_BOX = (52.30, 52.40, 21.06, 21.20)
POLAND_BOX = (49.0, 55.0, 14.0, 24.3)
PRIVATE_TEXT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)(?:\+48[. -]?)?\d{3}[. -]?\d{3}[. -]?\d{3}(?!\w)"
    r"|\b(?:kod(?: dostępu)?|PIN)\s*[:#=]?\s*\d{3,8}\b", re.IGNORECASE
)


@dataclass
class Observation:
    source: str
    ref: str
    name: str
    lat: float
    lon: float
    address: str = ""
    municipality: str = ""
    placement: str = ""
    access: str = ""
    hours: str = ""
    checked_on: str = ""
    transformation: str = ""

    @property
    def id(self):
        return f"{self.source}:{self.ref}"


def normalize(value):
    value = value.casefold().replace("ł", "l")
    normalized = unicodedata.normalize("NFKD", value)
    letters = (c if c.isalnum() else " " for c in normalized if not unicodedata.combining(c))
    return " ".join("".join(letters).split())


def distance(lat1, lon1, lat2, lon2):
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    h = math.sin(delta_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(delta_lon / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def in_box(lat, lon, box):
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def clean(value):
    return str(value).strip()[:500] if value is not None else ""


def public_text(value):
    return " ".join(PRIVATE_TEXT.sub("", clean(value)).split())


def parse_geojson(source, raw):
    geo = json.loads(raw)
    if geo.get("type") != "FeatureCollection" or not isinstance(geo.get("features"), list):
        raise ValueError("Expected a GeoJSON FeatureCollection")
    observations = []
    for feature in geo["features"]:
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = map(float, geom["coordinates"][:2])
        p = feature.get("properties") or {}
        if source == "osm":
            if p.get("emergency") != "defibrillator" or not p.get("@osm_id"):
                continue
            ref = f"{p.get('@osm_type', 'node')}-{p['@osm_id']}"
            name = p.get("name") or p.get("operator") or p.get("description") or "Defibrylator AED"
            municipality = p.get("addr:city")
            address = " ".join(v for v in map(clean, (p.get("addr:street"), p.get("addr:housenumber"), municipality)) if v)
            placement = p.get("defibrillator:location:pl") or p.get("defibrillator:location")
            observation = Observation(source, ref, public_text(name) or "Defibrylator AED", lat, lon,
                                      public_text(address), public_text(municipality),
                                      public_text(placement), clean(p.get("access")).lower(),
                                      clean(p.get("opening_hours")), clean(p.get("check_date")))
            if not in_box(lat, lon, POLAND_BOX):
                continue
        else:
            if p.get("id") is None:
                raise ValueError("Przemyśl observation without ID")
            address = " ".join(v for v in map(clean, (p.get("street"), p.get("home_number"), p.get("postcode"), p.get("city"))) if v)
            observation = Observation(source, str(p["id"]), clean(p.get("name")) or "Defibrylator AED",
                                      lat, lon, address, clean(p.get("city")) or CITIES[source])
        observations.append(observation)
    return observations


def parse_csv(source, raw):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), strict=True))
    if len(rows[0]) == 1:
        rows = [next(csv.reader([row[0]], skipinitialspace=True, strict=True)) for row in rows if row]
    headers = [normalize(cell) for cell in rows[0]]
    expected = ["dlugosc geograficzna", "szerokosc geograficzna", "nazwa", "lokalizacja", "adres", "numer id"]
    columns = [headers.index(name) for name in expected]
    observations = []
    for row in rows[1:]:
        if not row:
            continue
        lon, lat, name, placement, address, ref = [clean(row[idx]) for idx in columns]
        lat, lon = float(lat), float(lon)
        swapped = source == "marki" and not in_box(lat, lon, MARKI_BOX) and in_box(lon, lat, MARKI_BOX)
        if swapped:
            lat, lon = lon, lat
        if not ref:
            raise ValueError(f"{source} observation without ID")
        observations.append(Observation(source, ref, placement or name, lat, lon, address, CITIES[source],
                                        transformation="zamiana osi" if swapped else ""))
    return observations


def parse(source, raw):
    observations = parse_csv(source, raw) if SOURCES[source][2].endswith(".csv") else parse_geojson(source, raw)
    if not observations or len({o.ref for o in observations}) != len(observations):
        raise ValueError(f"{source} snapshot is empty or has duplicate IDs")
    return observations


def refresh(source):
    _, url, filename = SOURCES[source]
    path = RAW / filename
    try:
        request = Request(url, headers={"User-Agent": "OdblokujAED/1.0 (local registry prototype)"})
        with urlopen(request, timeout=25) as response:
            payload = response.read(32 * 1024 * 1024 + 1)
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError("Snapshot exceeds size limit")
        parse(source, payload)
        with tempfile.NamedTemporaryFile(dir=RAW, delete=False) as temp:
            temp.write(payload)
            temp_path = Path(temp.name)
        try:
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
        print(f"{source}: zapisano {len(payload):,} B")
        return True
    except (OSError, ValueError, IndexError, KeyError, TypeError, csv.Error) as exc:
        print(f"{source}: {exc}. Zachowano poprzedni plik, jeśli istnieje.")
        return False


def grid_cell(observation):
    return math.floor(observation.lat * 500), math.floor(observation.lon * 500)


def match_score(observation, candidate, separation):
    if candidate.access in {"private", "no"}:
        return None
    left_address, right_address = normalize(observation.address), normalize(candidate.address)
    if left_address and left_address == right_address:
        return 0
    left, right = normalize(observation.name), normalize(candidate.name)
    generic = {"defibrylator aed", "defibrylator", "aed"}
    if left == right and left not in generic:
        return 1
    if separation <= 0.012 and not (left_address and right_address):
        return 2
    return None


def reconcile(observations):
    baseline = {o.id: [o] for o in observations.get("osm", ())}
    grid = defaultdict(list)
    for members in baseline.values():
        grid[grid_cell(members[0])].append(members[0])
    review = []
    municipal_claims = set()
    marki_coords = Counter((o.lat, o.lon) for o in observations.get("marki", ()))

    for source in CITIES:
        for observation in observations.get(source, ()):
            reason = ""
            if not in_box(observation.lat, observation.lon, MARKI_BOX if source == "marki" else POLAND_BOX):
                reason = "Współrzędne poza zasięgiem źródła."
            elif source == "marki" and marki_coords[observation.lat, observation.lon] > 1:
                reason = "Współrzędne dzielone przez różne adresy."
            else:
                row, col = grid_cell(observation)
                nearby = []
                for y in range(row - 1, row + 2):
                    for x in range(col - 1, col + 2):
                        for candidate in grid.get((y, x), ()):
                            separation = distance(observation.lat, observation.lon, candidate.lat, candidate.lon)
                            if separation <= 0.1:
                                nearby.append((candidate, separation))

                matches = []
                for candidate, separation in nearby:
                    if separation <= 0.025:
                        score = match_score(observation, candidate, separation)
                        if score is not None:
                            matches.append((score, separation, candidate))
                matches.sort(key=lambda match: (match[0], match[1], match[2].id))
                if matches:
                    score, _, candidate = matches[0]
                    claimed = (source, candidate.id)
                    ambiguous = len(matches) > 1 and matches[1][0] == score
                    if not ambiguous and claimed not in municipal_claims:
                        municipal_claims.add(claimed)
                        baseline[candidate.id].append(observation)
                        continue
                    reason = "Niejednoznaczne dopasowanie do OpenStreetMap."
                elif nearby and min(pair[1] for pair in nearby) <= 0.025:
                    reason = "Bliski punkt wymaga potwierdzenia tożsamości urządzenia."
                elif source == "przemysl" and not nearby:
                    reason = "Kandydat bez punktu OpenStreetMap w promieniu 100 m."
            if reason:
                review.append((source, observation.ref, observation.name, reason, observation.address))
            else:
                baseline[observation.id] = [observation]
    return baseline, review


def build():
    observations = {}
    for source, (_, _, filename) in SOURCES.items():
        path = RAW / filename
        if path.is_file():
            observations[source] = parse(source, path.read_bytes())
    if not observations:
        raise ValueError("Brak danych lokalnych. Uruchom: python3 prepare_data.py --refresh")
    groups, review = reconcile(observations)
    with tempfile.NamedTemporaryFile(dir=DATA, delete=False) as temp:
        new_db = Path(temp.name)
    try:
        db = sqlite3.connect(new_db)
        with db:
            db.executescript("""
                CREATE TABLE sites (
                    rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    lat REAL NOT NULL, lon REAL NOT NULL, address TEXT, municipality TEXT,
                    placement TEXT, access TEXT, hours TEXT, sources TEXT NOT NULL,
                    checked_on TEXT, field_sources TEXT NOT NULL, search_text TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE sites_geo USING rtree(rowid, min_lat, max_lat, min_lon, max_lon);
                CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT, count INTEGER, url TEXT);
                CREATE TABLE review (source TEXT, ref TEXT, name TEXT, reason TEXT, address TEXT);
                CREATE TABLE metadata (generated_at TEXT);
                CREATE TABLE field_evidence (
                    aed_id TEXT NOT NULL, field TEXT NOT NULL, source TEXT NOT NULL,
                    upstream_id TEXT NOT NULL, transformation TEXT NOT NULL,
                    PRIMARY KEY (aed_id, field)
                );
            """)
            db.executemany("INSERT INTO sources VALUES (?,?,?,?)", [
                (source, label, len(observations[source]), url)
                for source, (label, url, _) in SOURCES.items() if source in observations
            ])
            db.executemany("INSERT INTO review VALUES (?,?,?,?,?)", review)
            db.execute("INSERT INTO metadata VALUES (?)", (datetime.now(timezone.utc).isoformat(),))
            for primary, *support in groups.values():
                if primary.access in {"private", "no"}:
                    continue
                members = [primary, *support]
                chosen = {}
                for field in ("name", "address", "municipality", "placement", "access", "hours", "checked_on"):
                    ranked = [*support, primary] if field in {"name", "address", "municipality"} else members
                    chosen[field] = next((o for o in ranked if getattr(o, field)), primary)
                values = {field: getattr(o, field) for field, o in chosen.items()}
                provenance = {field: o.source for field, o in chosen.items() if values[field]}
                provenance["coordinates"] = primary.source
                search = normalize(" ".join(o.name + " " + o.address + " " + o.municipality + " " + o.placement for o in members))
                cursor = db.execute(
                    "INSERT INTO sites VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (primary.id, values["name"], primary.lat, primary.lon, values["address"], values["municipality"],
                     values["placement"], values["access"], values["hours"], json.dumps([o.source for o in members]),
                     values["checked_on"], json.dumps(provenance), search),
                )
                db.execute("INSERT INTO sites_geo VALUES (?,?,?,?,?)", (cursor.lastrowid, primary.lat, primary.lat, primary.lon, primary.lon))
                evidence = [(primary.id, "coordinates", primary.source, primary.ref, primary.transformation)]
                evidence.extend((primary.id, field, o.source, o.ref, o.transformation)
                                for field, o in chosen.items() if values[field])
                db.executemany("INSERT INTO field_evidence VALUES (?,?,?,?,?)", evidence)
            site_count, = db.execute("SELECT count(*) FROM sites").fetchone()
        db.close()
        new_db.replace(DB)
        print(f"Rejestr: {site_count:,} punktów, {len(review)} do sprawdzenia.")
    finally:
        new_db.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Pobierz i zweryfikuj migawki przed aktualizacją indeksu.")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(refresh, SOURCES))
    build()
