"""Local connector controls, daily sync scheduler, staged contributions, field tagging and dane.gov.pl publication files."""
import base64
from contextlib import closing
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from zipfile import ZipFile, ZIP_DEFLATED

from prepare_data import (
    DATA, FIELDS, PORTAL_METADATA_JSON, PUBLIC_CSV, PUBLIC_GEOJSON, RAW,
    REGISTRY_JSON, SOURCE_METADATA, SOURCES, TERYT_MAP, build, compute_confidence,
    in_box, normalize, POLAND_BOX, public_text, refresh,
    SOURCE_CONFIG, LIVE_SOURCES, BUILD_LOCK, fetch_state, load_custom_sources, public_download, parse_geojson,
)

LOCK = threading.Lock()
SYNC_INTERVAL_HOURS = max(1, int(os.getenv("AED_SYNC_INTERVAL_HOURS", "24")))
SYNC_STATE = DATA / "sync-state.json"
RUN = {
    "state": "idle",
    "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "next_sync_at": (datetime.now(timezone.utc) + timedelta(hours=SYNC_INTERVAL_HOURS)).isoformat(timespec="seconds"),
    "schedule": f"codziennie (co {SYNC_INTERVAL_HOURS}h)",
    "results": {},
}
try:
    _previous_run = json.loads(SYNC_STATE.read_text(encoding="utf-8"))
    RUN.update(_previous_run)
    if RUN["state"] == "running":
        RUN["state"] = "interrupted"
        RUN["next_sync_at"] = datetime.now(timezone.utc).isoformat()
except (OSError, ValueError, TypeError):
    pass


def persist_sync_state():
    temporary = SYNC_STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(RUN, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SYNC_STATE)

INTAKE = (
    "operator_device_id", "site_name", "municipality", "street", "house_number", "postcode",
    "longitude", "latitude", "placement", "level", "cabinet_lock_status", "access_instructions",
    "access_type", "opening_hours", "location_checked_on", "access_checked_on"
)
DAYS = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
TIME = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
END_TIME = rf"(?:{TIME}|24:00)"
HOURS = re.compile(rf"(?:(?:{DAYS}(?:-{DAYS})?)(?:,{DAYS}(?:-{DAYS})?)*\s+)?{TIME}-{END_TIME}(?:,{TIME}-{END_TIME})*")
_SCHEDULER_STARTED = False


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
    return {
        "run": run,
        "items": [
            {
                "id": key,
                "name": name,
                "url": url,
                "format": path.rsplit(".", 1)[-1].upper(),
                "file": path,
                "count": imported.get(key, 0),
                "held_snapshot": (RAW / path).is_file() and imported.get(key, 0) == 0,
                "snapshot": datetime.fromtimestamp((RAW / path).stat().st_mtime, timezone.utc).isoformat()
                if (RAW / path).is_file() else None,
                "last_result": run["results"].get(key),
                "fetch": fetch_state().get(key),
                "enabled": key in LIVE_SOURCES,
                "status": SOURCE_METADATA.get(key, {}).get("status", "awaiting_adapter"),
                **SOURCE_METADATA.get(key, {}),
            }
            for key, (name, url, path) in SOURCES.items()
        ] + approved_sources(),
    }


def operator_source_id(name):
    return "operator_" + hashlib.sha256(name.strip().casefold().encode()).hexdigest()[:12]


def approved_sources():
    records = published()
    grouped = {}
    for row in records:
        key = row["source_ids"][0]
        item = grouped.setdefault(key, {"id": key, "name": row["public_operator_name"], "count": 0,
            "format": "GeoJSON", "url": "/api/export", "status": "approved_operator", "enabled": True,
            "license": "Zgoda operatora przy zgłoszeniu", "cadence": "po zatwierdzeniu"})
        item["count"] += 1
    return list(grouped.values())


