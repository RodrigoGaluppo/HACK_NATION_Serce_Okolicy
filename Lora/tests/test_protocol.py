import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'twatch'))
from model import Store, decode, distance

PACKETS = json.loads((ROOT/'data/bydgoszcz.json').read_text())['packets']
def wire(p):
    return json.dumps(p, separators=(',', ':')).encode()
def diff(a, b):
    return ((a-b+2**29) % 2**30)-2**29


class ProtocolTests(unittest.TestCase):
    def test_snapshot_matches_compiled_payloads(self):
        header = (ROOT/'common/bydgoszcz.h').read_text()
        self.assertEqual(len(PACKETS), 8)
        self.assertEqual(len({p['id'] for p in PACKETS}), 8)
        for p in PACKETS:
            self.assertEqual(decode(wire(p)), p)
            self.assertIn(wire(p).decode(), header)
            self.assertLessEqual(len(wire(p)), 240)

    def test_reject_bad_packets(self):
        for raw in (b'', b'{}', b'null', b'[]', b'{'*241, b'{"v":1'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): decode(raw)
        for key, values in {'v':[True,2,'1'], 'lat':[True,0,float('nan'),float('inf'),'53.1'],
                            'lon':[None,90], 'id':['','a'*33,'line\nbreak'],
                            'n':['\u0142',[]], 'p':[''], 'a':['available']}.items():
            for value in values:
                p = dict(PACKETS[0]); p[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError): decode(wire(p))

    def test_dedup_distance_and_refresh(self):
        s = Store((PACKETS[0]['lat'], PACKETS[0]['lon']))
        for p in reversed(PACKETS): s.add(wire(p), 100, diff)
        self.assertEqual(s.nearest()[0]['id'], PACKETS[0]['id'])
        s.add(wire(PACKETS[0]), 200, diff)
        self.assertEqual(len(s.items), 8)
        self.assertEqual(s.nearest()[0]['seen'], 200)
        self.assertAlmostEqual(distance(PACKETS[0], s.origin), 0)
        ds = [distance(p, s.origin) for p in s.nearest()]
        self.assertEqual(ds, sorted(ds))
        self.assertTrue(all(math.isfinite(d) for d in ds))

    def test_capacity_eviction_across_clock_wrap(self):
        s = Store((53.1235,18.0084), 2)
        s.add(wire(PACKETS[0]), 2**30-100, diff)
        s.add(wire(PACKETS[1]), 20, diff)
        s.add(wire(PACKETS[2]), 40, diff)
        self.assertEqual(len(s.items), 2)
        self.assertNotIn(PACKETS[0]['id'], s.items)

if __name__ == '__main__': unittest.main()
