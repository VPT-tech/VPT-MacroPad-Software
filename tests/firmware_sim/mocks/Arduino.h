// Мінімальний мок Arduino API для хостових тестів прошивки VPT | Pad.
#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include <deque>

#define HIGH 1
#define LOW 0
#define INPUT_PULLUP 2
#define CHANGE 3
typedef uint8_t pin_size_t;
typedef void (*voidFuncPtr)(void);

namespace sim {
extern unsigned long now_ms;
extern int pin_level[64];
extern voidFuncPtr isr[64];
extern int irq_disabled;
}

inline unsigned long millis() { return sim::now_ms; }
inline void delay(unsigned long ms) { sim::now_ms += ms; }
inline void pinMode(int, int) {}
inline int digitalRead(int pin) { return sim::pin_level[pin]; }
inline int digitalPinToInterrupt(int pin) { return pin; }
inline void attachInterrupt(int pin, voidFuncPtr cb, int) { sim::isr[pin] = cb; }
inline void noInterrupts() { sim::irq_disabled++; }
inline void interrupts() { sim::irq_disabled--; }

// Мінімальний Arduino String — потрібен лише для збірки старої прошивки v1.0 (legacy-фікстура)
class String {
public:
  std::string s;
  String() {}
  String(const char *c) : s(c ? c : "") {}
  String(const std::string &x) : s(x) {}
  String(int v) : s(std::to_string(v)) {}
  void reserve(unsigned) {}
  unsigned length() const { return (unsigned)s.size(); }
  bool startsWith(const char *p) const { return s.rfind(p, 0) == 0; }
  bool endsWith(const char *p) const { size_t n = strlen(p); return s.size() >= n && s.compare(s.size() - n, n, p) == 0; }
  String substring(unsigned a) const { return a >= s.size() ? String() : String(s.substr(a)); }
  String substring(unsigned a, unsigned b) const { return a >= s.size() || b <= a ? String() : String(s.substr(a, b - a)); }
  int indexOf(char c, unsigned from = 0) const { size_t p = s.find(c, from); return p == std::string::npos ? -1 : (int)p; }
  long toInt() const { return atol(s.c_str()); }
  void trim() { size_t a = s.find_first_not_of(" \t\r\n"); size_t b = s.find_last_not_of(" \t\r\n"); s = (a == std::string::npos) ? "" : s.substr(a, b - a + 1); }
  bool operator==(const char *c) const { return s == c; }
  String &operator+=(char c) { s += c; return *this; }
  String operator+(const char *c) const { return String(s + c); }
  String operator+(const String &o) const { return String(s + o.s); }
  friend String operator+(const char *c, const String &o) { return String(std::string(c) + o.s); }
  const char *c_str() const { return s.c_str(); }
};

class MockSerial {
public:
  bool host_open = true;
  std::deque<char> rx;
  std::string tx;
  void begin(unsigned long) {}
  explicit operator bool() const { return host_open; }
  int available() { return (int)rx.size(); }
  int read() { if (rx.empty()) return -1; char c = rx.front(); rx.pop_front(); return (uint8_t)c; }
  int availableForWrite() { return 256; }
  size_t write(const uint8_t *b, size_t n) { tx.append((const char *)b, n); return n; }
  size_t println(const char *s) { tx += s; tx += "\r\n"; return strlen(s) + 2; }
  size_t println(const String &s) { return println(s.c_str()); }
  void flush() {}
  void feed(const std::string &s) { for (char c : s) rx.push_back(c); }
  std::vector<std::string> lines() {
    std::vector<std::string> out; std::string cur;
    for (char c : tx) { if (c == '\n') { out.push_back(cur); cur.clear(); } else if (c != '\r') cur += c; }
    return out;
  }
};
extern MockSerial Serial;

struct RP2040 {
  enum resetReason_t {UNKNOWN_RESET, PWRON_RESET, RUN_PIN_RESET, SOFT_RESET, WDT_RESET, DEBUG_RESET, GLITCH_RESET, BROWNOUT_RESET};
  int bootloader_calls = 0;
  uint32_t wdt_timeout = 0;
  int wdt_feeds = 0;
  resetReason_t reset_reason = PWRON_RESET;
  void rebootToBootloader() { bootloader_calls++; }
  void wdt_begin(uint32_t ms) { wdt_timeout = ms; }
  void wdt_reset() { wdt_feeds++; }
  resetReason_t getResetReason() { return reset_reason; }
};
extern RP2040 rp2040;
