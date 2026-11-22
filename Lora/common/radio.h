#pragma once
#include <RadioLib.h>
#include "config.h"
SX1262 radio = new Module(8, 14, 12, 13);
inline void startRadio() {
  SPI.begin(9, 11, 10, 8);
  // Heltec V3: DIO3 powers the 1.8V TCXO; DIO2 controls the RF switch.
  int state = radio.begin(RADIO_MHZ, 125.0, 7, 5, 0x12, 10, 8, 1.8);
  if (state == RADIOLIB_ERR_NONE) state = radio.setCRC(true);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.printf("Radio init failed: %d\n", state);
    while (true) delay(1000);
  }
}
