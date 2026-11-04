#pragma once
#include <string>
#include <vector>
#include <cstdint>
#define MOUSE_LEFT 1
#define MOUSE_RIGHT 2
#define MOUSE_MIDDLE 4
struct MockMouse {
  int buttons = 0;
  std::vector<std::string> log;
  void begin() {}
  void press(uint8_t b) { buttons |= b; log.push_back("+m" + std::to_string(b)); }
  void release(uint8_t b) { buttons &= ~b; log.push_back("-m" + std::to_string(b)); }
  void move(int, int, int w) { log.push_back("w" + std::to_string(w)); }
};
extern MockMouse Mouse;
