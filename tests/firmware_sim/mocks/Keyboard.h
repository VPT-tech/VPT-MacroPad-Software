#pragma once
#include <set>
#include <string>
#include <vector>
#include <cstdint>
#define KEY_LEFT_CTRL  0x80
#define KEY_LEFT_SHIFT 0x81
#define KEY_LEFT_ALT   0x82
#define KEY_LEFT_GUI   0x83
struct MockKeyboard {
  std::set<int> down;
  std::vector<std::string> log;
  int consumer = 0;
  void begin() {}
  // Логуються лише фронти — саме їх бачить хост у HID-звітах
  void press(uint8_t k) { if (down.insert(k).second) log.push_back("+" + std::to_string(k)); }
  void release(uint8_t k) { if (down.erase(k)) log.push_back("-" + std::to_string(k)); }
  void releaseAll() { down.clear(); log.push_back("-all"); }
  void consumerPress(uint16_t c) { if (consumer != c) log.push_back("+c" + std::to_string(c)); consumer = c; }
  void consumerRelease() { if (consumer) log.push_back("-c"); consumer = 0; }
};
extern MockKeyboard Keyboard;
