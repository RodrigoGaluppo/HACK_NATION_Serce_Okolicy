"""Local connector controls, staged contributions and publication files."""
import base64
from contextlib import closing
import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import threading
from zipfile import ZipFile, ZIP_DEFLATED

from prepare_data import DATA, SOURCES, RAW, build, refresh

LOCK = threading.Lock()
RUN = {"state": "idle", "finished_at": None, "results": {}}
FIELDS = ("aed_id", "site_name", "locality", "municipality", "teryt", "street", "house_number", "postcode",
          "coordinate_status", "longitude", "latitude", "coordinate_accuracy_m", "placement", "indoor_outdoor",
          "level", "cabinet_lock_status", "access_instructions", "device_type", "access_type", "opening_hours",
          "access_status", "readiness_status", "public_operator_name", "public_operator_contact_url",
          "location_checked_on", "access_checked_on", "readiness_checked_on", "is_stale", "source_ids", "field_sources")
INTAKE = ("operator_device_id", "site_name", "municipality", "street", "house_number", "postcode",
          "longitude", "latitude", "placement", "level", "cabinet_lock_status", "access_instructions",
          "access_type", "opening_hours", "location_checked_on", "access_checked_on")
DAYS = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
TIME = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
END_TIME = rf"(?:{TIME}|24:00)"
HOURS = re.compile(rf"(?:(?:{DAYS}(?:-{DAYS})?)(?:,{DAYS}(?:-{DAYS})?)*\s+)?{TIME}-{END_TIME}(?:,{TIME}-{END_TIME})*")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    conn = sqlite3.connect(DATA / "operations.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id TEXT PRIMARY KEY, created TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
    )""")
    return conn


def admin_token():
    value = os.getenv("AED_ADMIN_TOKEN")
    if value:
        return value
    path = DATA / "admin-token"
    try:
        with open(path) as file:
            return file.read().strip()
    except FileNotFoundError:
        value = secrets.token_urlsafe(24)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
            file.write(value + "\n")
        return value


def connectors(sources):
    imported = {s["id"]: s["count"] for s in sources}
    with LOCK:
        run = {**RUN, "results": dict(RUN["results"])}
    return {"run": run, "items": [
        {"id": key, "name": name, "url": url, "format": path.rsplit(".", 1)[-1].upper(),
         "file": path, "count": imported.get(key, 0),
         "snapshot": datetime.fromtimestamp((RAW / path).stat().st_mtime, timezone.utc).isoformat()
                     if (RAW / path).is_file() else None,
         "last_result": run["results"].get(key)}
        for key, (name, url, path) in SOURCES.items()]}


def start_refresh(selected):
    if selected != "all" and selected not in SOURCES:
        raise ValueError("Nieznane źródło.")
    with LOCK:
        if RUN["state"] == "running":
            return False
        RUN.update(state="running", results={}, finished_at=None)

    def worker():
        state = "complete"
        try:
            for key in SOURCES if selected == "all" else (selected,):
                ok = refresh(key)
                with LOCK:
                    RUN["results"][key] = "updated" if ok else "kept_snapshot"
            build()
        except (OSError, ValueError, sqlite3.Error, csv.Error, KeyError, IndexError):
            state = "failed"
        finally:
            with LOCK:
                RUN.update(state=state, finished_at=now())

    threading.Thread(target=worker, daemon=True).start()
    return True


def template():
    return csv_line(INTAKE) + "\r\n"


def csv_line(values):
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerow(values)
    return buffer.getvalue().rstrip("\r\n")


def input_rows(body):
    fmt = body.get("format")
    data = body.get("data")
    if fmt == "form" and isinstance(data, dict):
        return [data]
    if fmt == "csv" and isinstance(data, str):
        text = data.lstrip("\ufeff")
        first = text.splitlines()[0] if text else ""
        dialect = ";" if first.count(";") > first.count(",") else ","
        return list(csv.DictReader(io.StringIO(text), delimiter=dialect, strict=True))
    if fmt == "geojson" and isinstance(data, str):
        geo = json.loads(data)
        if not isinstance(geo, dict) or geo.get("type") != "FeatureCollection" or not isinstance(geo.get("features"), list):
            raise ValueError("GeoJSON musi mieć typ FeatureCollection.")
        rows = []
        for feature in geo["features"]:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ValueError("Każdy rekord GeoJSON musi mieć typ Feature.")
            props = feature.get("properties")
            if not isinstance(props, dict):
                raise ValueError("Każdy rekord GeoJSON musi zawierać properties.")
            geom = feature.get("geometry")
            lon, lat = None, None
            if geom is not None:
                coords = geom.get("coordinates") if isinstance(geom, dict) and geom.get("type") == "Point" else None
                if not isinstance(coords, list) or len(coords) != 2 or any(type(x) not in (int, float) for x in coords):
                    raise ValueError("Geometria musi mieć typ Point i parę liczbową [długość, szerokość].")
                lon, lat = coords
            rows.append({**props, "operator_device_id": props.get("operator_device_id") or feature.get("id"),
                         "longitude": lon, "latitude": lat})
        return rows
    if fmt == "xlsx" and isinstance(data, str):
        from openpyxl import load_workbook
        raw = base64.b64decode(data, validate=True)
        from zipfile import BadZipFile
        try:
            with ZipFile(io.BytesIO(raw)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 12_000_000:
                    raise ValueError("Skoroszyt jest za duży.")
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
        except (BadZipFile, KeyError, OSError, SyntaxError) as exc:
            raise ValueError("Uszkodzony plik XLSX.") from exc
        try:
            if "Dane_AED" not in book:
                raise ValueError("Brak arkusza Dane_AED.")
            sheet = book["Dane_AED"]
            if sheet.max_row and sheet.max_row > 501:
                raise ValueError("Arkusz Dane_AED może zawierać do 500 wierszy danych.")
            rows = sheet.iter_rows(max_row=502, max_col=len(INTAKE), values_only=True)
            fields = next(rows, ())
            return [dict(zip(fields, row)) for row in rows if any(value is not None for value in row)]
        finally:
            book.close()
    raise ValueError("Wybierz formularz, CSV, GeoJSON lub XLSX.")


def validate(body):
    if body.get("consent") is not True:
        raise ValueError("Potwierdź możliwość publicznego udostępnienia danych.")
    provider = body.get("operator")
    if not isinstance(provider, str) or not 2 <= len(provider.strip()) <= 150:
        raise ValueError("Podaj nazwę organizacji (2–150 znaków).")
    rows = input_rows(body)
    if not 1 <= len(rows) <= 500:
        raise ValueError("Prześlij od 1 do 500 wierszy.")
    from prepare_data import public_text, POLAND_BOX, in_box
    clean, errors, refs = [], [], set()
    for number, row in enumerate(rows, 1):
        item = {}
        try:
            for key in INTAKE:
                value = row.get(key)
                if key.endswith("_on") and isinstance(value, date):
                    value = value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
                value = "" if value is None else str(value).strip()
                if len(value) > 500 or value.startswith("="):
                    raise ValueError("Zbyt długi tekst lub formuła w polu " + key)
                item[key] = value
            for key in ("operator_device_id", "site_name", "municipality", "placement"):
                if not item[key]:
                    raise ValueError("Uzupełnij " + key)
            if item["operator_device_id"] in refs:
                raise ValueError("Powtórzony identyfikator urządzenia.")
            refs.add(item["operator_device_id"])
            access = item["access_type"]
            if access not in {"public", "restricted", "unknown"}:
                raise ValueError("access_type: public, restricted albo unknown.")
            if item["cabinet_lock_status"] not in {"", "locked", "unlocked", "unknown", "not_applicable"}:
                raise ValueError("Nieprawidłowy stan zamka.")
            hours = item["opening_hours"]
            if hours not in {"", "24/7"} and not all(HOURS.fullmatch(part.strip()) for part in hours.split(";")):
                raise ValueError("Godziny w formacie 24/7 lub np. Mo-Fr 08:00-18:00. Zostaw puste, jeśli nieznane.")
            lon, lat = item["longitude"], item["latitude"]
            if bool(lat) != bool(lon):
                raise ValueError("Podaj obie współrzędne.")
            if lat:
                lon, lat = float(lon), float(lat)
                if not in_box(lat, lon, POLAND_BOX):
                    raise ValueError("Współrzędne poza Polską. Sprawdź kolejność długość, szerokość.")
            elif not (item["street"] and item["house_number"]):
                raise ValueError("Podaj pełny adres lub obie współrzędne.")
            for key in ("location_checked_on", "access_checked_on"):
                value = item[key]
                if value and (date.fromisoformat(value).isoformat() != value or date.fromisoformat(value) > date.today()):
                    raise ValueError("Użyj daty RRRR-MM-DD, bez dat przyszłych.")
            for key in ("placement", "access_instructions", "site_name"):
                item[key] = public_text(item[key])
            if not item["placement"] or not item["site_name"]:
                raise ValueError("Podaj publiczną nazwę i opis miejsca.")
            item.update(longitude=lon if lat else None, latitude=lat if lat else None,
                        public_operator_name=provider.strip(), coordinate_status="located" if lat else "address_only")
            clean.append(item)
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({"row": number, "message": str(exc)})
    return clean, errors


def submit(rows):
    created = datetime.now(timezone.utc).isoformat()
    records = []
    for row in rows:
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True)
        identifier = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        records.append((identifier, created, "pending", canonical))
    with closing(db()) as conn, conn:
        conn.executemany("INSERT OR IGNORE INTO submissions VALUES (?,?,?,?)", records)
    return len(records)


def queue():
    with closing(db()) as conn:
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in conn.execute(
            "SELECT * FROM submissions WHERE status = 'pending' ORDER BY created LIMIT 500")]


def decide(identifier, status):
    if status not in {"approved", "rejected"}:
        raise ValueError("Wybierz decyzję.")
    with closing(db()) as conn, conn:
        return bool(conn.execute("UPDATE submissions SET status=? WHERE id=? AND status='pending'",
                                 (status, identifier)).rowcount)


def published():
    with closing(db()) as conn:
        rows = list(conn.execute("SELECT id, payload FROM submissions WHERE status='approved' ORDER BY created,id"))
    by_device = {}
    for row in rows:
        payload = json.loads(row["payload"])
        device = (payload["public_operator_name"].casefold(), payload["operator_device_id"])
        aed_id = by_device[device]["aed_id"] if device in by_device else "operator:" + row["id"]
        payload.update(aed_id=aed_id, source_ids=["operator"], field_sources={
            key: "operator" for key in INTAKE if key in FIELDS and payload.get(key) not in ("", None, "unknown")
        }, device_type="unknown", access_status="unknown", readiness_status="unknown",
            is_stale=any((date.today() - date.fromisoformat(payload[key])).days > 365
                         for key in ("location_checked_on", "access_checked_on") if payload.get(key)))
        if payload["coordinate_status"] == "located":
            payload["field_sources"].pop("longitude", None)
            payload["field_sources"].pop("latitude", None)
            payload["field_sources"]["coordinates"] = "operator"
        by_device[device] = payload
    return list(by_device.values())


def export_pack():
    rows = published()
    stream = io.StringIO(newline="")
    active = [f for f in FIELDS if any(row.get(f) not in (None, "") for row in rows)] or list(FIELDS)
    writer = csv.writer(stream)
    writer.writerow(active)

    def csv_value(value):
        if isinstance(value, (dict, list, bool)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    for row in rows:
        writer.writerow([csv_value(row.get(field)) for field in active])
    features = [{"type": "Feature", "id": row["aed_id"],
                 "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
                 "properties": {key: row.get(key) if row.get(key) != "" else None
                                for key in FIELDS if key not in ("longitude", "latitude")}}
                for row in rows if row["coordinate_status"] == "located"]
    metadata = {
        "dataset": {"title": "Odblokuj AED – zatwierdzone zgłoszenia operatorów",
                    "description": "Roboczy pakiet zgłoszeń zatwierdzonych w panelu Odblokuj AED.",
                    "category": "HEAL", "keywords": ["AED", "defibrylatory"], "language": "pl",
                    "publisher": None, "reuse_terms": None, "update_frequency": None},
        "resources": [{"filename": "aed.csv", "format": "csv", "language": "pl", "data_date": date.today().isoformat(), "record_count": len(rows)},
                      {"filename": "aed.geojson", "format": "geojson", "language": "pl", "data_date": date.today().isoformat(), "record_count": len(features)}],
        "release": {"generated_at": now(), "schema_version": "1", "status": "editor_review", "fields": list(FIELDS),
                    "source_inventory": {"operator": "Zgłoszenia zatwierdzone przez redaktora rejestru."}},
    }
    payloads = {"aed.csv": stream.getvalue().encode(), "aed.geojson": json.dumps(
        {"type": "FeatureCollection", "features": features}, ensure_ascii=False, allow_nan=False).encode()}
    for resource in metadata["resources"]:
        resource["sha256"] = hashlib.sha256(payloads[resource["filename"]]).hexdigest()
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
        archive.writestr("portal-metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    return out.getvalue()


def xlsx_template():
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Dane_AED"
    sheet.append(INTAKE)
    sheet.freeze_panes = "A2"
    dictionary = book.create_sheet("Slownik_pol")
    dictionary.append(("Pole", "Typ", "Wymaganie", "Opis"))
    descriptions = {
        "operator_device_id": "Stały identyfikator urządzenia organizacji.",
        "site_name": "Publiczna nazwa obiektu.",
        "municipality": "Miejscowość, w której znajduje się AED.",
        "street": "Ulica. Wymagana przy braku współrzędnych.",
        "house_number": "Numer budynku. Wymagany przy braku współrzędnych.",
        "postcode": "Kod pocztowy w formie tekstu.",
        "longitude": "Długość geograficzna WGS84. Podaj razem z latitude.",
        "latitude": "Szerokość geograficzna WGS84. Podaj razem z longitude.",
        "placement": "Publiczny opis położenia szafki.",
        "level": "Kondygnacja, np. parter.",
        "cabinet_lock_status": "Stan zamknięcia według arkusza Wartosci.",
        "access_instructions": "Publiczne wskazówki dostępu bez kodów lub danych osobowych.",
        "access_type": "Rodzaj dostępu według arkusza Wartosci.",
        "opening_hours": "Zgłoszone godziny, np. 24/7 lub Mo-Fr 08:00-18:00.",
        "location_checked_on": "Data sprawdzenia położenia w formacie RRRR-MM-DD.",
        "access_checked_on": "Data sprawdzenia dostępu w formacie RRRR-MM-DD.",
    }
    required = {"operator_device_id", "site_name", "municipality", "placement", "access_type"}
    for index, name in enumerate(INTAKE, 1):
        numeric = name in {"latitude", "longitude"}
        dictionary.append((name, "liczba" if numeric else "tekst",
                           "tak" if name in required else "warunkowo" if name in {
                               "longitude", "latitude", "street", "house_number"} else "nie", descriptions[name]))
        if not numeric:
            from openpyxl.utils import get_column_letter
            sheet.column_dimensions[get_column_letter(index)].number_format = "@"
    values = book.create_sheet("Wartosci")
    values.append(("access_type", "public", "restricted", "unknown"))
    values.append(("cabinet_lock_status", "locked", "unlocked", "unknown", "not_applicable"))
    examples = book.create_sheet("Przyklady")
    examples.append(INTAKE)
    examples.append(("demo-001", "Punkt demonstracyjny", "Warszawa", None, None, None,
                     21.0122, 52.2297, "Przy recepcji", "parter", "unlocked", None, "public", "24/7"))
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()
