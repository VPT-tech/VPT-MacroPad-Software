// Хостові сценарні тести прошивки VPT | Pad.
// Збірка та запуск:  make -C tests/firmware_sim   (або див. Makefile)
#include "../../firmware/VPT_MacroPad/VPT_MacroPad.ino"

#include <algorithm>
#include <iostream>

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

static int g_failed = 0, g_checks = 0;
#define CHECK(cond) do { g_checks++; if (!(cond)) { g_failed++; \
  std::cerr << __FILE__ << ":" << __LINE__ << "  CHECK FAILED: " #cond << std::endl; } } while (0)

static void run_ms(unsigned long ms) {
  for (unsigned long i = 0; i < ms; i++) { sim::now_ms++; loop(); }
}

static void boot(bool keep_flash = false) {
  if (!keep_flash) EEPROM = MockEEPROM();
  for (int i = 0; i < 64; i++) { sim::pin_level[i] = HIGH; sim::isr[i] = nullptr; }
  Serial = MockSerial();
  rp2040 = RP2040();
  Keyboard = MockKeyboard();
  Mouse = MockMouse();
  protoLevel = 1; hostWasOpen = false; rxLen = 0; rxOverflow = false;
  setup();
  run_ms(5);
}

static void cmd(const std::string &c) { Serial.feed(c + "\n"); run_ms(2); }
static void clear_io() { Serial.tx.clear(); Keyboard.log.clear(); Mouse.log.clear(); }

static bool has_line(const std::string &l) {
  auto v = Serial.lines();
  return std::find(v.begin(), v.end(), l) != v.end();
}
static int count_prefix(const std::string &p) {
  int n = 0;
  for (auto &l : Serial.lines()) if (l.rfind(p, 0) == 0) n++;
  return n;
}
static int count_log(const std::vector<std::string> &log, const std::string &e) {
  return (int)std::count(log.begin(), log.end(), e);
}

static void press(int pin, unsigned long hold_ms) {
  sim::pin_level[pin] = LOW; run_ms(hold_ms);
}
static void release(int pin, unsigned long after_ms = 30) {
  sim::pin_level[pin] = HIGH; run_ms(after_ms);
}

// Один клацок EC11. dir=+1 праворуч (стани 3->2->0->1->3), -1 ліворуч (3->1->0->2->3).
static void enc_click(int idx, int dir, bool call_loop = true) {
  const int clk = encCLKPins[idx], dt = encDTPins[idx];
  static const int seqR[4][2] = {{0, 1}, {0, 0}, {1, 0}, {1, 1}}; // {CLK, DT}
  static const int seqL[4][2] = {{1, 0}, {0, 0}, {0, 1}, {1, 1}};
  const int (*seq)[2] = dir > 0 ? seqR : seqL;
  for (int k = 0; k < 4; k++) {
    int nclk = seq[k][0], ndt = seq[k][1];
    if (sim::pin_level[clk] != nclk) { sim::pin_level[clk] = nclk; if (sim::isr[clk]) sim::isr[clk](); }
    if (sim::pin_level[dt] != ndt) { sim::pin_level[dt] = ndt; if (sim::isr[dt]) sim::isr[dt](); }
  }
  if (call_loop) run_ms(1);
}

const int PIN_BTN1 = 20, PIN_BTN2 = 22, PIN_ENC1_SW = 2;

static void test_default_serial_events() {
  boot();
  clear_io();
  press(PIN_BTN1, 40);
  CHECK(has_line("BTN_1_PRESSED"));
  release(PIN_BTN1);
  CHECK(has_line("BTN_1_RELEASED"));
  press(PIN_ENC1_SW, 40); release(PIN_ENC1_SW);
  CHECK(has_line("ENC_1_SW_PRESSED"));
  CHECK(has_line("ENC_1_SW_RELEASED"));
}