def register_source(body):
    name, url = str(body.get("name", "")).strip(), str(body.get("url", "")).strip()
    license_text = str(body.get("license", "")).strip()
    if not 2 <= len(name) <= 150 or not license_text or len(license_text) > 500:
        raise ValueError("Podaj nazwę i warunki ponownego wykorzystania źródła.")
    if str(body.get("format", "geojson")).lower() not in {"geojson", "json"}:
        raise ValueError("Automatyczny adapter wymaga GeoJSON FeatureCollection z polami wzorca. CSV/XLSX prześlij w formularzu zgłoszeń.")
    key = "custom_" + hashlib.sha256(url.encode()).hexdigest()[:12]
    payload = public_download(url)
    observations = parse_geojson(key, payload)
    if not observations or any(not in_box(o.lat, o.lon, POLAND_BOX) for o in observations):
        raise ValueError("Źródło wymaga niepustego GeoJSON z punktami w Polsce i trwałymi ID.")
    item = {"id": key, "name": name, "url": url, "license": license_text,
            "scope": str(body.get("scope", "Polska"))[:150], "format": "geojson"}
    with LOCK:
        if RUN["state"] == "running":
            raise ValueError("Poczekaj na zakończenie synchronizacji.")
        config = json.loads(SOURCE_CONFIG.read_text()) if SOURCE_CONFIG.is_file() else []
        config = [v for v in config if v["id"] != key] + [item]
        temp = SOURCE_CONFIG.with_suffix(".tmp")
        temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(SOURCE_CONFIG)
        with BUILD_LOCK:
            load_custom_sources()
    # Reuse the validated refresh path to record hash and retrieval provenance.
    if not refresh(key):
        raise ValueError("Zapisano konfigurację; pobranie migawki nie powiodło się. Ponów synchronizację.")
    build()
    return item


def start_refresh(selected):
    if selected != "all" and selected not in SOURCES:
        raise ValueError("Nieznane źródło.")
    with LOCK:
        if RUN["state"] == "running":
            return False
        RUN.update(state="running", results={}, finished_at=None, error=None)
        persist_sync_state()

    def worker():
        state = "complete"
        try:
            for key in list(LIVE_SOURCES) if selected == "all" else (selected,):
                ok = refresh(key)
                with LOCK:
                    RUN["results"][key] = "updated" if ok else "kept_snapshot"
            build()
        except (OSError, ValueError, sqlite3.Error, csv.Error, KeyError, IndexError) as exc:
            state = "failed"
            with LOCK:
                RUN["error"] = str(exc)
        finally:
            finished = datetime.now(timezone.utc)
            with LOCK:
                RUN.update(
                    state=state,
                    finished_at=finished.isoformat(timespec="seconds"),
                    next_sync_at=(finished + timedelta(hours=SYNC_INTERVAL_HOURS)).isoformat(timespec="seconds"),
                )
                persist_sync_state()

    threading.Thread(target=worker, daemon=True).start()
    return True


def start_daily_scheduler():
    global _SCHEDULER_STARTED
    with LOCK:
        if _SCHEDULER_STARTED:
            return
        _SCHEDULER_STARTED = True

    def loop():
        while True:
            try:
                with LOCK:
                    due = datetime.fromisoformat(RUN["next_sync_at"])
                if datetime.now(timezone.utc) >= due:
                    start_refresh("all")
            except (ValueError, OSError, KeyError):
                pass
            time.sleep(30)

    threading.Thread(target=loop, daemon=True, name="aed-daily-sync").start()


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
        return [{**row, "operator_device_id": row.get("operator_device_id") or row.get("aed_id")}
                for row in csv.DictReader(io.StringIO(text), delimiter=dialect, strict=True)]
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
            rows.append({
                **props,
                "operator_device_id": props.get("operator_device_id") or props.get("aed_id") or feature.get("id"),
                "longitude": lon,
                "latitude": lat,
            })
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
    user_confidence = body.get("confidence")
    if user_confidence is not None:
        try:
            user_confidence = max(10, min(100, int(user_confidence)))
        except (ValueError, TypeError):
            user_confidence = None
    rows = input_rows(body)
    if not 1 <= len(rows) <= 500:
        raise ValueError("Prześlij od 1 do 500 wierszy.")
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
            row_conf = row.get("confidence") if row.get("confidence") is not None else user_confidence
            if row_conf is not None:
                try:
                    row_conf = max(10, min(100, int(row_conf)))
                except (ValueError, TypeError):
                    row_conf = None
            item.update(
                longitude=lon if lat else None,
                latitude=lat if lat else None,
                public_operator_name=provider.strip(),
                coordinate_status="located" if lat else "address_only",
                user_confidence=row_conf,
                verification_note=public_text(row.get("verification_note") or body.get("verification_note") or ""),
            )
            clean.append(item)
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({"row": number, "message": str(exc)})
    return clean, errors


