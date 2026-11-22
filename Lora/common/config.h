#pragma once
// Same settings on both Heltec boards. Raw LoRa, not LoRaWAN/Meshtastic.
constexpr float RADIO_MHZ = 868.1;
constexpr uint32_t SEND_INTERVAL_MS = 60000;
constexpr char AP_NAME[] = "Serce-LoRa";
constexpr char AP_PASSWORD[] = "serce-okolicy";
constexpr uint16_t UDP_PORT = 4210;
// Fixed reference, NOT GPS. Edit together with twatch/config.py.
constexpr double ORIGIN_LAT = 53.1235, ORIGIN_LON = 18.0084;
constexpr uint32_t STALE_MS = 600000;
constexpr size_t MAX_PACKET = 240, MAX_SITES = 32;