// Нова плата (порожній флеш) працює одразу, без програми: вбудований профіль "Медіа"
static void test_works_out_of_the_box() {
  boot();
  Serial.host_open = false;   // програми немає
  run_ms(5);
  clear_io();
  press(PIN_BTN1, 40); release(PIN_BTN1);
  CHECK(count_log(Keyboard.log, "+c182") == 1);          // попередній трек
  press(PIN_BTN2, 40); release(PIN_BTN2);
  CHECK(count_log(Keyboard.log, "+c205") == 1);          // play / pause
  enc_click(2, +1); run_ms(20);
  CHECK(count_log(Keyboard.log, "+c233") == 1);          // ENC_3 — гучність +
  enc_click(0, -1); run_ms(20);
  CHECK(count_log(Mouse.log, "w1") == 1);                // ENC_1 — прокрутка
  CHECK(Keyboard.down.empty() && Keyboard.consumer == 0);
  // Таблиця вбудованого профілю повністю валідна (жодних SERIAL-заглушок)
  for (int b = 0; b < NUM_BTNS; b++)
    for (int sl = 0; sl < 3; sl++) CHECK(hwConfig.buttons[b][sl].type != ACT_SERIAL);
  for (int e = 0; e < NUM_ENC; e++)
    for (int d = 0; d < 2; d++) CHECK(isHidType(hwConfig.encoders[e][d].type));
}

// Програма закрила порт — плата повертається до профілю з флешу (як після перепідключення)
static void test_reverts_to_saved_profile_when_app_closes() {
  boot();
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:0:120");   // профіль "без програми": 'x'
  cmd("SAVE_EEPROM");
  cmd("SET_KEY:BTN_1:TAP:SERIAL");           // активний профіль програми: подію обробляє ПК
  clear_io();
  press(PIN_BTN1, 40); release(PIN_BTN1);
  CHECK(count_log(Keyboard.log, "+120") == 0);
  Serial.host_open = false;                  // програму закрили
  run_ms(3);
  clear_io();
  press(PIN_BTN1, 40); release(PIN_BTN1);
  CHECK(count_log(Keyboard.log, "+120") == 1);
  CHECK(hwConfig.buttons[0][SLOT_TAP].type == ACT_HID_KEY);
  // повернення не стирає флеш
  int commits = EEPROM.commits;
  Serial.host_open = true; run_ms(3); Serial.host_open = false; run_ms(3);
  CHECK(EEPROM.commits == commits);

  // те саме явною командою (програма шле її перед виходом)
  Serial.host_open = true; run_ms(3);
  cmd("SET_KEY:BTN_1:TAP:SERIAL");
  cmd("LOAD_EEPROM");
  CHECK(hwConfig.buttons[0][SLOT_TAP].type == ACT_HID_KEY && hwConfig.buttons[0][SLOT_TAP].param2 == 120);
}

static void test_ping_and_proto() {
  boot();
  clear_io();
  cmd("PING_VPT_MACROPAD");
  CHECK(has_line("PONG_VPT_MACROPAD_V1"));
  cmd("PROTO:2");
  CHECK(has_line(std::string("PROTO_OK:2:FW=") + FW_VERSION));
  CHECK(protoLevel == 2);
  cmd("PROTO:9");
  CHECK(protoLevel == PROTO_MAX);
  // Закриття порту ПК (DTR=0) повертає протокол v1 для сумісності зі старою програмою
  Serial.host_open = false; run_ms(2);
  Serial.host_open = true; run_ms(2);
  CHECK(protoLevel == 1);
}

static void test_fast_path_hid() {
  boot();
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:1:99");   // Ctrl+C
  cmd("SET_KEY:BTN_1:DTAP:NONE");
  cmd("SET_KEY:BTN_1:HOLD:NONE");
  clear_io();
  press(PIN_BTN1, 40);
  CHECK(Keyboard.down.count(KEY_LEFT_CTRL) == 1);
  CHECK(Keyboard.down.count(99) == 1);
  release(PIN_BTN1);
  CHECK(Keyboard.down.empty());
  CHECK(has_line("BTN_1_PRESSED"));   // v1: без суфіксів
}

// Регресія: зміна прив'язки під час утримання кнопки залишала "залиплий" Ctrl.
static void test_no_stuck_key_on_rebind() {
  boot();
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:1:0");    // тільки Ctrl (затиснутий модифікатор)
  cmd("SET_KEY:BTN_1:DTAP:NONE");
  cmd("SET_KEY:BTN_1:HOLD:NONE");
  clear_io();
  press(PIN_BTN1, 40);
  CHECK(Keyboard.down.count(KEY_LEFT_CTRL) == 1);
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:0:120"); // профіль перемкнувся: тепер 'x'
  release(PIN_BTN1);
  CHECK(Keyboard.down.empty());
  CHECK(count_log(Keyboard.log, "+120") == 0); // 'x' не має з'являтись при відпусканні
}