def submit(rows, auto_approve=False):
    created = datetime.now(timezone.utc).isoformat()
    status = "approved" if auto_approve else "pending"
    records = []
    for row in rows:
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True)
        identifier = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        records.append((identifier, created, status, canonical))
    with closing(db()) as conn, conn:
        conn.executemany("INSERT OR IGNORE INTO submissions VALUES (?,?,?,?)", records)
    return len(records)


def tag_location(body):
    """Tag or verify an AED location directly from the frontend map (online or synced from offline PWA)."""
    site_name = public_text(body.get("site_name") or body.get("name") or "Punkt AED (Oznaczony w terenie)")
    municipality = public_text(body.get("municipality") or "Polska")
    placement = public_text(body.get("placement") or "Oznaczono w aplikacji terenowej PWA")
    lat = float(body.get("latitude") if body.get("latitude") is not None else body.get("lat"))
    lon = float(body.get("longitude") if body.get("longitude") is not None else body.get("lon"))
    if not in_box(lat, lon, POLAND_BOX):
        raise ValueError("Współrzędne znajdują się poza obszarem Polski.")
    access_type = body.get("access_type") or body.get("access") or "unknown"
    if access_type not in {"public", "restricted", "unknown"}:
        access_type = "unknown"
    lock_status = body.get("cabinet_lock_status") or "unknown"
    if lock_status not in {"locked", "unlocked", "unknown", "not_applicable"}:
        lock_status = "unknown"
    conf = body.get("user_confidence", body.get("confidence", 50))
    try:
        conf = max(15, min(100, int(conf)))
    except (ValueError, TypeError):
        conf = 50
    check_dates = {}
    for field in ("location_checked_on", "access_checked_on"):
        value = body.get(field) or ""
        if value:
            parsed = date.fromisoformat(str(value))
            if parsed.isoformat() != value or parsed > date.today():
                raise ValueError("Użyj daty RRRR-MM-DD, bez dat przyszłych.")
        check_dates[field] = value
    device_id = public_text(body.get("operator_device_id") or body.get("aed_id") or f"tag-{round(lat, 5)}-{round(lon, 5)}")
    row = {
        "operator_device_id": device_id,
        "site_name": site_name,
        "municipality": municipality,
        "street": public_text(body.get("street") or ""),
        "house_number": public_text(body.get("house_number") or ""),
        "postcode": public_text(body.get("postcode") or ""),
        "longitude": round(lon, 6),
        "latitude": round(lat, 6),
        "placement": placement,
        "level": public_text(body.get("level") or ""),
        "cabinet_lock_status": lock_status,
        "access_instructions": public_text(body.get("access_instructions") or ""),
        "access_type": access_type,
        "opening_hours": public_text(body.get("opening_hours") or body.get("hours") or ""),
        "location_checked_on": check_dates["location_checked_on"],
        "access_checked_on": check_dates["access_checked_on"],
        "public_operator_name": public_text(body.get("public_operator_name") or body.get("operator") or "Zgłoszenie terenowe PWA · Serce Okolicy"),
        "coordinate_status": "located",
        "user_confidence": conf,
        "verification_note": public_text(body.get("verification_note") or ""),
    }
    submit([row], auto_approve=False)
    pub = [p for p in published() if p.get("operator_device_id") == device_id]
    return pub[-1] if pub else {**row, "status": "pending"}


def queue():
    with closing(db()) as conn:
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in conn.execute("SELECT * FROM submissions WHERE status = 'pending' ORDER BY created LIMIT 500")
        ]


def decide(identifier, status):
    if status not in {"approved", "rejected"}:
        raise ValueError("Wybierz decyzję.")
    with closing(db()) as conn, conn:
        return bool(conn.execute(
            "UPDATE submissions SET status=? WHERE id=? AND status='pending'",
            (status, identifier),
        ).rowcount)


