"""Evidence and publication regressions; runs offline against the local registry."""
import csv
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import operations
import prepare_data as data


class EvidenceTests(unittest.TestCase):
    def test_missing_access_and_multiple_sources_never_imply_ready(self):
        a = data.Observation('osm', 'node-1', 'AED', 52.2, 21.0, checked_on=date.today().isoformat())
        b = data.Observation('krosno', '2', 'AED', 52.2, 21.0)
        record, _, _ = data.canonical_record(a, [b])
        self.assertEqual(record['access_type'], 'unknown')
        self.assertEqual(record['readiness_status'], 'unknown')
        self.assertIsNone(record['readiness_checked_on'])
        self.assertIsNone(record['access_checked_on'])
        self.assertIsNone(record['coordinate_accuracy_m'])

    def test_geojson_canonical_roundtrip_fields(self):
        payload = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'id': 'device-1',
            'geometry': {'type': 'Point', 'coordinates': [21.0, 52.2]},
            'properties': {'aed_id': 'device-1', 'site_name': 'Library', 'locality': 'Warszawa', 'access_type': 'unknown'}}]}
        observation = data.parse_geojson('custom_test', json.dumps(payload).encode())[0]
        self.assertEqual(observation.name, 'Library')
        self.assertEqual(observation.municipality, 'Warszawa')
        self.assertEqual(observation.ref, 'device-1')

    def test_csv_canonical_id_can_be_used_for_intake(self):
        rows = operations.input_rows({'format': 'csv', 'data': 'aed_id,site_name\r\ndevice-1,Library\r\n'})
        self.assertEqual(rows[0]['operator_device_id'], 'device-1')

    def test_mixed_catalogue_does_not_import_newer_pharmacy_resource(self):
        page = {'data': [
            {'attributes': {'title': 'Wykaz defibrylatorów AED', 'format': 'csv', 'data_date': '2026-09-14', 'download_url': 'https://example.com/aed.csv'}},
            {'attributes': {'title': 'Wykaz aptek', 'format': 'csv', 'data_date': '2026-09-15', 'download_url': 'https://example.com/pharmacies.csv'}}], 'links': {}}
        terms = {'data': {'attributes': {'license_name': 'CC0 1.0'}}}
        with patch.object(data, 'public_download', side_effect=[json.dumps(page).encode(), json.dumps(terms).encode()]):
            resource = data.catalogue_resource('legionowo')
        self.assertEqual(resource['download_url'], 'https://example.com/aed.csv')
        self.assertEqual(resource['_license'], 'CC0 1.0')

    def test_legionowo_keeps_distinct_devices_at_shared_coordinates(self):
        csv_data = ('nazwa,nazwa_ulicy,nr_budynku,nr_lokalu,kod_pocztowy,miejscowosc,szerokosc_geograficzna,dlugosc_geograficzna\n'
            'Police,Jagiellońska,26,,05-120,Legionowo,52.402691,20.927850\n'
            'Municipal guard,Jagiellońska,26,,05-120,Legionowo,52.402691,20.927850\n').encode()
        points = data.parse('legionowo', csv_data)
        self.assertEqual(len({point.id for point in points}), 2)
        groups, review = data.reconcile({'legionowo': points}, [])
        self.assertEqual(len(groups), 2)
        self.assertFalse(review)
        self.assertTrue(all(point.access == '' and point.checked_on == '' for point in points))

    def test_local_sources_cannot_be_downloaded(self):
        for url in ('http://example.com/a', 'https://127.0.0.1/a', 'https://[::1]/a', 'https://169.254.169.254/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                data.public_download(url)

    def test_failed_fetch_preserves_snapshot_and_last_success_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw = directory / 'raw'
            raw.mkdir()
            snapshot = raw / 'osm.geojson'
            snapshot.write_bytes(b'last successful snapshot')
            state = directory / 'fetch.json'
            state.write_text('{"osm": {"sha256": "previous-sha", "retrieved_at": "2024-01-01T00:00:00Z"}}')
            with patch.object(data, 'RAW', raw), patch.object(data, 'FETCH_STATE', state), patch.object(data, 'public_download', side_effect=OSError('network unavailable')):
                self.assertFalse(data.refresh('osm'))
                self.assertEqual(snapshot.read_bytes(), b'last successful snapshot')
                self.assertEqual(data.fetch_state()['osm']['sha256'], 'previous-sha')
                self.assertEqual(data.fetch_state()['osm']['status'], 'failed')

    def test_unchanged_fetch_preserves_snapshot_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw = directory / 'raw'
            raw.mkdir()
            snapshot = raw / 'osm.geojson'
            payload = json.dumps({'type': 'FeatureCollection', 'features': [{'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [21.0, 52.2]},
                'properties': {'emergency': 'defibrillator', '@osm_id': 1}}]}).encode()
            snapshot.write_bytes(payload)
            before = snapshot.stat().st_mtime_ns
            with patch.object(data, 'RAW', raw), patch.object(data, 'FETCH_STATE', directory / 'fetch.json'), patch.object(data, 'public_download', return_value=payload):
                self.assertTrue(data.refresh('osm'))
                self.assertEqual(snapshot.stat().st_mtime_ns, before)

    def test_review_required_and_retry_cannot_revoke_approval(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(operations, 'DATA', Path(temporary)):
            row = operations.tag_location({'lat': 52.2, 'lon': 21.0, 'name': 'Library'})
            self.assertEqual(row['status'], 'pending')
            self.assertEqual(row['location_checked_on'], '')
            self.assertEqual(row['access_checked_on'], '')
            self.assertEqual(row['level'], '')
            self.assertEqual(row['verification_note'], '')
            self.assertEqual(operations.published(), [])
            pending = operations.queue()[0]
            operations.decide(pending['id'], 'approved')
            operations.submit([pending['payload']])
            approved = operations.published()
            self.assertEqual(len(approved), 1)
            self.assertTrue(approved[0]['source_ids'][0].startswith('operator_'))
            self.assertEqual(approved[0]['readiness_status'], 'unknown')
            self.assertEqual(approved[0]['opening_hours'], '')
            self.assertEqual(len(operations.approved_sources()), 1)

    def test_download_cache_is_shared_and_invalidates_after_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            registry = directory / "registry.json"
            registry.write_text('{"items": []}')
            metadata = directory / "metadata.json"
            metadata.write_text('{"release": {"data_date": "2024-01-01"}}')
            with patch.object(operations, 'DATA', directory), patch.object(operations, 'REGISTRY_JSON', registry), patch.object(operations, 'PORTAL_METADATA_JSON', metadata):
                first = operations.public_release_files()
                self.assertIs(first, operations.public_release_files())
                operations.tag_location({'lat': 52.2, 'lon': 21.0, 'name': 'Library'})
                pending = operations.queue()[0]
                before = operations.public_release_files()
                self.assertEqual(json.loads(before['aed.json'])['total_count'], 0)
                operations.decide(pending['id'], 'approved')
                after = operations.public_release_files()
                self.assertEqual(json.loads(after['aed.json'])['total_count'], 1)
                self.assertIs(after, operations.public_release_files())
                inventory = json.loads(after['portal-metadata.json'])['release']['source_inventory']
                self.assertTrue(all(item['license'] for item in inventory.values()))

    @unittest.skipUnless(data.REGISTRY_JSON.is_file(), 'Prepare a local registry first')
    def test_public_export_parity_and_held_sources(self):
        registry = json.loads(data.REGISTRY_JSON.read_text())
        self.assertTrue(all(row['readiness_status'] == 'unknown' for row in registry['items']))
        self.assertFalse(any(source in {'bydgoszcz', 'pkp_transport', 'ratuj_z_sercem'}
            for row in registry['items'] for source in row['source_ids']))
        with tempfile.TemporaryDirectory() as temporary, patch.object(operations, 'DATA', Path(temporary)):
            with ZipFile(io.BytesIO(operations.export_pack())) as archive:
                rows = list(csv.DictReader(io.StringIO(archive.read('aed.csv').decode())))
                features = json.loads(archive.read('aed.geojson'))['features']
                canonical = json.loads(archive.read('aed.json'))['items']
        located = {row['aed_id']: row for row in rows if row['coordinate_status'] == 'located'}
        self.assertEqual(set(located), {feature['id'] for feature in features})
        self.assertEqual({row['aed_id'] for row in rows}, {row['aed_id'] for row in canonical})
        for feature in features:
            row = located[feature['id']]
            self.assertEqual(json.loads(row['source_ids']), feature['properties']['source_ids'])
            self.assertEqual(json.loads(row['field_sources']), feature['properties']['field_sources'])
            self.assertEqual([float(row['longitude']), float(row['latitude'])], feature['geometry']['coordinates'])


if __name__ == '__main__':
    unittest.main()