// Регресія: кнопка, натиснута як SERIAL (Shift-шар), після перемикання профілю
// друкувала нову HID-клавішу при відпусканні.
static void test_serial_press_stays_serial() {
  boot();
  cmd("PROTO:2");
  cmd("SET_KEY:BTN_2:TAP:SERIAL");
  clear_io();
  press(PIN_BTN2, 40);
  cmd("SET_KEY:BTN_2:TAP:HID_KEY:0:97");
  cmd("SET_KEY:BTN_2:DTAP:NONE");
  cmd("SET_KEY:BTN_2:HOLD:NONE");
  release(PIN_BTN2, 300);
  CHECK(Keyboard.log.empty());
  CHECK(has_line("BTN_2_PRESSED"));
  CHECK(has_line("BTN_2_RELEASED"));    // без :HW — подію обробляє ПК
  // наступне натискання вже апаратне і позначене :HW
  clear_io();
  press(PIN_BTN2, 40); release(PIN_BTN2);
  CHECK(has_line("BTN_2_PRESSED:HW"));
  CHECK(has_line("BTN_2_FIRED:TAP"));
  CHECK(has_line("BTN_2_RELEASED:HW"));
  CHECK(count_log(Keyboard.log, "+97") == 1);
}

static void test_multitap_and_hold() {
  boot();
  cmd("PROTO:2");
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:0:97");   // a
  cmd("SET_KEY:BTN_1:DTAP:HID_KEY:0:98");  // b
  cmd("SET_KEY:BTN_1:HOLD:HID_KEY:0:99");  // c

  // Одинарний тап: 'a' лише після вікна подвійного тапу
  clear_io();
  press(PIN_BTN1, 60); release(PIN_BTN1, 100);
  CHECK(count_log(Keyboard.log, "+97") == 0);
  run_ms(200);
  CHECK(count_log(Keyboard.log, "+97") == 1);
  CHECK(count_log(Keyboard.log, "-97") == 1);
  CHECK(has_line("BTN_1_FIRED:TAP"));

  // Подвійний тап
  clear_io();
  press(PIN_BTN1, 50); release(PIN_BTN1, 60);
  press(PIN_BTN1, 50); release(PIN_BTN1, 300);
  CHECK(count_log(Keyboard.log, "+98") == 1);
  CHECK(count_log(Keyboard.log, "+97") == 0);
  CHECK(has_line("BTN_1_FIRED:DTAP"));

  // Утримання
  clear_io();
  press(PIN_BTN1, 400);
  CHECK(Keyboard.down.count(99) == 1);
  CHECK(has_line("BTN_1_FIRED:HOLD"));
  release(PIN_BTN1, 300);
  CHECK(Keyboard.down.empty());
  CHECK(count_log(Keyboard.log, "+97") == 0);
}

static void test_encoder_isr_and_tags() {
  boot();
  clear_io();
  enc_click(0, +1);
  enc_click(0, -1);
  CHECK(has_line("ENC_1_RIGHT"));
  CHECK(has_line("ENC_1_LEFT"));

  cmd("PROTO:2");
  cmd("SET_KEY:ENC_1_R:HID_MEDIA:5");
  cmd("SET_KEY:ENC_1_L:SERIAL");
  clear_io();
  enc_click(0, +1);
  enc_click(0, -1);
  CHECK(has_line("ENC_1_RIGHT:HW:A1"));   // зміна напрямку — без прискорення
  CHECK(has_line("ENC_1_LEFT:A1"));
  CHECK(count_log(Keyboard.log, "+c233") == 1);

  // Кроки не губляться, навіть якщо цикл "завис" (ISR накопичує клацання)
  clear_io();
  for (int i = 0; i < 5; i++) enc_click(0, +1, /*call_loop=*/false);
  run_ms(1);
  CHECK(count_prefix("ENC_1_RIGHT") == 5);
  // Кожне клацання — окреме натискання медіа-клавіші (а не одне злите)
  CHECK(count_log(Keyboard.log, "+c233") == 5);
  run_ms(20);
  CHECK(Keyboard.consumer == 0);

  // Колесо миші
  cmd("SET_KEY:ENC_1_L:HID_MOUSE:4");
  clear_io();
  enc_click(0, -1);
  CHECK(count_log(Mouse.log, "w1") == 1);

  // Брязкіт контактів (CLK туди-сюди) не дає хибних кроків
  clear_io();
  const int clk = encCLKPins[0];
  for (int i = 0; i < 6; i++) { sim::pin_level[clk] = !sim::pin_level[clk]; sim::isr[clk](); }
  run_ms(1);
  CHECK(count_prefix("ENC_1_") == 0);
}

