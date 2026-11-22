"""Shared packet contract; works on MicroPython and CPython."""
import json
import math


def decode(wire):
    if len(wire) > 240:
        raise ValueError('Oversize packet')
    p = json.loads(wire)
    if not isinstance(p, dict) or type(p.get('v')) is not int or p['v'] != 1:
        raise ValueError('Protocol version')
    for key, limit in (('id', 32), ('n', 40), ('p', 60)):
        s = p.get(key)
        if not isinstance(s, str) or not 0 < len(s) <= limit or any(ord(c) < 32 or ord(c) > 126 for c in s):
            raise ValueError('Invalid text')
    for key, low, high in (('lat', 53.0, 53.3), ('lon', 17.8, 18.3)):
        n = p.get(key)
        if type(n) not in (int, float) or not low <= n <= high:
            raise ValueError('Outside Bydgoszcz')
    if p.get('a') != 'unverified':
        raise ValueError('Unsupported access claim')
    return p


def distance(p, origin):
    rad = math.pi / 180
    a = math.sin((p['lat']-origin[0])*rad/2)**2
    a += math.cos(origin[0]*rad)*math.cos(p['lat']*rad)*math.sin((p['lon']-origin[1])*rad/2)**2
    return 12742000 * math.asin(math.sqrt(min(1, a)))


class Store:
    def __init__(self, origin, limit=32):
        self.origin, self.limit, self.items = origin, limit, {}

    def add(self, wire, now, ticks_diff):
        p = decode(wire)
        if p['id'] not in self.items and len(self.items) >= self.limit:
            oldest = max(self.items, key=lambda k: ticks_diff(now, self.items[k]['seen']))
            del self.items[oldest]
        p['seen'] = now
        self.items[p['id']] = p

    def nearest(self):
        return sorted(self.items.values(), key=lambda p: distance(p, self.origin))