def published():
    with closing(db()) as conn:
        rows = list(conn.execute("SELECT id, payload FROM submissions WHERE status='approved' ORDER BY created,id"))
    by_device = {}
    for row in rows:
        payload = json.loads(row["payload"])
        device = (payload["public_operator_name"].casefold(), payload["operator_device_id"])
        aed_id = by_device[device]["aed_id"] if device in by_device else "operator:" + row["id"][:12]
        source_id = operator_source_id(payload["public_operator_name"])
        field_sources = {
            key: source_id
            for key in INTAKE
            if key in FIELDS and payload.get(key) not in ("", None, "unknown")
        }
        if payload["coordinate_status"] == "located":
            field_sources.pop("longitude", None)
            field_sources.pop("latitude", None)
            field_sources["coordinates"] = source_id

        auto_score, auto_level, reasons = compute_confidence(
            ["operator"],
            placement=payload.get("placement"),
            address=payload.get("street"),
            access=payload.get("access_type"),
            checked_on=payload.get("access_checked_on") or payload.get("location_checked_on"),
            lock_status=payload.get("cabinet_lock_status"),
            hours=payload.get("opening_hours"),
            operator=payload.get("public_operator_name"),
        )
        user_conf = payload.get("user_confidence")
        if isinstance(user_conf, int):
            score = auto_score
        else:
            score = auto_score
        level = "high" if score >= 70 else ("medium" if score >= 45 else "low")
        municipality = payload.get("municipality") or None
        teryt = TERYT_MAP.get(normalize(municipality or "")) if municipality else None

        payload.update(
            aed_id=aed_id,
            locality=municipality,
            teryt=teryt,
            coordinate_accuracy_m=None,
            indoor_outdoor=payload.get("indoor_outdoor") or "unknown",
            device_type="fixed",
            access_status="available" if payload.get("access_type") == "public" else (
                "restricted" if payload.get("access_type") == "restricted" else "unknown"
            ),
            readiness_status="unknown",
            public_operator_contact_url=None,
            readiness_checked_on=None,
            source_ids=[source_id],
            field_sources=field_sources,
            is_stale=any(
                (date.today() - date.fromisoformat(payload[key])).days > 365
                for key in ("location_checked_on", "access_checked_on") if payload.get(key)
            ),
            confidence=score,
            confidence_level=level,
            confidence_reasons=reasons,
        )
        by_device[device] = payload
    return list(by_device.values())


def _build_release_files():
    # Include both the full national canonical dataset and approved operator submissions
    base_items = []
    if REGISTRY_JSON.is_file():
        try:
            reg = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
            base_items = reg.get("items", [])
        except Exception:
            base_items = []
    op_rows = published()
    all_rows = [*op_rows, *base_items]

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

    for row in all_rows:
        writer.writerow([csv_value(row.get(field)) for field in FIELDS])

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
        for row in all_rows
        if row.get("coordinate_status") == "located"
    ]
    csv_bytes = stream.getvalue().encode("utf-8")
    geojson_bytes = json.dumps(
        {"type": "FeatureCollection", "features": features},
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    base_metadata = {}
    try:
        base_metadata = json.loads(PORTAL_METADATA_JSON.read_text())
    except (OSError, ValueError):
        pass
    effective_dates = [base_metadata.get("release", {}).get("data_date")]
    effective_dates.extend(row.get(field) for row in all_rows for field in ("location_checked_on", "access_checked_on", "readiness_checked_on"))
    with closing(db()) as conn:
        latest = conn.execute("SELECT MAX(created) FROM submissions WHERE status='approved'").fetchone()[0]
    if latest:
        effective_dates.append(latest[:10])
    data_date = max((d for d in effective_dates if d and len(d) == 10 and d <= date.today().isoformat()), default=None)
    source_inventory = {
        key: {"name": SOURCES[key][0], "url": SOURCES[key][1], **SOURCE_METADATA.get(key, {})}
        for key in sorted({key for row in base_items for key in row.get("source_ids", [])}) if key in SOURCES
    }
    source_inventory.update({r["source_ids"][0]: {
        "name": r.get("public_operator_name"), "url": "/zglos", "license": "Zgoda operatora na publiczne udostępnienie przy zgłoszeniu; do przeglądu wydawcy",
        "status": "approved_operator", "cadence": "po zatwierdzeniu"} for r in op_rows})
    metadata = {
        "dataset": {
            "title": "Odblokuj AED · Serce Okolicy – Ogólnopolski zbiór danych o defibrylatorach AED",
            "description": "Pakiet roboczy łączący zaimportowane źródła oraz zatwierdzone zgłoszenia operatorów. Liczby i pochodzenie w inwentarzu wydania.",
            "category": "HEAL",
            "keywords": ["AED", "defibrylatory", "ratownictwo", "pierwsza pomoc", "otwarte dane", "dane.gov.pl"],
            "language": "pl",
            "publisher": "Serce Okolicy · Odblokuj AED",
            "reuse_terms": "© OpenStreetMap contributors, ODbL 1.0; pozostałe źródła według inwentarza. Wydawca musi zatwierdzić warunki.",
            "update_frequency": "codziennie",
        },
        "resources": [
            {
                "filename": "aed.csv",
                "format": "csv",
                "media_type": "text/csv; charset=utf-8",
                "language": "pl",
                "data_date": data_date,
                "record_count": len(all_rows),
                "sha256": hashlib.sha256(csv_bytes).hexdigest(),
            },
            {
                "filename": "aed.geojson",
                "format": "geojson",
                "media_type": "application/geo+json",
                "language": "pl",
                "data_date": data_date,
                "record_count": len(features),
                "sha256": hashlib.sha256(geojson_bytes).hexdigest(),
            },
        ],
        "release": {
            "generated_at": now(),
            "schema_version": "1.1",
            "status": "draft_pending_publisher_and_reuse_review",
            "sync_schedule": f"codziennie (automatyczna synchronizacja co {SYNC_INTERVAL_HOURS}h)",
            "fields": list(FIELDS),
            "operator_approved_count": len(op_rows),
            "data_date": data_date,
            "source_inventory": source_inventory,
        },
    }
    canonical_bytes = json.dumps({"schema": "dane.gov.pl/odblokuj-aed/v1", "generated_at": metadata["release"]["generated_at"],
        "data_date": data_date, "total_count": len(all_rows), "sources": [{"id": key, **value} for key, value in source_inventory.items()], "items": all_rows},
        ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"aed.csv": csv_bytes, "aed.geojson": geojson_bytes, "aed.json": canonical_bytes,
            "portal-metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")}