static void test_serial_robustness() {
  boot();
  clear_io();
  // Задовгий рядок відкидається повністю і не "протікає" хвостом як команда
  std::string junk(300, 'A');
  Serial.feed(junk + "SET_KEY:BTN_1:TAP:HID_KEY:0:97\nPING_VPT_MACROPAD\n");
  run_ms(5);
  CHECK(has_line("PONG_VPT_MACROPAD_V1"));
  CHECK(hwConfig.buttons[0][SLOT_TAP].type == ACT_HID_MEDIA);   // вбудований профіль не змінився

  // Пошкоджені специфікації -> SERIAL (подія піде на ПК)
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:99:999");
  CHECK(hwConfig.buttons[0][SLOT_TAP].type == ACT_SERIAL);
  cmd("SET_KEY:BTN_1:TAP:HID_MEDIA:42");
  CHECK(hwConfig.buttons[0][SLOT_TAP].type == ACT_SERIAL);
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:2:97");
  CHECK(hwConfig.buttons[0][SLOT_TAP].type == ACT_HID_KEY);
  CHECK(hwConfig.buttons[0][SLOT_TAP].param1 == 2);
  cmd("SET_KEY:ENC_9_L:HID_MEDIA:5");     // неіснуючий енкодер — ігнор
  cmd("SET_KEY:BTN_10:TAP:HID_MEDIA:5");  // неіснуюча кнопка — ігнор
  cmd("  SET_KEY:ENC_3_SW:HOLD:HID_MEDIA:4  \r");
  CHECK(hwConfig.buttons[11][SLOT_HOLD].type == ACT_HID_MEDIA);
}

static void test_eeprom_persistence() {
  boot();
  CHECK(EEPROM.commits == 1);              // перший старт — запис дефолтів
  cmd("SET_KEY:BTN_3:TAP:HID_MEDIA:1");
  cmd("SAVE_EEPROM");
  CHECK(has_line("EEPROM_SAVED"));
  CHECK(EEPROM.commits == 2);
  cmd("SAVE_EEPROM");                      // без змін — флеш не стирається
  CHECK(EEPROM.commits == 2);

  boot(/*keep_flash=*/true);               // перезавантаження плати
  CHECK(hwConfig.buttons[2][SLOT_TAP].type == ACT_HID_MEDIA);
  CHECK(hwConfig.buttons[2][SLOT_TAP].param1 == 1);

  // Пошкоджений вміст EEPROM -> вбудований профіль
  EEPROM.flash[4] = 77;
  boot(true);
  CHECK(hwConfig.buttons[0][SLOT_TAP].type == ACT_HID_MEDIA && hwConfig.buttons[0][SLOT_TAP].param1 == 3);
  CHECK(hwConfig.buttons[2][SLOT_TAP].type == ACT_HID_MEDIA && hwConfig.buttons[2][SLOT_TAP].param1 == 2);
}

static void test_bootloader_releases_keys() {
  boot();
  cmd("SET_KEY:BTN_1:TAP:HID_KEY:1:0");
  cmd("SET_KEY:BTN_1:DTAP:NONE");
  cmd("SET_KEY:BTN_1:HOLD:NONE");
  press(PIN_BTN1, 40);
  CHECK(!Keyboard.down.empty());
  cmd("ENTER_BOOTLOADER");
  CHECK(rp2040.bootloader_calls == 1);
  CHECK(Keyboard.down.empty());
}

static void test_watchdog() {
  boot();
  CHECK(rp2040.wdt_timeout == WDT_TIMEOUT_MS);
  CHECK(WDT_TIMEOUT_MS <= 8000);           // апаратний максимум RP2040 ~8.3 с
  int feeds = rp2040.wdt_feeds;
  run_ms(10);
  CHECK(rp2040.wdt_feeds >= feeds + 10);   // годуємо на кожній ітерації loop()
  clear_io();
  cmd("PROTO:2");
  CHECK(has_line(std::string("PROTO_OK:2:FW=") + FW_VERSION));

  // Плата перезапустилась через watchdog -> ПК дізнається про це під час рукостискання
  EEPROM = MockEEPROM();
  for (int i = 0; i < 64; i++) { sim::pin_level[i] = HIGH; sim::isr[i] = nullptr; }
  Serial = MockSerial();
  rp2040 = RP2040();
  rp2040.reset_reason = RP2040::WDT_RESET;
  protoLevel = 1; hostWasOpen = false; rxLen = 0; rxOverflow = false;
  setup();
  run_ms(5);
  cmd("PROTO:2");
  CHECK(has_line(std::string("PROTO_OK:2:FW=") + FW_VERSION + ":RST=WDT"));
  clear_io();
  cmd("PROTO:2");                          // повторне підключення — вже без повідомлення
  CHECK(has_line(std::string("PROTO_OK:2:FW=") + FW_VERSION));
}

