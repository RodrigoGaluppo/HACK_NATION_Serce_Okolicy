import json
import unittest
from unittest.mock import patch
import map_data


class MapPackTests(unittest.TestCase):
    def test_convert_real_osm_shape_without_aed_records(self):
        raw = {'elements': [
            {'type': 'way', 'id': 1, 'tags': {'highway': 'residential', 'name': 'Test'},
             'geometry': [{'lat': 52.2, 'lon': 21.0}, {'lat': 52.201, 'lon': 21.001}]},
            {'type': 'way', 'id': 2, 'tags': {'building': 'yes'}, 'geometry': [
                {'lat': 52.2, 'lon': 21.0}, {'lat': 52.201, 'lon': 21.0},
                {'lat': 52.201, 'lon': 21.001}, {'lat': 52.2, 'lon': 21.0}]},
        ]}
        result = map_data.convert(raw, 52.2, 21.0, 1)
        self.assertEqual(result['type'], 'FeatureCollection')
        self.assertEqual([f['geometry']['type'] for f in result['features']], ['LineString', 'Polygon'])
        self.assertEqual(result['metadata']['radius_km'], 1)
        self.assertFalse(result['metadata']['routing'])
        self.assertIn('ODbL', result['metadata']['attribution'])
        json.dumps(result, allow_nan=False)

    def test_incomplete_overpass_data_is_not_cached_as_complete(self):
        for payload in ({'remark': 'timeout', 'elements': []}, {'elements': []}):
            with self.assertRaises(ValueError):
                map_data.convert(payload, 52.2, 21.0, 1)

    def test_bounded_polish_area_before_network(self):
        for lat, lon, radius in ((52.2, 21, 4), (0, 0, 1), (52.2, 21, -1)):
            with patch.object(map_data, 'urlopen') as fetch, self.assertRaises(ValueError):
                map_data.extract(lat, lon, radius)
            fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