_RELEASE_CACHE_LOCK = threading.Lock()
_RELEASE_CACHE = (None, None)


def public_release_files():
    """One cached approved snapshot shared by individual downloads and ZIP export."""
    global _RELEASE_CACHE
    def identity(path):
        try:
            stat = path.stat()
            return str(path), stat.st_mtime_ns, stat.st_size
        except OSError:
            return str(path), None, None
    with _RELEASE_CACHE_LOCK, BUILD_LOCK:
        key = (identity(REGISTRY_JSON), identity(PORTAL_METADATA_JSON), identity(DATA / "operations.sqlite3"), identity(SOURCE_CONFIG))
        if key != _RELEASE_CACHE[0]:
            files = _build_release_files()
            # Reading an empty operations database can create its tables.
            key = (identity(REGISTRY_JSON), identity(PORTAL_METADATA_JSON), identity(DATA / "operations.sqlite3"), identity(SOURCE_CONFIG))
            _RELEASE_CACHE = (key, files)
        return _RELEASE_CACHE[1]


def export_pack():
    files = public_release_files()
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for filename, payload in files.items():
            archive.writestr(filename, payload)
        archive.writestr("wzorcowy-zakres-aed.xlsx", xlsx_template())
    return out.getvalue()


def xlsx_template():
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Dane_AED"
    sheet.append(INTAKE)
    sheet.freeze_panes = "A2"
    dictionary = book.create_sheet("Slownik_pol")
    dictionary.append(("Pole", "Typ", "Wymaganie", "Zakres", "Opis"))
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
        dictionary.append((
            name,
            "liczba" if numeric else "tekst",
            "tak" if name in required else "warunkowo" if name in {"longitude", "latitude", "street", "house_number"} else "nie",
            "publiczne (dane.gov.pl)",
            descriptions[name],
        ))
        if not numeric:
            from openpyxl.utils import get_column_letter
            sheet.column_dimensions[get_column_letter(index)].number_format = "@"
    values = book.create_sheet("Wartosci")
    values.append(("access_type", "public", "restricted", "unknown"))
    values.append(("cabinet_lock_status", "locked", "unlocked", "unknown", "not_applicable"))
    examples = book.create_sheet("Przyklady")
    examples.append(INTAKE)
    examples.append((
        "BYD-PKP-01", "Bydgoszcz Główna – Dworzec kolejowy", "Bydgoszcz", "Zygmunta Augusta", "7", "85-082",
        18.0009, 53.1338, "Poczekalnia między peronami 3 i 4", "parter", "unlocked",
        "Dostępny całodobowo w holu głównym dworca.", "public", "24/7", "2026-11-21", "2026-11-21"
    ))
    examples.append((
        "WAW-DEMO-02", "Urząd Dzielnicy Mokotów", "Warszawa", "Rakowiecka", "25/27", "02-517",
        21.0149, 52.2086, "Przy wejściu na półpiętrze", "parter", "locked",
        "Poproś o dostęp przy recepcji.", "restricted", "Mo-Fr 08:00-18:00", "2026-11-21", "2026-11-21"
    ))
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()
