#include <Arduino.h>
#include "radio.h"
#include "bydgoszcz.h"
size_t nextSite=0;
uint32_t lastSend=0;
bool first=true;
void setup() { Serial.begin(115200); startRadio(); }
void loop() {
  if (!first && uint32_t(millis()-lastSend)<SEND_INTERVAL_MS) { delay(10); return; }
  first=false;
  String packet=BYDGOSZCZ[nextSite];
  int state=radio.transmit(packet);
  Serial.printf("TX %u: %d\n", unsigned(nextSite), state);
  lastSend=millis(); // Interval starts after airtime, including failed attempts.
  nextSite=(nextSite+1)%BYDGOSZCZ_COUNT;
}