static void test_encoder_accel_measured_on_board() {
  boot();
  cmd("PROTO:2");
  cmd("SET_KEY:ENC_1_L:SERIAL");
  cmd("SET_KEY:ENC_1_R:SERIAL");
  // Пауза gap_ms ПЕРЕД кожним клацанням: інтервал кожного клацання = gap_ms (+1 мс циклу)
  auto rotate = [](int dir, int n, int gap_ms) {
    for (int i = 0; i < n; i++) { run_ms(gap_ms); enc_click(0, dir); }
  };
  rotate(+1, 1, 200);
  clear_io();
  rotate(+1, 3, 10);     // дуже швидко
  CHECK(count_prefix("ENC_1_RIGHT:A5") == 3);
  clear_io();
  rotate(+1, 2, 40);
  CHECK(count_prefix("ENC_1_RIGHT:A3") == 2);
  clear_io();
  rotate(+1, 2, 60);
  CHECK(count_prefix("ENC_1_RIGHT:A2") == 2);
  clear_io();
  rotate(+1, 2, 150);    // повільно
  CHECK(count_prefix("ENC_1_RIGHT:A1") == 2);
  clear_io();
  rotate(-1, 1, 5);      // різка зміна напрямку — не прискорення
  CHECK(has_line("ENC_1_LEFT:A1"));
  // v1 (стара програма) — без жодних суфіксів
  boot();
  clear_io();
  rotate(+1, 2, 10);
  CHECK(count_prefix("ENC_1_RIGHT") == 2 && has_line("ENC_1_RIGHT"));
}

static void test_fast_debounce() {
  boot();
  clear_io();
  // Затримка реакції ~2 мс замість ~21 мс
  sim::pin_level[PIN_BTN1] = LOW;
  run_ms(4);
  CHECK(has_line("BTN_1_PRESSED"));
  release(PIN_BTN1, 40);
  CHECK(has_line("BTN_1_RELEASED"));

  // Брязкіт контактів на натисканні та відпусканні -> рівно одна пара подій
  clear_io();
  const int bounce[] = {LOW, LOW, LOW, HIGH, HIGH, HIGH, LOW, HIGH, LOW, LOW, LOW, LOW};  // відскок 3 мс
  for (int lv : bounce) { sim::pin_level[PIN_BTN1] = lv; run_ms(1); }
  run_ms(50);
  const int bounce_up[] = {HIGH, HIGH, HIGH, LOW, LOW, LOW, HIGH, LOW, HIGH, HIGH, HIGH, HIGH};
  for (int lv : bounce_up) { sim::pin_level[PIN_BTN1] = lv; run_ms(1); }
  run_ms(50);
  CHECK(count_prefix("BTN_1_PRESSED") == 1);
  CHECK(count_prefix("BTN_1_RELEASED") == 1);

  // Коротка завада (1 мс) не є натисканням
  clear_io();
  sim::pin_level[PIN_BTN1] = LOW; run_ms(1);
  sim::pin_level[PIN_BTN1] = HIGH; run_ms(30);
  CHECK(count_prefix("BTN_1_") == 0);

  // Дуже короткий тап (8 мс) не губиться: відпускання фіксується після блокування
  clear_io();
  sim::pin_level[PIN_BTN1] = LOW; run_ms(8);
  sim::pin_level[PIN_BTN1] = HIGH; run_ms(40);
  CHECK(count_prefix("BTN_1_PRESSED") == 1);
  CHECK(count_prefix("BTN_1_RELEASED") == 1);
}

int main() {
  test_default_serial_events();
  test_works_out_of_the_box();
  test_reverts_to_saved_profile_when_app_closes();
  test_ping_and_proto();
  test_fast_path_hid();
  test_no_stuck_key_on_rebind();
  test_serial_press_stays_serial();
  test_multitap_and_hold();
  test_encoder_isr_and_tags();
  test_serial_robustness();
  test_eeprom_persistence();
  test_bootloader_releases_keys();
  test_watchdog();
  test_encoder_accel_measured_on_board();
  test_fast_debounce();
  std::cout << (g_failed ? "FAILED " : "OK ") << (g_checks - g_failed) << "/" << g_checks << " checks passed" << std::endl;
  return g_failed ? 1 : 0;
}
