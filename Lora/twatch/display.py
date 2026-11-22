"""Minimal ST7789 + FT6336 driver for T-Watch 2020 V1 only."""
from machine import Pin, SPI, I2C
import framebuf
import time


def rgb(r, g, b):
    c = ((r & 248) << 8) | ((g & 252) << 3) | (b >> 3)
    return ((c & 255) << 8) | (c >> 8)  # framebuffer little endian -> LCD big endian


class Display:
    def __init__(self):
        power = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
        # AXP202 LDO2 = 3.3V for display. Preserve all unrelated rail bits.
        value = power.readfrom_mem(0x35, 0x28, 1)[0]
        power.writeto_mem(0x35, 0x28, bytes([(value & 15) | 0xF0]))
        value = power.readfrom_mem(0x35, 0x12, 1)[0]
        power.writeto_mem(0x35, 0x12, bytes([value | 4]))
        self.cs, self.dc = Pin(5, Pin.OUT, value=1), Pin(27, Pin.OUT)
        self.spi = SPI(2, baudrate=40000000, polarity=0, phase=0, sck=Pin(18), mosi=Pin(19))
        self.touch = I2C(1, scl=Pin(32), sda=Pin(23), freq=100000)
        self.command(0x01); time.sleep_ms(150)
        self.command(0x11); time.sleep_ms(120)
        self.command(0x3A, b'\x55')
        self.command(0x36, b'\x00')
        self.command(0x21)
        self.command(0x13)
        self.command(0x29); time.sleep_ms(20)
        self.backlight = Pin(12, Pin.OUT, value=1)
        self.buffer = bytearray(240*240*2)
        self.fb = framebuf.FrameBuffer(self.buffer, 240, 240, framebuf.RGB565)

    def command(self, code, data=None):
        self.cs(0); self.dc(0); self.spi.write(bytes([code]))
        if data:
            self.dc(1); self.spi.write(data)
        self.cs(1)

    def show(self):
        self.command(0x2A, b'\x00\x00\x00\xef')
        self.command(0x2B, b'\x00\x00\x00\xef')
        self.command(0x2C, self.buffer)

    def touched(self):
        try:
            return bool(self.touch.readfrom_mem(0x38, 2, 1)[0] & 15)
        except OSError:
            return False
