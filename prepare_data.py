"""Download, normalize and reconcile all Polish AED sources into canonical dane.gov.pl JSON/GeoJSON/CSV and SQLite."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
import os
import ipaddress
import socket
from urllib.parse import urlparse
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
FETCH_LOCK = threading.Lock()
BUILD_LOCK = threading.RLock()
import unicodedata
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
DB = DATA / "aed.sqlite3"
REGISTRY_JSON = DATA / "aed_registry.json"
PUBLIC_GEOJSON = DATA / "aed.geojson"
PUBLIC_CSV = DATA / "aed.csv"
PORTAL_METADATA_JSON = DATA / "portal-metadata.json"

FIELDS = (
    "aed_id", "site_name", "locality", "municipality", "teryt", "street", "house_number", "postcode",
    "coordinate_status", "longitude", "latitude", "coordinate_accuracy_m", "placement", "indoor_outdoor",
    "level", "cabinet_lock_status", "access_instructions", "device_type", "access_type", "opening_hours",
    "access_status", "readiness_status", "public_operator_name", "public_operator_contact_url",
    "location_checked_on", "access_checked_on", "readiness_checked_on", "is_stale", "source_ids", "field_sources"
)

SOURCES = {
    "osm": (
        "OpenAEDMap / OpenStreetMap Polska",
        "https://openaedmap.org/api/v1/countries/PL.geojson",
        "osm.geojson",
    ),
    "krosno": (
        "Miasto Krosno (dane.gov.pl #3624)",
        "https://api.dane.gov.pl/media/resources/20240219/Defibrylator_jAmxQcp.csv",
        "krosno.csv",
    ),
    "przemysl": (
        "Miasto Przemyśl (dane.gov.pl #4581)",
        "https://api.dane.gov.pl/media/resources/20241106/1730818801_b50R6UVxPgoVdBbq.geojson",
        "przemysl.geojson",
    ),
    "marki": (
        "Gmina Miasto Marki (dane.gov.pl #4955)",
        "https://api.dane.gov.pl/media/resources/20250710/Defibrylator_GminaMiastoMarki_1.csv",
        "marki.csv",
    ),
    "warszawa": (
        "Urząd m.st. Warszawy (dane.gov.pl #39512 / SCB)",
        "https://dane.um.warszawa.pl/pl/catalogue/7bc32ffc-c2ac-4d32-83c9-b6f7a0b38de8",
        "warszawa.geojson",
    ),
    "inpost": (
        "Sieć Paczkomat® InPost AED",
        "https://inpost.pl/aktulanosci-defibrylatory-AED-lokalizacje",
        "inpost.geojson",
    ),
    "bydgoszcz": (
        "Miasto Bydgoszcz – Miejski Rejestr AED",
        "https://www.bydgoszcz.pl/",
        "bydgoszcz.geojson",
    ),
    "trojmiasto": (
        "Otwarte Dane Trójmiasto (Gdańsk · Gdynia · Sopot)",
        "https://ckan.multimediagdansk.pl/",
        "trojmiasto.geojson",
    ),
    "krakow": (
        "MSIP Kraków – Małopolski Rejestr AED",
        "https://msip.krakow.pl/",
        "krakow.geojson",
    ),
    "wroclaw": (
        "Otwarte Dane Wrocław – Rejestr AED",
        "https://opendata.cui.wroclaw.pl/",
        "wroclaw.geojson",
    ),
    "poznan": (
        "SIP Poznań – Miejska Sieć AED",
        "https://www.poznan.pl/mim/plan/",
        "poznan.geojson",
    ),
    "katowice_gzm": (
        "Otwarte Dane GZM & Katowice",
        "https://otwartedane.metropoliagzm.pl/",
        "katowice_gzm.geojson",
    ),
    "pkp_transport": (
        "PKP S.A. & Węzły Transportowe (Dworce i Lotniska)",
        "https://www.pkp.pl/",
        "pkp_transport.geojson",
    ),
    "ratuj_z_sercem": (
        "Sieć Ratuj z Sercem · OSP · Edukacja",
        "https://www.ratujzsercem.pl/",
        "ratuj_z_sercem.geojson",
    ),
    "bzp_wawer": (
        "e-Zamówienia BZP & CRU/TED (Postępowanie 340/NZ/2026 CPV 33182100-0)",
        "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/08def2c5-4a57-0f74-962b-12000166a405",
        "bzp_wawer.json",
    ),
}

SOURCES["legionowo"] = ("Miasto Legionowo (dane.gov.pl #40593)",
    "https://api.dane.gov.pl/media/resources/20260914/aed.csv", "legionowo.csv")

SOURCE_METADATA = {
    "osm": {"scope": "Ogólnopolski", "license": "ODbL 1.0 (OpenStreetMap)", "cadence": "codziennie (24h)", "owner": "Społeczność OSM / OpenAEDMap"},
    "krosno": {"scope": "Krosno (woj. podkarpackie)", "license": "CC0 / Otwarte Dane dane.gov.pl", "cadence": "codziennie (24h)", "owner": "Urząd Miasta Krosna"},
    "przemysl": {"scope": "Przemyśl (woj. podkarpackie)", "license": "CC0 / Otwarte Dane dane.gov.pl", "cadence": "codziennie (24h)", "owner": "Urząd Miejski w Przemyślu"},
    "marki": {"scope": "Marki (woj. mazowieckie)", "license": "CC0 / Otwarte Dane dane.gov.pl", "cadence": "codziennie (24h)", "owner": "Urząd Miasta Marki"},
    "warszawa": {"scope": "m.st. Warszawa (woj. mazowieckie)", "license": "CC BY 4.0 (dane.gov.pl #39512)", "cadence": "codziennie (24h)", "owner": "Urząd m.st. Warszawy (SCB)"},
    "inpost": {"scope": "Ogólnopolski (Sieć Paczkomat®)", "license": "Dane publiczne operatora", "cadence": "codziennie (24h)", "owner": "InPost sp. z o.o."},
    "bydgoszcz": {"scope": "Bydgoszcz (woj. kujawsko-pomorskie)", "license": "Otwarte Dane Miejskie", "cadence": "codziennie (24h)", "owner": "Miasto Bydgoszcz"},
    "trojmiasto": {"scope": "Gdańsk, Gdynia, Sopot (woj. pomorskie)", "license": "Otwarty Gdańsk / CC BY 4.0", "cadence": "codziennie (24h)", "owner": "Trójmiejski Rejestr AED"},
    "krakow": {"scope": "Kraków (woj. małopolskie)", "license": "Otwarte Dane MSIP Kraków", "cadence": "codziennie (24h)", "owner": "Urząd Miasta Krakowa"},
    "wroclaw": {"scope": "Wrocław (woj. dolnośląskie)", "license": "Otwarte Dane Wrocław", "cadence": "codziennie (24h)", "owner": "Urząd Miejski Wrocławia"},
    "poznan": {"scope": "Poznań (woj. wielkopolskie)", "license": "Otwarte Dane SIP Poznań", "cadence": "codziennie (24h)", "owner": "Urząd Miasta Poznania"},
    "katowice_gzm": {"scope": "Metropolia GZM / Katowice (woj. śląskie)", "license": "Otwarte Dane GZM", "cadence": "codziennie (24h)", "owner": "Górnośląsko-Zagłębiowska Metropolia"},
    "pkp_transport": {"scope": "Ogólnopolski (Dworce PKP i Lotniska)", "license": "Informacja publiczna", "cadence": "codziennie (24h)", "owner": "PKP S.A. / Zarządcy Węzłów"},
    "ratuj_z_sercem": {"scope": "Ogólnopolski (OSP, Szkoły, Instytucje)", "license": "Otwarte dane społeczne", "cadence": "codziennie (24h)", "owner": "Sieć Ratuj z Sercem / OSP"},
    "bzp_wawer": {"scope": "Warszawa Wawer + Ogólnopolski BZP/TED", "license": "Informacja o zamówieniach publicznych", "cadence": "codziennie (24h)", "owner": "Urząd Zamówień Publicznych (BZP)"},
}

# Only downloaded, attributable sources enter the public registry. Existing regional
# demo snapshots are retained on disk for review, never silently published.
LIVE_SOURCES = {"osm", "krosno", "przemysl", "marki", "inpost", "warszawa", "legionowo"}
CATALOGUE_DATASETS = {"krosno": "3624", "przemysl": "4581", "marki": "4955", "legionowo": "40593"}
SOURCE_CONFIG = DATA / "source-config.json"
FETCH_STATE = DATA / "source-fetch-state.json"
for _key, _meta in SOURCE_METADATA.items():
    _meta["status"] = "configured" if _key in LIVE_SOURCES else "awaiting_adapter"
    if _key not in {"osm"}:
        _meta["license"] = "Warunki ponownego wykorzystania wymagają przeglądu wydawcy"
SOURCE_METADATA["osm"].update(license_reviewed=True, license_url="https://www.openstreetmap.org/copyright")
SOURCE_METADATA["inpost"].update(license_reviewed=False, license="Publiczna lista operatora; warunki redystrybucji wymagają zatwierdzenia wydawcy")
SOURCE_METADATA["warszawa"]["status"] = "configured" if os.getenv("WARSAW_API_TOKEN") else "requires_api_token"
SOURCE_METADATA["bzp_wawer"]["status"] = "procurement_lead_only"

SOURCE_METADATA["legionowo"] = {"scope": "Legionowo (woj. mazowieckie)", "license": "CC0 1.0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/", "cadence": "codziennie (24h)",
    "owner": "Gmina Miejska Legionowo", "status": "configured", "license_reviewed": True,
    "id_policy": "SHA-256 nazwy i adresu; źródło nie publikuje identyfikatora urządzenia. Zmiany nazwy/adresu wymagają przeglądu dopasowania."}

for _key, _license in {"krosno": "CC0 1.0", "przemysl": "CC0 1.0", "marki": "CC BY 4.0"}.items():
    SOURCE_METADATA[_key].update(license=_license, license_reviewed=True,
        license_metadata_url="https://api.dane.gov.pl/1.4/datasets/" + CATALOGUE_DATASETS[_key])


def load_custom_sources():
    if SOURCE_CONFIG.is_file():
        for item in json.loads(SOURCE_CONFIG.read_text(encoding="utf-8")):
            key = item["id"]
            SOURCES[key] = (item["name"], item["url"], key + ".geojson")
            SOURCE_METADATA[key] = {**item, "status": "configured", "cadence": "codziennie (24h)"}
            LIVE_SOURCES.add(key)


def public_download(url, *, headers=None, data=None, limit=32 * 1024 * 1024):
    """Bounded HTTPS fetch; validate DNS and every redirect against private networks."""
    from urllib.request import HTTPRedirectHandler, build_opener
    def check(value):
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Źródło musi mieć publiczny adres HTTPS.")
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Prywatne i lokalne adresy źródeł są zabronione.")
    class Redirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            check(newurl)
            return super().redirect_request(req, fp, code, msg, hdrs, newurl)
    check(url)
    req = Request(url, data=data, headers={"User-Agent": "OdblokujAED/1.1", **(headers or {})})
    with build_opener(Redirect()).open(req, timeout=25) as response:
        result = response.read(limit + 1)
    if len(result) > limit:
        raise ValueError("Snapshot exceeds size limit")
    return result


def catalogue_resource(source):
    url = "https://api.dane.gov.pl/1.4/datasets/" + CATALOGUE_DATASETS[source] + "/resources?page_size=100"
    wanted = "csv" if SOURCES[source][2].endswith(".csv") else "geojson"
    candidates = []
    for _ in range(20):
        page = json.loads(public_download(url))
        candidates.extend(r["attributes"] for r in page["data"] if r["attributes"].get("format", "").lower() == wanted
            and ("defib" in normalize(r["attributes"].get("title", "")) or "aed" in normalize(r["attributes"].get("title", "")).split()))
        url = page.get("links", {}).get("next")
        if not url:
            break
    if not candidates:
        raise ValueError("Brak zgodnego zasobu katalogu")
    resource = max(candidates, key=lambda r: (r.get("data_date") or "", r.get("modified") or ""))
    dataset = json.loads(public_download("https://api.dane.gov.pl/1.4/datasets/" + CATALOGUE_DATASETS[source]))["data"]["attributes"]
    resource["_license"] = dataset.get("license_name") or "Warunki wymagają przeglądu wydawcy"
    resource["_custom_terms"] = dataset.get("license_condition_custom_description") or dataset.get("license_description") or ""
    return resource


def fetch_state():
    try:
        return json.loads(FETCH_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


load_custom_sources()
for _key, _state in fetch_state().items():
    if _key in SOURCE_METADATA and _state.get("license"):
        SOURCE_METADATA[_key].update(license=_state["license"], custom_terms=_state.get("custom_terms", ""),
            license_reviewed=_state.get("license_reviewed", False))

CITIES = {
    "krosno": "Krosno",
    "przemysl": "Przemyśl",
    "marki": "Marki",
    "warszawa": "Warszawa",
    "inpost": "Polska",
    "bydgoszcz": "Bydgoszcz",
    "trojmiasto": "Gdańsk",
    "krakow": "Kraków",
    "wroclaw": "Wrocław",
    "poznan": "Poznań",
    "katowice_gzm": "Katowice",
    "pkp_transport": "Polska",
    "ratuj_z_sercem": "Polska",
}

TERYT_MAP = {
    "warszawa": "1465011",
    "krosno": "1861011",
    "przemysl": "1862011",
    "marki": "1434021",
    "bydgoszcz": "0461011",
    "gdansk": "2261011",
    "gdynia": "2262011",
    "sopot": "2264011",
    "krakow": "1261011",
    "wroclaw": "0264011",
    "poznan": "3064011",
    "katowice": "2469011",
    "lodz": "1061011",
    "szczecin": "3262011",
    "lublin": "0663011",
    "bialystok": "2061011",
    "rzeszow": "1863011",
    "kielce": "2661011",
    "olsztyn": "2862011",
    "opole": "1661011",
    "zielona gora": "0862011",
    "gorzow wielkopolski": "0861011",
    "torun": "0463011",
}

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
    street: str = ""
    house_number: str = ""
    postcode: str = ""
    placement: str = ""
    access: str = ""
    hours: str = ""
    checked_on: str = ""
    transformation: str = ""
    level: str = ""
    indoor_outdoor: str = ""
    cabinet_lock_status: str = ""
    access_instructions: str = ""
    operator: str = ""

    @property
    def id(self):
        return f"{self.source}:{self.ref}"


def normalize(value):
    value = (value or "").casefold().replace("ł", "l")
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
    seen_refs = set()
    for feature in geo["features"]:
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coordinates = geom["coordinates"]
        if coordinates and isinstance(coordinates[0], list):
            coordinates = coordinates[0]
        lon, lat = map(float, coordinates[:2])
        p = feature.get("properties") or {}
        if source == "osm":
            if p.get("emergency") != "defibrillator" or not p.get("@osm_id"):
                continue
            ref = f"{p.get('@osm_type', 'node')}-{p['@osm_id']}"
            name = p.get("name") or p.get("operator") or p.get("description") or "Defibrylator AED"
            municipality = public_text(p.get("addr:city"))
            street = public_text(p.get("addr:street"))
            house_number = public_text(p.get("addr:housenumber"))
            postcode = public_text(p.get("addr:postcode"))
            address = " ".join(v for v in (street, house_number, postcode, municipality) if v)
            placement = p.get("defibrillator:location:pl") or p.get("defibrillator:location")
            indoor_val = clean(p.get("indoor")).lower()
            indoor_outdoor = "indoor" if indoor_val == "yes" else ("outdoor" if indoor_val == "no" else "unknown")
            locked_val = clean(p.get("locked")).lower()
            lock_status = "locked" if locked_val == "yes" else ("unlocked" if locked_val == "no" else "unknown")
            observation = Observation(
                source=source,
                ref=ref,
                name=public_text(name) or "Defibrylator AED",
                lat=lat,
                lon=lon,
                address=public_text(address),
                municipality=municipality,
                street=street,
                house_number=house_number,
                postcode=postcode,
                placement=public_text(placement),
                access=clean(p.get("access")).lower(),
                hours=clean(p.get("opening_hours")),
                checked_on=clean(p.get("check_date") or p.get("survey:date")),
                level=public_text(p.get("level")),
                indoor_outdoor=indoor_outdoor,
                cabinet_lock_status=lock_status,
                access_instructions=public_text(p.get("access:description") or ""),
                operator=public_text(p.get("operator")),
            )
            if not in_box(lat, lon, POLAND_BOX):
                continue
        else:
            raw_id = p.get("id") or p.get("aed_id") or p.get("locker_id") or p.get("defibrillator_id") or feature.get("id")
            if raw_id is None:
                raise ValueError(f"{source} observation without ID")
            ref = str(raw_id)
            if ref in seen_refs:
                raise ValueError(f"{source} duplicate upstream ID: {ref}")
            seen_refs.add(ref)
            street = public_text(p.get("street") or p.get("location_street"))
            house_number = public_text(p.get("home_number") or p.get("house_number") or p.get("location_building"))
            postcode = public_text(p.get("postcode") or p.get("location_postcode"))
            municipality = public_text(p.get("city") or p.get("locality") or p.get("municipality") or p.get("location_city")) or CITIES.get(source, "")
            address = " ".join(v for v in (street, house_number, postcode, municipality) if v)
            raw_placement = p.get("placement") or p.get("location_description") or ""
            # Przemyśl generic description provides context only per implementation plan
            placement = "" if source == "przemysl" else public_text(raw_placement)
            observation = Observation(
                source=source,
                ref=ref,
                name=public_text(p.get("name") or p.get("site_name") or p.get("location_object_name")) or "Defibrylator AED",
                lat=lat,
                lon=lon,
                address=address,
                municipality=municipality,
                street=street,
                house_number=house_number,
                postcode=postcode,
                placement=placement,
                access=clean(p.get("access") or p.get("access_type") or ("public" if p.get("device_public_access") == "Publiczny" else "")).lower(),
                hours=clean(p.get("opening_hours") or ("24/7" if p.get("device_availability") == "24/7" else "")),
                checked_on=clean(p.get("check_date") or p.get("location_checked_on")),
                level=public_text(p.get("level")),
                indoor_outdoor=clean(p.get("indoor_outdoor")).lower(),
                cabinet_lock_status=clean(p.get("cabinet_lock_status")).lower(),
                access_instructions=public_text(p.get("access_instructions") or p.get("device_access_description")),
                operator=public_text(p.get("operator") or p.get("public_operator_name")),
            )
        observations.append(observation)
    return observations


def parse_csv(source, raw):
    if source == "legionowo":
        observations = []
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True):
            name = public_text(row["nazwa"])
            city = public_text(row["miejscowosc"])
            street = public_text(row["nazwa_ulicy"])
            house = public_text(row["nr_budynku"])
            postcode = public_text(row["kod_pocztowy"])
            address = " ".join(value for value in (street, house, postcode, city) if value)
            identity = "|".join(normalize(value) for value in (name, city, street, house, row.get("nr_lokalu", "")))
            ref = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
            observations.append(Observation(source=source, ref=ref, name=name,
                lat=float(row["szerokosc_geograficzna"]), lon=float(row["dlugosc_geograficzna"]),
                address=address, municipality=city, street=street, house_number=house, postcode=postcode,
                transformation="ID utworzony z nazwy i adresu; brak trwałego ID w źródle"))
        return observations
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
        observations.append(Observation(
            source=source,
            ref=ref,
            name=public_text(placement or name),
            lat=lat,
            lon=lon,
            address=public_text(address),
            municipality=CITIES[source],
            placement=public_text(placement),
            transformation="zamiana osi (walidacja granic miasta Marki)" if swapped else "",
        ))
    return observations


def parse(source, raw):
    filename = SOURCES[source][2]
    if filename.endswith(".json"):
        leads = json.loads(raw)
        if not isinstance(leads, list):
            raise ValueError(f"{source} JSON must be a list of leads")
        return leads
    observations = parse_csv(source, raw) if filename.endswith(".csv") else parse_geojson(source, raw)
    if not observations or len({o.ref for o in observations}) != len(observations):
        raise ValueError(f"{source} snapshot is empty or has duplicate IDs")
    return observations


def refresh_inpost():
    url = SOURCES["inpost"][1]
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 OdblokujAED/1.0"})
    with urlopen(request, timeout=20) as response:
        html = response.read(5 * 1024 * 1024).decode("utf-8", errors="ignore")
    codes = sorted(set(re.findall(r"\(([A-Z0-9]{5,12})\)", html)))
    if not codes:
        raise ValueError("Nie znaleziono kodów Paczkomat® AED na stronie InPost")

    def fetch_point(code):
        try:
            u = f"https://api-shipx-pl.easypack24.net/v1/points/{code}"
            req = Request(u, headers={"User-Agent": "Mozilla/5.0 OdblokujAED/1.0"})
            with urlopen(req, timeout=8) as r:
                d = json.loads(r.read().decode("utf-8"))
                loc = d.get("location") or {}
                addr = d.get("address_details") or {}
                if loc.get("longitude") and loc.get("latitude"):
                    return {
                        "type": "Feature",
                        "id": f"inpost-{code}",
                        "geometry": {"type": "Point", "coordinates": [float(loc["longitude"]), float(loc["latitude"])]},
                        "properties": {
                            "id": code,
                            "locker_id": code,
                            "name": f"Paczkomat® InPost {code} (Stacja AED)",
                            "operator": "InPost sp. z o.o.",
                            "city": addr.get("city") or "",
                            "street": addr.get("street") or "",
                            "home_number": addr.get("building_number") or "",
                            "postcode": addr.get("post_code") or "",
                            "placement": d.get("location_description") or "Zewnętrzny moduł AED przy urządzeniu Paczkomat®",
                            "access": "public",
                            "opening_hours": "",
                            "indoor_outdoor": "outdoor",
                            "cabinet_lock_status": "unknown",
                            "check_date": "",
                        },
                    }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetch_point, codes))
    previous = {}
    old_path = RAW / SOURCES["inpost"][2]
    if old_path.is_file() and fetch_state().get("inpost", {}).get("sha256"):
        try:
            previous = {str(f.get("properties", {}).get("id")): f for f in json.loads(old_path.read_bytes())["features"]}
        except (ValueError, KeyError, TypeError):
            pass
    # A failed ShipX lookup is not an operator withdrawal. Keep its last successful
    # observation, without changing its observation date.
    features = [result or previous.get(code) for code, result in zip(codes, results)]
    missing = [code for code, result in zip(codes, features) if result is None]
    if missing:
        raise ValueError(f"Niepełne geokodowanie InPost ({len(missing)} punktów); zachowano poprzednią migawkę")
    if not features:
        raise ValueError("Nie udało się pobrać punktów InPost ShipX")
    return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2).encode("utf-8")


def refresh(source):
    _, url, filename = SOURCES[source]
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / filename
    state = fetch_state()
    entry = {**state.get(source, {}), "attempted_at": datetime.now(timezone.utc).isoformat()}
    try:
        if source not in LIVE_SOURCES:
            raise ValueError("Źródło oczekuje na adapter i potwierdzenie pochodzenia migawki")
        if source == "inpost":
            payload = refresh_inpost()
        elif source == "warszawa":
            token = os.getenv("WARSAW_API_TOKEN")
            if not token:
                raise ValueError("Wymagany WARSAW_API_TOKEN; katalog zawiera dokumentację, nie rekordy")
            url = "https://dane.um.warszawa.pl/api/action/get_scb_lokalizacja_defibrylatorow"
            raw = json.loads(public_download(url, headers={"Authorization": token}, data=b"{}"))
            features = raw if isinstance(raw, list) else raw.get("result", raw.get("features", []))
            payload = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", **f} for f in features]}, ensure_ascii=False).encode()
        else:
            if source in CATALOGUE_DATASETS:
                resource = catalogue_resource(source)
                url = resource["download_url"]
                entry["upstream_data_date"] = resource.get("data_date")
                entry.update(license=resource["_license"], custom_terms=resource["_custom_terms"],
                    license_reviewed=resource["_license"] in {"CC0 1.0", "CC BY 4.0"} and not resource["_custom_terms"])
                SOURCE_METADATA[source].update(license=entry["license"], custom_terms=entry["custom_terms"], license_reviewed=entry["license_reviewed"])
            payload = public_download(url)
        parse(source, payload)
        checksum = hashlib.sha256(payload).hexdigest()
        if not path.is_file() or path.read_bytes() != payload:
            archive = RAW / "history" / source
            archive.mkdir(parents=True, exist_ok=True)
            (archive / (checksum + path.suffix)).write_bytes(payload)
            with tempfile.NamedTemporaryFile(dir=RAW, delete=False) as temp:
                temp.write(payload)
                temp_path = Path(temp.name)
            temp_path.replace(path)
        entry.update(status="ok", downloaded_from=url, sha256=checksum, retrieved_at=datetime.now(timezone.utc).isoformat(), error=None)
        print(f"{source}: zweryfikowano {len(payload):,} B")
        ok = True
    except (OSError, ValueError, IndexError, KeyError, TypeError, csv.Error) as exc:
        entry.update(status="failed", error=str(exc))
        print(f"{source}: {exc}. Zachowano poprzednią migawkę.")
        ok = False
    # A lock prevents parallel refreshes from overwriting each other's history.
    with FETCH_LOCK:
        state = fetch_state()
        state[source] = entry
        temp = FETCH_STATE.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(FETCH_STATE)
    return ok


def grid_cell(observation):
    return math.floor(observation.lat * 500), math.floor(observation.lon * 500)


def match_score(observation, candidate, separation):
    if candidate.access in {"private", "no"}:
        return None
    if separation <= 0.003:
        return 0
    left_address, right_address = normalize(observation.address), normalize(candidate.address)
    if left_address and left_address == right_address:
        return 0
    left, right = normalize(observation.name), normalize(candidate.name)
    generic = {"defibrylator aed", "defibrylator", "aed"}
    if left == right and left not in generic:
        return 1
    if separation <= 0.015 and not (left_address and right_address):
        return 2
    return None


def compute_confidence(sources, placement="", address="", access="", checked_on="", lock_status="", hours="", operator=""):
    unique_sources = set(sources)
    score = 25
    reasons = ["Źródło zawiera współrzędne WGS84; nie jest to kontrola w terenie"]
    if len(unique_sources) >= 3:
        score += 35
        reasons.append(f"Dopasowane rekordy z {len(unique_sources)} źródeł; niezależność wymaga oceny")
    elif len(unique_sources) == 2:
        score += 30
        reasons.append("Dopasowanie rekordów co najmniej dwóch źródeł")
    if placement or address:
        score += 15
        reasons.append("Szczegółowy opis lokalizacji szafki lub pełny adres")
    if access not in ("", None, "unknown"):
        score += 10
        reasons.append("Określony status dostępności publicznej")
    if hours not in ("", None, "unknown") or lock_status in ("unlocked", "locked", "not_applicable"):
        score += 5
        reasons.append("Informacja o godzinach dostępu lub stanie zamka szafki")
    if checked_on:
        try:
            age = (date.today() - date.fromisoformat(checked_on[:10])).days
            if 0 <= age <= 365:
                score += 15
                reasons.append("Potwierdzona data weryfikacji z ostatnich 365 dni")
        except ValueError:
            pass
    score = min(100, score)
    level = "high" if score >= 70 else ("medium" if score >= 45 else "low")
    return score, level, reasons


def reconcile(observations, leads):
    baseline = {o.id: [o] for o in observations.get("osm", ())}
    grid = defaultdict(list)
    for members in baseline.values():
        grid[grid_cell(members[0])].append(members[0])
    review = []
    municipal_claims = set()
    marki_coords = Counter((o.lat, o.lon) for o in observations.get("marki", ()))

    for lead in leads:
        review.append((
            lead.get("source", "bzp_wawer"),
            lead.get("ref", "BZP"),
            lead.get("name", "Zamówienie publiczne AED"),
            lead.get("reason", "Lead zakupowy oczekujący na potwierdzenie montażu."),
            lead.get("address", ""),
        ))

    for source in (key for key in observations if key != "osm"):
        for observation in observations.get(source, ()):
            reason = ""
            if not in_box(observation.lat, observation.lon, MARKI_BOX if source == "marki" else POLAND_BOX):
                reason = "Współrzędne poza zasięgiem źródła (kwarantanna – para współrzędnych wskazuje na Krosno)."
            elif source == "marki" and marki_coords[observation.lat, observation.lon] > 1:
                reason = "Współrzędne dzielone przez różne adresy w tym samym źródle."
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
                    if candidate.source == observation.source:
                        continue
                    if separation <= 0.030:
                        score = match_score(observation, candidate, separation)
                        if score is not None:
                            matches.append((score, separation, candidate))
                matches.sort(key=lambda match: (match[0], match[1], match[2].id))
                if matches:
                    score, _, candidate = matches[0]
                    claimed = (source, candidate.id)
                    ambiguous = len(matches) > 1 and matches[1][0] == score and matches[1][1] < 0.005
                    if not ambiguous and claimed not in municipal_claims:
                        municipal_claims.add(claimed)
                        baseline[candidate.id].append(observation)
                        continue
                    if source in {"krosno", "przemysl", "marki"}:
                        reason = "Niejednoznaczne dopasowanie do OpenStreetMap."
                    else:
                        baseline[observation.id] = [observation]
                        continue
                elif source in {"krosno", "przemysl", "marki"} and nearby and min(pair[1] for pair in nearby) <= 0.025:
                    reason = "Bliski punkt wymaga potwierdzenia tożsamości urządzenia."
                elif source == "przemysl" and not nearby:
                    reason = "Kandydat bez punktu OpenStreetMap w promieniu 100 m."
            if reason:
                review.append((source, observation.ref, observation.name, reason, observation.address))
            else:
                baseline[observation.id] = [observation]
                grid[grid_cell(observation)].append(observation)
    return baseline, review


def canonical_record(primary, support):
    members = [primary, *support]
    field_list = (
        "name", "address", "municipality", "street", "house_number", "postcode",
        "placement", "access", "hours", "checked_on", "level", "indoor_outdoor",
        "cabinet_lock_status", "access_instructions", "operator"
    )
    chosen = {}
    for field in field_list:
        ranked = [*support, primary] if field in {"name", "address", "municipality", "street", "house_number", "postcode", "placement", "cabinet_lock_status", "access_instructions", "operator"} else members
        chosen[field] = next((o for o in ranked if getattr(o, field)), primary)
    values = {field: getattr(o, field) for field, o in chosen.items()}

    raw_access = values["access"]
    access_type = "public" if raw_access in {"yes", "public", "designated", "permissive"} else ("unknown" if raw_access in {"", "unknown"} else "restricted")
    access_status = "available" if access_type == "public" else ("restricted" if access_type == "restricted" else "unknown")
    indoor_outdoor = values["indoor_outdoor"] if values["indoor_outdoor"] in {"indoor", "outdoor"} else "unknown"
    lock_status = values["cabinet_lock_status"] if values["cabinet_lock_status"] in {"locked", "unlocked", "not_applicable"} else "unknown"
    municipality = values["municipality"] or None
    teryt = TERYT_MAP.get(normalize(municipality or "")) if municipality else None
    checked_on = values["checked_on"] or None
    is_stale = False
    if checked_on:
        try:
            age = (date.today() - date.fromisoformat(checked_on)).days
            if age < 0:
                checked_on = None
            else:
                is_stale = age > 365
        except ValueError:
            checked_on = None

    source_ids = list(dict.fromkeys(o.source for o in members))
    field_sources = {"coordinates": primary.source}
    field_map = {
        "site_name": ("name", values["name"]),
        "locality": ("municipality", municipality),
        "municipality": ("municipality", municipality),
        "street": ("street", values["street"] or None),
        "house_number": ("house_number", values["house_number"] or None),
        "postcode": ("postcode", values["postcode"] or None),
        "placement": ("placement", values["placement"] or None),
        "indoor_outdoor": ("indoor_outdoor", indoor_outdoor if indoor_outdoor != "unknown" else None),
        "level": ("level", values["level"] or None),
        "cabinet_lock_status": ("cabinet_lock_status", lock_status if lock_status != "unknown" else None),
        "access_instructions": ("access_instructions", values["access_instructions"] or None),
        "access_type": ("access", access_type if access_type != "unknown" else None),
        "access_status": ("access", access_status if access_status != "unknown" else None),
        "opening_hours": ("hours", values["hours"] or None),
        "public_operator_name": ("operator", values["operator"] or None),
        "location_checked_on": ("checked_on", checked_on),

    }
    for pub_field, (obs_field, val) in field_map.items():
        if val:
            field_sources[pub_field] = chosen[obs_field].source

    conf_score, conf_level, conf_reasons = compute_confidence(
        source_ids,
        placement=values["placement"],
        address=values["address"],
        access=access_type,
        checked_on=checked_on,
        lock_status=lock_status,
        hours=values["hours"],
        operator=values["operator"],
    )

    record = {
        "aed_id": primary.id,
        "site_name": values["name"] or "Defibrylator AED",
        "locality": municipality,
        "municipality": municipality,
        "teryt": teryt,
        "street": values["street"] or None,
        "house_number": values["house_number"] or None,
        "postcode": values["postcode"] or None,
        "coordinate_status": "located",
        "longitude": round(primary.lon, 6),
        "latitude": round(primary.lat, 6),
        "coordinate_accuracy_m": None,
        "placement": values["placement"] or None,
        "indoor_outdoor": indoor_outdoor,
        "level": values["level"] or None,
        "cabinet_lock_status": lock_status,
        "access_instructions": values["access_instructions"] or None,
        "device_type": "fixed",
        "access_type": access_type,
        "opening_hours": values["hours"] or None,
        "access_status": access_status,
        "readiness_status": "unknown",
        "public_operator_name": values["operator"] or None,
        "public_operator_contact_url": None,
        "location_checked_on": checked_on,
        "access_checked_on": None,
        "readiness_checked_on": None,
        "is_stale": is_stale,
        "source_ids": source_ids,
        "field_sources": field_sources,
        "confidence": conf_score,
        "confidence_level": conf_level,
        "confidence_reasons": conf_reasons,
        # Aliases for seamless UI compatibility
        "id": primary.id,
        "name": values["name"] or "Defibrylator AED",
        "lat": round(primary.lat, 6),
        "lon": round(primary.lon, 6),
        "address": values["address"] or "",
        "access": access_type,
        "hours": values["hours"] or "",
        "checked_on": checked_on or "",
        "sources": source_ids,
    }
    return record, chosen, values


def write_canonical_files(records, source_rows, review_rows, generated_at):
    # 1. Write canonical JSON registry (data/aed_registry.json)
    registry_payload = {
        "schema": "dane.gov.pl/odblokuj-aed/v1",
        "generated_at": generated_at,
        "update_schedule": "codziennie (24h)",
        "total_count": len(records),
        "review_count": len(review_rows),
        "sources": source_rows,
        "review": [
            {"source": s, "ref": r, "name": n, "reason": rsn, "address": a}
            for s, r, n, rsn, a in review_rows
        ],
        "items": records,
    }
    REGISTRY_JSON.write_text(json.dumps(registry_payload, ensure_ascii=False), encoding="utf-8")

    # 2. Write canonical GeoJSON FeatureCollection (data/aed.geojson)
    features = [
        {
            "type": "Feature",
            "id": row["aed_id"],
            "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
            "properties": {
                key: row.get(key) if row.get(key) != "" else None
                for key in (*FIELDS, "confidence", "confidence_level")
                if key not in ("longitude", "latitude")
            },
        }
        for row in records
        if row.get("coordinate_status") == "located"
    ]
    geojson_bytes = json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    PUBLIC_GEOJSON.write_bytes(geojson_bytes)

    # 3. Write canonical RFC 4180 CSV (data/aed.csv)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(FIELDS)

    def csv_value(value):
        if value is None:
            return ""
        if isinstance(value, (dict, list, bool)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    for row in records:
        writer.writerow([csv_value(row.get(field)) for field in FIELDS])
    csv_bytes = stream.getvalue().encode("utf-8")
    PUBLIC_CSV.write_bytes(csv_bytes)

    # 4. Write portal-metadata.json
    content_hash = hashlib.sha256(csv_bytes + geojson_bytes).hexdigest()
    effective_dates = [fetch_state().get(row["id"], {}).get("upstream_data_date") or
        datetime.fromtimestamp((RAW / SOURCES[row["id"]][2]).stat().st_mtime, timezone.utc).date().isoformat()
        for row in source_rows if row.get("imported")]
    today_iso = max(effective_dates, default=None)
    if PORTAL_METADATA_JSON.is_file():
        try:
            previous = json.loads(PORTAL_METADATA_JSON.read_text())
            if previous.get("release", {}).get("content_sha256") == content_hash:
                today_iso = previous["release"]["data_date"]
        except (OSError, ValueError, KeyError):
            pass
    metadata = {
        "dataset": {
            "title": "Ogólnopolski rejestr defibrylatorów AED – Serce Okolicy / Odblokuj AED",
            "description": "Zintegrowany, otwarty zbiór danych o lokalizacji, dostępności, szafkach i poziomie pewności defibrylatorów AED w Polsce z wielu rozproszonych źródeł publicznych, samorządowych i operatorskich.",
            "category": "HEAL",
            "category_label": "Zdrowie (HEAL)",
            "keywords": ["AED", "defibrylatory", "ratownictwo", "pierwsza pomoc", "otwarte dane", "Serce Okolicy", "Odblokuj AED"],
            "language": "pl",
            "publisher": "Inicjatywa Serce Okolicy · Odblokuj AED",
            "reuse_terms": "© OpenStreetMap contributors, ODbL 1.0. Pozostałe warunki: zgodnie z inwentarzem źródeł; do przeglądu wydawcy.",
            "update_frequency": "codziennie",
            "geographic_scope": "Polska (16 województw)",
            "has_high_value_data": None,
            "has_dynamic_data": None,
        },
        "resources": [
            {
                "filename": "aed.csv",
                "title": "Ogólnopolski wykaz defibrylatorów AED (tabela CSV)",
                "description": "Tabela główna w standardzie RFC 4180 UTF-8 CRLF obejmująca rekordy z potwierdzonymi współrzędnymi oraz rekordy adresowe (coordinate_status=address_only).",
                "format": "csv",
                "media_type": "text/csv; charset=utf-8",
                "language": "pl",
                "data_date": today_iso,
                "record_count": len(records),
                "sha256": hashlib.sha256(csv_bytes).hexdigest(),
            },
            {
                "filename": "aed.geojson",
                "title": "Mapa defibrylatorów AED w Polsce (GeoJSON RFC 7946)",
                "description": "Widok przestrzenny (FeatureCollection Point WGS84 [longitude, latitude]) wszystkich zatwierdzonych urządzeń AED z potwierdzonymi współrzędnymi (coordinate_status=located).",
                "format": "geojson",
                "media_type": "application/geo+json",
                "language": "pl",
                "data_date": today_iso,
                "record_count": len(features),
                "sha256": hashlib.sha256(geojson_bytes).hexdigest(),
            },
        ],
        "release": {
            "generated_at": generated_at,
            "data_date": today_iso,
            "schema_version": "1.1",
            "content_sha256": content_hash,
            "status": "draft_pending_publisher_and_reuse_review",
            "sync_schedule": "codziennie (automatyczna synchronizacja co 24h)",
            "fields": list(FIELDS),
            "source_inventory": {
                key: {
                    "name": label,
                    "url": url,
                    **SOURCE_METADATA.get(key, {}),
                }
                for key, (label, url, _) in SOURCES.items()
            },
        },
    }
    PORTAL_METADATA_JSON.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def _build():
    observations = {}
    leads = [{"source": "bzp_wawer", "ref": "340/NZ/2026", "name": "Wawer: postępowanie 340/NZ/2026 (12 urządzeń w zakresie)",
        "reason": "Ręcznie wskazany lead z planu: CPV 33182100-0. Wymaga niezależnego potwierdzenia montażu; nie jest lokalizacją AED.",
        "address": "Warszawa Wawer"}]
    for source, (_, _, filename) in SOURCES.items():
        path = RAW / filename
        if path.is_file() and source in LIVE_SOURCES and (source in {"osm", "krosno", "przemysl", "marki"} or bool(fetch_state().get(source, {}).get("sha256"))):
            parsed = parse(source, path.read_bytes())
            if filename.endswith(".json"):
                leads.extend(parsed)
            else:
                observations[source] = parsed
    if not observations:
        raise ValueError("Brak danych lokalnych. Uruchom: python3 prepare_data.py --refresh")
    groups, review = reconcile(observations, leads)
    generated_at = datetime.now(timezone.utc).isoformat()
    source_rows = []
    for source, (label, url, filename) in SOURCES.items():
        count = len(leads) if filename.endswith(".json") else len(observations.get(source, ()))
        if count or (RAW / filename).is_file():
            source_rows.append({
                "id": source,
                "name": label,
                "count": count if source in observations else 0,
                "lead_count": len(leads) if source == "bzp_wawer" else 0,
                "url": url,
                "imported": source in observations,
                "held_snapshot": (RAW / filename).is_file() and source not in observations,
                "fetch": fetch_state().get(source),
                **SOURCE_METADATA.get(source, {}),
            })

    records = []
    with tempfile.NamedTemporaryFile(dir=DATA, delete=False) as temp:
        new_db = Path(temp.name)
    try:
        db = sqlite3.connect(new_db)
        with db:
            db.executescript("""
                CREATE TABLE sites (
                    rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    lat REAL NOT NULL, lon REAL NOT NULL, address TEXT, municipality TEXT,
                    street TEXT, house_number TEXT, postcode TEXT, teryt TEXT,
                    placement TEXT, indoor_outdoor TEXT, level TEXT, cabinet_lock_status TEXT,
                    access_instructions TEXT, access TEXT, hours TEXT, operator TEXT,
                    sources TEXT NOT NULL, checked_on TEXT, field_sources TEXT NOT NULL,
                    confidence INTEGER NOT NULL, confidence_level TEXT NOT NULL,
                    confidence_reasons TEXT NOT NULL, canonical_json TEXT NOT NULL,
                    search_text TEXT NOT NULL
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
            db.executemany(
                "INSERT INTO sources VALUES (?,?,?,?)",
                [(s["id"], s["name"], s["count"], s["url"]) for s in source_rows],
            )
            db.executemany("INSERT INTO review VALUES (?,?,?,?,?)", review)
            db.execute("INSERT INTO metadata VALUES (?)", (generated_at,))
            for primary, *support in groups.values():
                if primary.access in {"private", "no"}:
                    continue
                members = [primary, *support]
                record, chosen, values = canonical_record(primary, support)
                records.append(record)
                search = normalize(" ".join(
                    f"{o.name} {o.address} {o.municipality} {o.placement} {o.operator} {o.postcode}"
                    for o in members
                ))
                cursor = db.execute(
                    "INSERT INTO sites VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record["aed_id"], record["site_name"], record["latitude"], record["longitude"],
                        record["address"], record["municipality"] or "", record["street"] or "",
                        record["house_number"] or "", record["postcode"] or "", record["teryt"] or "",
                        record["placement"] or "", record["indoor_outdoor"], record["level"] or "",
                        record["cabinet_lock_status"], record["access_instructions"] or "",
                        record["access_type"], record["opening_hours"] or "",
                        record["public_operator_name"] or "",
                        json.dumps(record["source_ids"], ensure_ascii=False),
                        record["location_checked_on"] or "",
                        json.dumps(record["field_sources"], ensure_ascii=False),
                        record["confidence"], record["confidence_level"],
                        json.dumps(record["confidence_reasons"], ensure_ascii=False),
                        json.dumps(record, ensure_ascii=False),
                        search,
                    ),
                )
                db.execute(
                    "INSERT INTO sites_geo VALUES (?,?,?,?,?)",
                    (cursor.lastrowid, primary.lat, primary.lat, primary.lon, primary.lon),
                )
                evidence = [(primary.id, "coordinates", primary.source, primary.ref, primary.transformation)]
                evidence.extend(
                    (primary.id, field, o.source, o.ref, o.transformation)
                    for field, o in chosen.items() if values[field]
                )
                db.executemany("INSERT OR REPLACE INTO field_evidence VALUES (?,?,?,?,?)", evidence)
            site_count, = db.execute("SELECT count(*) FROM sites").fetchone()
        db.close()
        new_db.replace(DB)
        write_canonical_files(records, source_rows, review, generated_at)
        print(f"Rejestr: {site_count:,} punktów z {len(observations)} zaimportowanych źródeł, {len(review)} w kolejce weryfikacji. Zapisano pliki JSON/GeoJSON/CSV.")
    finally:
        new_db.unlink(missing_ok=True)


def build():
    with BUILD_LOCK:
        return _build()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Pobierz i zweryfikuj migawki przed aktualizacją indeksu.")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(refresh, SOURCES))
    build()
