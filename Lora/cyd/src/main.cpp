#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <TFT_eSPI.h>
#include "records.h"
// Set true only when GPIO35 is wired to the Heltec receiver TX.
constexpr bool USE_UART = false;
TFT_eSPI tft;
WiFiUDP udp;
SiteList list;
String serialLine;
bool discardLine=false, oldButton=true;
size_t page=0;
uint32_t lastDraw=0,lastConnect=0;
constexpr uint16_t FOREST=0x09C5, PAPER=0xF79C, MINT=0xB7F3;
void draw() {
  tft.fillScreen(PAPER); tft.fillRect(0,0,320,49,FOREST);
  tft.fillCircle(21,17,6,MINT); tft.fillCircle(31,17,6,MINT); tft.fillTriangle(15,18,37,18,26,33,MINT);
  tft.setTextColor(PAPER,FOREST); tft.drawString("SERCE OKOLICY",48,10,4);
  tft.drawString("LoRa / Bydgoszcz",48,33,1);
  tft.setTextColor(FOREST,PAPER);
  tft.drawString("Od punktu demo / nie GPS",10,55,2);
  if(!list.count) { tft.drawString("Czekam na punkty LoRa...",10,95,2); tft.drawString(WiFi.isConnected()?"Most Wi-Fi polaczony":"Laczenie z mostem Wi-Fi...",10,120,2); }
  size_t pages=(list.count+2)/3; if(pages) page%=pages;
  for(size_t i=page*3;i<list.count && i<page*3+3;++i) {
    auto& s=list.sites[i]; int y=79+(i%3)*46;
    tft.fillRoundRect(8,y,304,43,5,TFT_WHITE); tft.setTextColor(FOREST,TFT_WHITE);
    tft.drawString(s.name.substring(0,29),14,y+3,2);
    String sub=String(unsigned(distanceM(s)))+"m  "+(uint32_t(millis()-s.seen)>STALE_MS?"STARE":"NIEZWERYF.");
    tft.drawString(sub,14,y+24,1);
    tft.drawString(s.note.substring(0,22),151,y+24,1);
  }
  tft.setTextColor(FOREST,PAPER);
  tft.drawString("BOOT: dalej  "+String(page+1)+"/"+String(pages?pages:1),10,222,2);
}
void setup() {
  Serial.begin(115200);
  if(USE_UART) Serial2.begin(115200,SERIAL_8N1,35,-1);
  pinMode(0,INPUT_PULLUP);
  tft.init(); tft.setRotation(1);
  WiFi.mode(WIFI_STA); WiFi.begin(AP_NAME,AP_PASSWORD); udp.begin(UDP_PORT); draw();
}
void loop() {
  int n=udp.parsePacket();
  if(n>0) {
    char b[MAX_PACKET+1]; int got=udp.read(b,MAX_PACKET);
    if(n<=int(MAX_PACKET) && got==n) { b[got]=0; list.add(String(b)); }
    while(udp.available()) udp.read();
  }
  while(USE_UART && Serial2.available()) {
    char c=Serial2.read();
    if(c=='\n') { if(!discardLine) list.add(serialLine); serialLine=""; discardLine=false; }
    else if(c!='\r' && !discardLine) { if(serialLine.length()<MAX_PACKET) serialLine+=c; else { discardLine=true; serialLine=""; } }
  }
  bool button=digitalRead(0);
  if(oldButton && !button) { ++page; draw(); delay(30); }
  oldButton=button;
  if(!WiFi.isConnected() && uint32_t(millis()-lastConnect)>15000) { WiFi.disconnect(); WiFi.begin(AP_NAME,AP_PASSWORD); lastConnect=millis(); }
  if(uint32_t(millis()-lastDraw)>1000) { draw(); lastDraw=millis(); }
  delay(5);
}
