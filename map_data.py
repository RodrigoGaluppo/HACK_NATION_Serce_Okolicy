"""Small, user-requested OSM vector extracts for local rendering, never tile prefetching."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from prepare_data import DATA, POLAND_BOX, in_box

LOCK = threading.Lock()
LAST_FETCH = 0.0
MAX_BYTES = 12 * 1024 * 1024


def convert(payload, lat, lon, radius):
    if payload.get('remark'):
        raise ValueError('Serwer map nie ukończył zapytania. Spróbuj ponownie później.')
    features = []
    for element in payload.get('elements', []):
        if element.get('type') != 'way':
            continue
        tags = element.get('tags', {})
        coords = [[point['lon'], point['lat']] for point in element.get('geometry', [])
                  if isinstance(point, dict) and isinstance(point.get('lat'), (int, float)) and isinstance(point.get('lon'), (int, float))
                  and math.isfinite(point['lat']) and math.isfinite(point['lon'])]
        if len(coords) < 2:
            continue
        polygon = len(coords) >= 4 and coords[0] == coords[-1] and (tags.get('building') or tags.get('natural') == 'water' or tags.get('water'))
        features.append({'type': 'Feature', 'id': 'way/' + str(element['id']),
            'geometry': {'type': 'Polygon' if polygon else 'LineString', 'coordinates': [coords] if polygon else coords},
            'properties': {key: tags[key] for key in ('name', 'highway', 'building', 'waterway', 'water', 'natural') if key in tags}})
    if not features:
        raise ValueError('Brak elementów mapy w odpowiedzi. Poprzednia mapa pozostaje dostępna.')
    if len(features) > 30000:
        raise ValueError('Mapa jest za duża. Wybierz mniejszy promień.')
    return {'type': 'FeatureCollection', 'metadata': {'center': {'lat': lat, 'lon': lon}, 'radius_km': radius,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'source': 'OpenStreetMap / Overpass API',
        'attribution': '© OpenStreetMap contributors · ODbL 1.0', 'license': 'https://www.openstreetmap.org/copyright',
        'purpose': 'offline_basemap', 'routing': False}, 'features': features}


def extract(lat, lon, radius):
    global LAST_FETCH
    if not in_box(lat, lon, POLAND_BOX) or not 0.5 <= radius <= 3:
        raise ValueError('Wybierz środek w Polsce i promień mapy 0,5–3 km.')
    # Reuse a small area between nearby requests and keep disk use bounded.
    lat, lon = round(lat, 3), round(lon, 3)
    radius = round(radius, 1)
    key = hashlib.sha256(f'{lat},{lon},{radius}'.encode()).hexdigest()[:20]
    folder = DATA / 'maps'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (key + '.geojson')
    if target.is_file() and time.time() - target.stat().st_mtime < 30 * 86400:
        return target.read_bytes()
    if not LOCK.acquire(blocking=False):
        raise ValueError('Trwa pobieranie innego obszaru mapy. Spróbuj za chwilę.')
    try:
        if time.monotonic() - LAST_FETCH < 15:
            raise ValueError('Odczekaj 15 sekund między pobraniami nowych obszarów mapy.')
        LAST_FETCH = time.monotonic()
        lat_delta, lon_delta = radius / 110, radius / (110 * math.cos(math.radians(lat)))
        box = f'{lat-lat_delta:.6f},{lon-lon_delta:.6f},{lat+lat_delta:.6f},{lon+lon_delta:.6f}'
        query = f'[out:json][timeout:25][maxsize:32000000];(way[highway]({box});way[building]({box});way[waterway]({box});way[natural=water]({box}););out geom({box});'
        request = Request('https://overpass-api.de/api/interpreter', data=urlencode({'data': query}).encode(),
            headers={'User-Agent': 'SerceOkolicy-AED/1.0 (small user-requested offline extracts)', 'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with urlopen(request, timeout=35) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('Obszar mapy przekracza 12 MB. Wybierz mniejszy promień.')
            result = json.dumps(convert(json.loads(raw), lat, lon, radius), ensure_ascii=False, allow_nan=False).encode()
        except (OSError, ValueError) as exc:
            if target.is_file():
                return target.read_bytes()
            raise ValueError('Nie udało się pobrać mapy ulic. Spróbuj później; zapisane punkty i mapa uproszczona nadal działają.') from exc
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(result)
        temporary.replace(target)
        files = sorted(folder.glob('*.geojson'), key=lambda p: p.stat().st_mtime, reverse=True)
        for older in files[24:]:
            older.unlink(missing_ok=True)
        return result
    finally:
        LOCK.release()
