#pragma once
#include <cstring>
#include <cstdint>
struct MockEEPROM {
  uint8_t flash[512];
  uint8_t ram[512];
  int commits = 0;
  bool dirty = false;
  MockEEPROM() { memset(flash, 0xFF, sizeof(flash)); memset(ram, 0xFF, sizeof(ram)); }
  void begin(int) { memcpy(ram, flash, sizeof(ram)); dirty = false; }
  template <typename T> T &get(int a, T &t) { memcpy(&t, ram + a, sizeof(T)); return t; }
  template <typename T> const T &put(int a, const T &t) {
    if (memcmp(ram + a, &t, sizeof(T)) != 0) { memcpy(ram + a, &t, sizeof(T)); dirty = true; }
    return t;
  }
  bool commit() { if (!dirty) return true; memcpy(flash, ram, sizeof(flash)); commits++; dirty = false; return true; }
};
extern MockEEPROM EEPROM;
