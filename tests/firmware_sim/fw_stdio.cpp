// Прошивка VPT | Pad, що працює як звичайний процес у реальному часі:
//   stdin  — байти "USB Serial" від ПК; рядки, що починаються з '#', — керування симулятором
//            (#press <pin>, #release <pin>, #enc <idx> <+1|-1>, #dtr <0|1>, #quit)
//   stdout — байти "USB Serial" до ПК, а також службові рядки:
//            "@HID <подія>" — HID-звіти (клавіатура/миша), "@RX <рядок>" — прийняті команди.
// Використовується наскрізним тестом tests/test_e2e_hw_sync.py.
#ifndef FW_SOURCE
#define FW_SOURCE "../../firmware/VPT_MacroPad/VPT_MacroPad.ino"
#endif
#include FW_SOURCE

#include <poll.h>
#include <unistd.h>
#include <chrono>
#include <deque>
#include <string>

namespace sim {
unsigned long now_ms = 1000;
int pin_level[64];
voidFuncPtr isr[64];
int irq_disabled = 0;
}
MockSerial Serial;
RP2040 rp2040;
MockUSB USB;
MockKeyboard Keyboard;
MockMouse Mouse;
MockEEPROM EEPROM;

static void set_pin(int pin, int level) {
  if (sim::pin_level[pin] == level) return;
  sim::pin_level[pin] = level;
  if (sim::isr[pin]) sim::isr[pin]();
}

// Переходи енкодера застосовуються по одному на ітерацію loop() (~1 мс), як при
// реальному повільному обертанні — так їх бачить і стара прошивка з опитуванням.
static std::deque<std::pair<int, int>> pending_pins;

static void enc_click(int idx, int dir) {
  static const int seqR[4][2] = {{0, 1}, {0, 0}, {1, 0}, {1, 1}};
  static const int seqL[4][2] = {{1, 0}, {0, 0}, {0, 1}, {1, 1}};
  const int (*seq)[2] = dir > 0 ? seqR : seqL;
  int clk = sim::pin_level[encCLKPins[idx]], dt = sim::pin_level[encDTPins[idx]];
  for (int k = 0; k < 4; k++) {
    if (seq[k][0] != clk) { pending_pins.push_back({encCLKPins[idx], seq[k][0]}); clk = seq[k][0]; }
    if (seq[k][1] != dt) { pending_pins.push_back({encDTPins[idx], seq[k][1]}); dt = seq[k][1]; }
  }
}

static bool handle_control(const std::string &l) {
  int a = 0, b = 0;
  if (sscanf(l.c_str(), "#press %d", &a) == 1) set_pin(a, LOW);
  else if (sscanf(l.c_str(), "#release %d", &a) == 1) set_pin(a, HIGH);
  else if (sscanf(l.c_str(), "#enc %d %d", &a, &b) == 2) enc_click(a, b);
  else if (sscanf(l.c_str(), "#dtr %d", &a) == 1) Serial.host_open = (a != 0);
  else if (l == "#quit") return false;
  return true;
}

int main() {
  for (int i = 0; i < 64; i++) { sim::pin_level[i] = HIGH; sim::isr[i] = nullptr; }
  Serial.host_open = false;
  auto t0 = std::chrono::steady_clock::now();
  setup();

  std::string line;
  size_t kb_printed = 0, mouse_printed = 0;
  bool running = true;
  while (running) {
    struct pollfd pfd = {0, POLLIN, 0};
    if (poll(&pfd, 1, 1) > 0) {
      char buf[4096];
      ssize_t n = read(0, buf, sizeof(buf));
      if (n <= 0) break;  // ПК закрив канал
      for (ssize_t i = 0; i < n; i++) {
        char c = buf[i];
        if (c == '\n') {
          if (!line.empty() && line[0] == '#') {
            running = handle_control(line);
          } else {
            Serial.feed(line + "\n");
            if (!line.empty()) printf("@RX %s\n", line.c_str());
          }
          line.clear();
        } else if (c != '\r') {
          line += c;
        }
      }
    }
    sim::now_ms = 1000 + (unsigned long)std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::steady_clock::now() - t0).count();
    if (!pending_pins.empty()) { set_pin(pending_pins.front().first, pending_pins.front().second); pending_pins.pop_front(); }
    loop();

    if (!Serial.tx.empty()) { fwrite(Serial.tx.data(), 1, Serial.tx.size(), stdout); Serial.tx.clear(); }
    for (; kb_printed < Keyboard.log.size(); kb_printed++) printf("@HID %s\n", Keyboard.log[kb_printed].c_str());
    for (; mouse_printed < Mouse.log.size(); mouse_printed++) printf("@HID %s\n", Mouse.log[mouse_printed].c_str());
    fflush(stdout);
  }
  return 0;
}
