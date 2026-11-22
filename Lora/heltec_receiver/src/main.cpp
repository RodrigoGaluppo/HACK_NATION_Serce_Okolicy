#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "radio.h"
#include "records.h"
WiFiUDP udp;
volatile bool received=false;
void IRAM_ATTR onReceive() { received=true; }
void setup() {
  Serial.begin(115200);
  // Optional wired CYD link: Heltec GPIO45 TX -> CYD GPIO35 RX, common GND.
  Serial1.begin(115200,SERIAL_8N1,-1,45);
  WiFi.mode(WIFI_AP); WiFi.softAP(AP_NAME,AP_PASSWORD);
  udp.begin(UDP_PORT);
  startRadio(); radio.setDio1Action(onReceive);
  int state=radio.startReceive();
  if(state) { Serial.printf("RX start: %d\n",state); ESP.restart(); }
}
void loop() {
  if(!received) { delay(1); return; }
  received=false;
  String packet;
  int state=radio.readData(packet);
  Site s;
  if(state==RADIOLIB_ERR_NONE && decode(packet,s)) {
    Serial.println(packet); Serial1.println(packet);
    udp.beginPacket(IPAddress(192,168,4,255),UDP_PORT);
    udp.write((const uint8_t*)packet.c_str(),packet.length()); udp.endPacket();
  }
  state=radio.startReceive();
  if(state) { Serial.printf("RX restart: %d\n",state); delay(1000); ESP.restart(); }
}
