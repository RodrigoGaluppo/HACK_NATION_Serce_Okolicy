import network
import socket
import time
from display import Display, rgb
from model import Store, distance
import config

screen = Display()
f = screen.fb
forest, paper, mint = rgb(11,57,40), rgb(246,242,229), rgb(182,255,158)
white = rgb(255,255,255)
store = Store(config.ORIGIN, config.MAX_SITES)
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', config.UDP_PORT))
sock.setblocking(False)
page, last_draw, last_connect, held = 0, None, None, False


def draw(now):
    global page
    f.fill(paper); f.fill_rect(0, 0, 240, 46, forest)
    # A tiny pixel heart, matching the app's mint accent.
    for y, row in enumerate(('01100110','11111111','11111111','01111110','00111100','00011000')):
        for x, bit in enumerate(row):
            if bit == '1': f.fill_rect(10+x*3, 12+y*3, 3, 3, mint)
    f.text('SERCE OKOLICY', 45, 12, paper)
    f.text('LoRa / Bydgoszcz', 45, 28, mint)
    f.text('Punkt demo / nie GPS', 10, 55, forest)
    rows = store.nearest()
    pages = max(1, (len(rows)+2)//3)
    page %= pages
    if not rows:
        f.text('Czekam na punkty...', 12, 94, forest)
        f.text('Most Wi-Fi: '+('OK' if wifi.isconnected() else 'laczenie'), 12, 114, forest)
    for i, p in enumerate(rows[page*3:page*3+3]):
        y = 74+i*47
        f.fill_rect(8, y, 224, 43, white)
        f.text(p['n'][:26], 14, y+4, forest)
        f.text(p['p'][:26], 14, y+16, forest)
        age = time.ticks_diff(now, p['seen'])
        status = 'STARE' if age > config.STALE_MS else 'NIEZWERYF.'
        f.text('%dm / %s' % (distance(p, config.ORIGIN), status), 14, y+29, forest)
    f.text('Dotknij: dalej %d/%d' % (page+1, pages), 12, 225, forest)
    screen.show()


while True:
    now = time.ticks_ms()
    if not wifi.isconnected() and (last_connect is None or time.ticks_diff(now, last_connect)>15000):
        wifi.disconnect()
        try:
            wifi.connect(config.SSID, config.PASSWORD)
        except OSError:
            pass
        last_connect = now
    try:
        wire, address = sock.recvfrom(241)
        store.add(wire, now, time.ticks_diff)
    except (OSError, ValueError, TypeError):
        pass
    touching = screen.touched()
    if touching and not held:
        page += 1
        last_draw = None
    held = touching
    if last_draw is None or time.ticks_diff(now, last_draw)>1000:
        draw(now)
        last_draw = now
    time.sleep_ms(30)
