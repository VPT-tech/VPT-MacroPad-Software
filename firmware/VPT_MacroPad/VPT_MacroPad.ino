// VPT | Pad — прошивка RP2040 (Arduino-Pico core)
//
// Протокол Serial (115200, рядки, завершені '\n'):
//   ПК -> плата:
//     PING_VPT_MACROPAD                -> PONG_VPT_MACROPAD_V1
//     PROTO:<n>                        -> PROTO_OK:<n>:FW=<версія>   (n = 1..PROTO_MAX)
//     SET_KEY:BTN_x:[TAP|DTAP|HOLD]:<spec>
//     SET_KEY:ENC_x_SW:[TAP|DTAP|HOLD]:<spec>
//     SET_KEY:ENC_x_L:<spec> / SET_KEY:ENC_x_R:<spec>
//     SAVE_EEPROM                      -> EEPROM_SAVED
//     RESET_HW, ENTER_BOOTLOADER
//     <spec> = NONE | SERIAL | HID_KEY:<mods>:<key> | HID_MOUSE:<n> | HID_MEDIA:<n>
//   плата -> ПК:
//     BTN_x_PRESSED / BTN_x_RELEASED / ENC_x_SW_PRESSED / ...
//     ENC_x_LEFT / ENC_x_RIGHT
//   Протокол v2 (вмикається командою PROTO:2, скидається при закритті порту):
//     до подій додається суфікс ":HW", якщо подію вже виконано апаратно (HID),
//     а при апаратному спрацюванні слоту надсилається BTN_x_FIRED:TAP|DTAP|HOLD.
//     Це дозволяє ПК ніколи не дублювати й не пропускати дію під час ресинхронізації.

#include <Arduino.h>
#ifdef USB
#undef USB
#endif
#include <USB.h>
#include <Keyboard.h>
#include <KeyboardLayout.h>
#include <Mouse.h>
#include <EEPROM.h>
#include <string.h>
#include <stdlib.h>

#define FW_VERSION "1.1.0"
const uint8_t PROTO_MAX = 2;

const int NUM_BTNS = 12;  // 0..8 = BTN_1..9, 9..11 = ENC_1_SW..ENC_3_SW
const int NUM_ENC  = 3;

// Піни 9 основних кнопок (BTN_1 .. BTN_9)
const int buttonPins[9] = {20, 22, 12, 19, 27, 13, 18, 17, 14};

// Піни 3 енкодерів EC11 та їхніх кнопок (ENC_1 .. ENC_3)
const int encCLKPins[NUM_ENC] = {4, 8, 11};
const int encDTPins[NUM_ENC]  = {26, 7, 10};
const int encSWPins[NUM_ENC]  = {2, 6, 9};

// Таблиця переходів квадратурного енкодера EC11 (код Грея)
const int8_t ENC_TABLE[16] = {
   0,  1, -1,  0,
  -1,  0,  0,  1,
   1,  0,  0, -1,
   0, -1,  1,  0
};

const unsigned long DEBOUNCE_DELAY = 20;
const unsigned long HOLD_TIME_MS   = 300;
const unsigned long DTAP_WINDOW_MS = 220;
const unsigned long TAP_RELEASE_MS = 8;
const int MAX_ENC_STEPS_PER_LOOP   = 16;

// Типи дій у пам'яті EEPROM
enum ActionType : uint8_t {
  ACT_SERIAL    = 0, // Відправляти подію тільки в Python-програму
  ACT_NONE      = 1, // Не призначено
  ACT_HID_KEY   = 2, // Клавіша + модифікатори (param1 = mod mask, param2 = keycode)
  ACT_HID_MOUSE = 3, // Клік/колесо миші (param1 = button/wheel code)
  ACT_HID_MEDIA = 4  // Медіа-клавіша (param1 = код медіа-дії)
};

enum SlotIdx : uint8_t { SLOT_TAP = 0, SLOT_DTAP = 1, SLOT_HOLD = 2 };
const char *const SLOT_NAMES[3] = {"TAP", "DTAP", "HOLD"};

struct HidBinding {
  uint8_t type;
  uint8_t param1;
  uint8_t param2;
  uint8_t reserved;
};

struct EEPROMConfig {
  uint32_t magic;
  // 12 кнопок, 3 слоти (0=TAP, 1=DTAP, 2=HOLD)
  HidBinding buttons[NUM_BTNS][3];
  // 3 енкодери, 2 напрямки (0=LEFT, 1=RIGHT)
  HidBinding encoders[NUM_ENC][2];
};

const uint32_t EEPROM_MAGIC = 0x56505433; // "VPT3" — формат не змінено, сумісно зі старими платами
EEPROMConfig hwConfig;

// Ядро arduino-pico за замовчуванням опитує HID раз на 10 мс, а кожен звіт чекає,
// поки хост забере попередній. Комбінація Ctrl+Shift+X (6 звітів) блокувала цикл
// на ~60 мс. 1 мс — стандарт для клавіатур/мишей Full-Speed USB.
int usb_hid_poll_interval = 1;

static inline bool isHidType(uint8_t t) {
  return t == ACT_HID_KEY || t == ACT_HID_MOUSE || t == ACT_HID_MEDIA;
}

static inline bool sameBinding(const HidBinding &a, const HidBinding &b) {
  return a.type == b.type && a.param1 == b.param1 && a.param2 == b.param2;
}

// ---------------- Стан кнопок ----------------
bool lastReadings[NUM_BTNS];
bool btnStates[NUM_BTNS];
unsigned long lastDebounceTimes[NUM_BTNS];

// Машина станів Multi-Tap
unsigned long pressStartTime[NUM_BTNS];
unsigned long lastReleaseTime[NUM_BTNS];
uint8_t tapCount[NUM_BTNS];
bool holdTriggered[NUM_BTNS];
bool fastPathActive[NUM_BTNS];

// Знімок налаштувань кнопки на момент натискання.
// Без нього зміна прив'язок (перемикання профілю) під час утримання призводила
// до "залиплих" клавіш: відпускалась вже НОВА клавіша, а стара лишалась натиснутою.
struct PressContext {
  bool serialMode;          // true — кнопку повністю обробляє ПК
  HidBinding slots[3];
};
PressContext pressCtx[NUM_BTNS];

// ---------------- Енкодери (обробка в перериваннях) ----------------
volatile uint8_t encIsrState[NUM_ENC];
volatile int8_t  encIsrDelta[NUM_ENC];
volatile int16_t encSteps[NUM_ENC];   // накопичені клацання: + праворуч, - ліворуч

static inline uint8_t readEncPins(int idx) {
  return (digitalRead(encCLKPins[idx]) ? 1 : 0) | (digitalRead(encDTPins[idx]) ? 2 : 0);
}

static void encoderIsr(int idx) {
  uint8_t s = readEncPins(idx);
  uint8_t prev = encIsrState[idx];
  if (s == prev) return;
  int8_t d = encIsrDelta[idx] + ENC_TABLE[(prev << 2) | s];
  encIsrState[idx] = s;
  if (s == 3) { // фіксоване положення (detent)
    if (d >= 2) encSteps[idx]++;
    else if (d <= -2) encSteps[idx]--;
    d = 0;
  }
  encIsrDelta[idx] = d;
}

void isrEnc0() { encoderIsr(0); }
void isrEnc1() { encoderIsr(1); }
void isrEnc2() { encoderIsr(2); }
void (*const ENC_ISRS[NUM_ENC])() = {isrEnc0, isrEnc1, isrEnc2};

// ---------------- Неблокуюча черга відпускання ----------------
struct PendingTapRelease {
  bool active;
  HidBinding binding;
  unsigned long releaseAt;
};
const int PENDING_SLOTS = 8;
PendingTapRelease pendingReleases[PENDING_SLOTS];

// ---------------- Serial ----------------
char rxBuf[160];
size_t rxLen = 0;
bool rxOverflow = false;
uint8_t protoLevel = 1;
bool hostWasOpen = false;

uint16_t getMediaUsageCode(uint8_t mediaId) {
  switch (mediaId) {
    case 1: return 0x00CD; // Play / Pause
    case 2: return 0x00B5; // Next Track
    case 3: return 0x00B6; // Previous Track
    case 4: return 0x00E2; // Mute
    case 5: return 0x00E9; // Volume Up
    case 6: return 0x00EA; // Volume Down
    default: return 0;
  }
}

void resetDefaultConfig() {
  memset(&hwConfig, 0, sizeof(hwConfig));
  hwConfig.magic = EEPROM_MAGIC;
  for (int b = 0; b < NUM_BTNS; b++) {
    hwConfig.buttons[b][SLOT_TAP]  = {ACT_SERIAL, 0, 0, 0};
    hwConfig.buttons[b][SLOT_DTAP] = {ACT_NONE, 0, 0, 0};
    hwConfig.buttons[b][SLOT_HOLD] = {ACT_NONE, 0, 0, 0};
  }
  for (int e = 0; e < NUM_ENC; e++) {
    hwConfig.encoders[e][0] = {ACT_SERIAL, 0, 0, 0};
    hwConfig.encoders[e][1] = {ACT_SERIAL, 0, 0, 0};
  }
}

static bool isValidBinding(const HidBinding &b) {
  return b.type <= ACT_HID_MEDIA;
}

void loadEEPROMConfig() {
  EEPROM.get(0, hwConfig);
  bool valid = (hwConfig.magic == EEPROM_MAGIC);
  for (int b = 0; valid && b < NUM_BTNS; b++)
    for (int s = 0; valid && s < 3; s++) valid = isValidBinding(hwConfig.buttons[b][s]);
  for (int e = 0; valid && e < NUM_ENC; e++)
    for (int d = 0; valid && d < 2; d++) valid = isValidBinding(hwConfig.encoders[e][d]);

  if (!valid) {
    resetDefaultConfig();
    EEPROM.put(0, hwConfig);
    EEPROM.commit();
  }
}

// EEPROM.put() у arduino-pico сам порівнює дані (memcmp) і commit() не стирає флеш,
// якщо нічого не змінилось, тож повторні SAVE_EEPROM безпечні для ресурсу флешу.
void saveEEPROMConfig() {
  hwConfig.magic = EEPROM_MAGIC;
  EEPROM.put(0, hwConfig);
  EEPROM.commit();
}

const char *getBtnName(int idx) {
  static const char *const NAMES[NUM_BTNS] = {
    "BTN_1", "BTN_2", "BTN_3", "BTN_4", "BTN_5", "BTN_6", "BTN_7", "BTN_8", "BTN_9",
    "ENC_1_SW", "ENC_2_SW", "ENC_3_SW"
  };
  return (idx >= 0 && idx < NUM_BTNS) ? NAMES[idx] : "BTN_?";
}

int parseBtnIndex(const char *name) {
  for (int i = 0; i < NUM_BTNS; i++) {
    if (strcmp(name, getBtnName(i)) == 0) return i;
  }
  return -1;
}

// ---------------- HID ----------------
void pressHid(const HidBinding &b) {
  if (b.type == ACT_HID_KEY) {
    if (b.param1 & 1) Keyboard.press(KEY_LEFT_CTRL);
    if (b.param1 & 2) Keyboard.press(KEY_LEFT_SHIFT);
    if (b.param1 & 4) Keyboard.press(KEY_LEFT_ALT);
    if (b.param1 & 8) Keyboard.press(KEY_LEFT_GUI);
    if (b.param2 != 0) Keyboard.press(b.param2);
  } else if (b.type == ACT_HID_MOUSE) {
    if (b.param1 == 1) Mouse.press(MOUSE_LEFT);
    else if (b.param1 == 2) Mouse.press(MOUSE_RIGHT);
    else if (b.param1 == 3) Mouse.press(MOUSE_MIDDLE);
    else if (b.param1 == 4) Mouse.move(0, 0, 1);
    else if (b.param1 == 5) Mouse.move(0, 0, -1);
  } else if (b.type == ACT_HID_MEDIA) {
    uint16_t code = getMediaUsageCode(b.param1);
    if (code != 0) Keyboard.consumerPress(code);
  }
}

void releaseHid(const HidBinding &b) {
  if (b.type == ACT_HID_KEY) {
    if (b.param2 != 0) Keyboard.release(b.param2);
    if (b.param1 & 8) Keyboard.release(KEY_LEFT_GUI);
    if (b.param1 & 4) Keyboard.release(KEY_LEFT_ALT);
    if (b.param1 & 2) Keyboard.release(KEY_LEFT_SHIFT);
    if (b.param1 & 1) Keyboard.release(KEY_LEFT_CTRL);
  } else if (b.type == ACT_HID_MOUSE) {
    if (b.param1 == 1) Mouse.release(MOUSE_LEFT);
    else if (b.param1 == 2) Mouse.release(MOUSE_RIGHT);
    else if (b.param1 == 3) Mouse.release(MOUSE_MIDDLE);
  } else if (b.type == ACT_HID_MEDIA) {
    Keyboard.consumerRelease();
  }
}

void releaseAllHid() {
  for (int i = 0; i < PENDING_SLOTS; i++) pendingReleases[i].active = false;
  Keyboard.releaseAll();
  Keyboard.consumerRelease();
  Mouse.release(MOUSE_LEFT);
  Mouse.release(MOUSE_RIGHT);
  Mouse.release(MOUSE_MIDDLE);
}

void tapHidNonBlocking(const HidBinding &b) {
  if (!isHidType(b.type)) return;
  // Колесо миші не потребує release
  if (b.type == ACT_HID_MOUSE && (b.param1 == 4 || b.param1 == 5)) {
    pressHid(b);
    return;
  }
  // Та сама клавіша ще "висить" від попереднього тапу (швидке обертання енкодера):
  // відпускаємо її зараз, інакше хост побачить одне довге натискання замість двох.
  for (int i = 0; i < PENDING_SLOTS; i++) {
    if (pendingReleases[i].active && sameBinding(pendingReleases[i].binding, b)) {
      releaseHid(pendingReleases[i].binding);
      pendingReleases[i].active = false;
    }
  }
  pressHid(b);
  unsigned long now = millis();
  for (int i = 0; i < PENDING_SLOTS; i++) {
    if (!pendingReleases[i].active) {
      pendingReleases[i] = {true, b, now + TAP_RELEASE_MS};
      return;
    }
  }
  // Усі слоти зайняті — звільняємо найстаріший
  int oldest = 0;
  for (int i = 1; i < PENDING_SLOTS; i++) {
    if ((long)(pendingReleases[i].releaseAt - pendingReleases[oldest].releaseAt) < 0) oldest = i;
  }
  releaseHid(pendingReleases[oldest].binding);
  pendingReleases[oldest] = {true, b, now + TAP_RELEASE_MS};
}

void processPendingReleases() {
  unsigned long now = millis();
  for (int i = 0; i < PENDING_SLOTS; i++) {
    if (pendingReleases[i].active && (long)(now - pendingReleases[i].releaseAt) >= 0) {
      releaseHid(pendingReleases[i].binding);
      pendingReleases[i].active = false;
    }
  }
}

// ---------------- Serial: вивід ----------------
void sendSerialLine(const char *msg) {
  size_t len = strlen(msg);
  if (Serial && Serial.availableForWrite() >= (int)(len + 2)) {
    Serial.write((const uint8_t *)msg, len);
    Serial.write((const uint8_t *)"\r\n", 2);
  }
}

void sendEvent(const char *name, const char *suffix, bool hwHandled) {
  char buf[48];
  snprintf(buf, sizeof(buf), "%s%s%s", name, suffix, (protoLevel >= 2 && hwHandled) ? ":HW" : "");
  sendSerialLine(buf);
}

void sendFired(int idx, int slot) {
  if (protoLevel < 2) return;
  char buf[48];
  snprintf(buf, sizeof(buf), "%s_FIRED:%s", getBtnName(idx), SLOT_NAMES[slot]);
  sendSerialLine(buf);
}

// ---------------- Serial: команди ----------------
static bool parseUint8(const char *s, uint8_t maxVal, uint8_t &out) {
  if (!s || !*s) return false;
  char *end = nullptr;
  long v = strtol(s, &end, 10);
  if (end == s || (*end != '\0' && *end != ':') || v < 0 || v > maxVal) return false;
  out = (uint8_t)v;
  return true;
}

// Невідома/пошкоджена специфікація -> SERIAL (подію обробить ПК, нічого не "загубиться").
HidBinding parseBindingSpec(const char *spec) {
  while (*spec == ' ') spec++;
  if (strcmp(spec, "NONE") == 0) return {ACT_NONE, 0, 0, 0};
  if (strcmp(spec, "SERIAL") == 0) return {ACT_SERIAL, 0, 0, 0};
  if (strncmp(spec, "HID_KEY:", 8) == 0) {
    const char *p = spec + 8;
    const char *colon = strchr(p, ':');
    uint8_t mod, key;
    if (colon && parseUint8(p, 15, mod) && parseUint8(colon + 1, 255, key) && (mod != 0 || key != 0)) {
      return {ACT_HID_KEY, mod, key, 0};
    }
  } else if (strncmp(spec, "HID_MOUSE:", 10) == 0) {
    uint8_t mb;
    if (parseUint8(spec + 10, 5, mb) && mb >= 1) return {ACT_HID_MOUSE, mb, 0, 0};
  } else if (strncmp(spec, "HID_MEDIA:", 10) == 0) {
    uint8_t mc;
    if (parseUint8(spec + 10, 255, mc) && getMediaUsageCode(mc) != 0) return {ACT_HID_MEDIA, mc, 0, 0};
  }
  return {ACT_SERIAL, 0, 0, 0};
}

void handleSetKey(char *rest) {
  char *firstColon = strchr(rest, ':');
  if (!firstColon) return;
  *firstColon = '\0';
  const char *target = rest;
  char *tail = firstColon + 1;
  size_t tlen = strlen(target);

  // Енкодер: ENC_x_L / ENC_x_R
  if (tlen == 7 && strncmp(target, "ENC_", 4) == 0 && target[5] == '_' &&
      (target[6] == 'L' || target[6] == 'R')) {
    int encIdx = target[4] - '1';
    int dir = (target[6] == 'R') ? 1 : 0;
    if (encIdx >= 0 && encIdx < NUM_ENC) {
      hwConfig.encoders[encIdx][dir] = parseBindingSpec(tail);
    }
    return;
  }

  int btnIdx = parseBtnIndex(target);
  if (btnIdx < 0) return;

  int slot = SLOT_TAP;
  const char *spec = tail;
  if (strncmp(tail, "TAP:", 4) == 0) { slot = SLOT_TAP; spec = tail + 4; }
  else if (strncmp(tail, "DTAP:", 5) == 0) { slot = SLOT_DTAP; spec = tail + 5; }
  else if (strncmp(tail, "HOLD:", 5) == 0) { slot = SLOT_HOLD; spec = tail + 5; }

  hwConfig.buttons[btnIdx][slot] = parseBindingSpec(spec);
}

void processSerialCommand(char *cmd) {
  if (strcmp(cmd, "PING_VPT_MACROPAD") == 0) {
    Serial.println("PONG_VPT_MACROPAD_V1");
  } else if (strncmp(cmd, "PROTO:", 6) == 0) {
    int req = atoi(cmd + 6);
    if (req < 1) req = 1;
    protoLevel = (req > PROTO_MAX) ? PROTO_MAX : (uint8_t)req;
    char buf[40];
    snprintf(buf, sizeof(buf), "PROTO_OK:%u:FW=%s", (unsigned)protoLevel, FW_VERSION);
    Serial.println(buf);
  } else if (strcmp(cmd, "ENTER_BOOTLOADER") == 0) {
    releaseAllHid();
    Serial.flush();
    delay(20);
    rp2040.rebootToBootloader();
  } else if (strcmp(cmd, "SAVE_EEPROM") == 0) {
    saveEEPROMConfig();
    Serial.println("EEPROM_SAVED");
  } else if (strcmp(cmd, "RESET_HW") == 0) {
    resetDefaultConfig();
    saveEEPROMConfig();
  } else if (strncmp(cmd, "SET_KEY:", 8) == 0) {
    handleSetKey(cmd + 8);
  }
}

void pollSerialInput() {
  // При закритті порту ПК повертаємось до протоколу v1 (сумісність зі старими версіями програми)
  bool hostOpen = (bool)Serial;
  if (hostWasOpen && !hostOpen) protoLevel = 1;
  hostWasOpen = hostOpen;

  int budget = 512; // не блокуємо цикл надовго навіть при великому пакеті команд
  while (budget-- > 0 && Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (!rxOverflow && rxLen > 0) {
        rxBuf[rxLen] = '\0';
        // trim
        char *start = rxBuf;
        while (*start == ' ' || *start == '\t') start++;
        char *end = rxBuf + rxLen - 1;
        while (end >= start && (*end == ' ' || *end == '\t')) *end-- = '\0';
        if (*start) processSerialCommand(start);
      }
      rxLen = 0;
      rxOverflow = false;
    } else if (!rxOverflow) {
      if (rxLen < sizeof(rxBuf) - 1) {
        rxBuf[rxLen++] = c;
      } else {
        // Задовгий рядок — ігноруємо його повністю до кінця рядка
        rxOverflow = true;
        rxLen = 0;
      }
    }
  }
}

// ---------------- Логіка кнопок ----------------
static int btnPin(int idx) {
  return (idx < 9) ? buttonPins[idx] : encSWPins[idx - 9];
}

void handleButtonLogic(int idx) {
  bool reading = digitalRead(btnPin(idx));
  unsigned long now = millis();

  if (reading != lastReadings[idx]) {
    lastDebounceTimes[idx] = now;
  }
  lastReadings[idx] = reading;

  PressContext &ctx = pressCtx[idx];

  if ((now - lastDebounceTimes[idx]) > DEBOUNCE_DELAY && reading != btnStates[idx]) {
    btnStates[idx] = reading;
    const char *bName = getBtnName(idx);

    if (btnStates[idx] == LOW) {
      // Знімок прив'язок на момент натискання
      for (int s = 0; s < 3; s++) ctx.slots[s] = hwConfig.buttons[idx][s];
      ctx.serialMode = (ctx.slots[SLOT_TAP].type == ACT_SERIAL) ||
                       (ctx.slots[SLOT_DTAP].type == ACT_SERIAL) ||
                       (ctx.slots[SLOT_HOLD].type == ACT_SERIAL);
      pressStartTime[idx] = now;
      holdTriggered[idx] = false;
      fastPathActive[idx] = false;

      sendEvent(bName, "_PRESSED", !ctx.serialMode);

      if (!ctx.serialMode) {
        bool hasMulti = (ctx.slots[SLOT_DTAP].type != ACT_NONE) || (ctx.slots[SLOT_HOLD].type != ACT_NONE);
        if (!hasMulti && isHidType(ctx.slots[SLOT_TAP].type)) {
          fastPathActive[idx] = true;
          tapCount[idx] = 0;
          pressHid(ctx.slots[SLOT_TAP]);
          sendFired(idx, SLOT_TAP);
        }
      }
    } else {
      sendEvent(bName, "_RELEASED", !ctx.serialMode);

      if (!ctx.serialMode) {
        if (fastPathActive[idx]) {
          releaseHid(ctx.slots[SLOT_TAP]);
          fastPathActive[idx] = false;
        } else if (holdTriggered[idx]) {
          if (isHidType(ctx.slots[SLOT_HOLD].type)) releaseHid(ctx.slots[SLOT_HOLD]);
          holdTriggered[idx] = false;
          tapCount[idx] = 0;
        } else if (ctx.slots[SLOT_DTAP].type == ACT_NONE) {
          if (isHidType(ctx.slots[SLOT_TAP].type)) {
            tapHidNonBlocking(ctx.slots[SLOT_TAP]);
            sendFired(idx, SLOT_TAP);
          }
          tapCount[idx] = 0;
        } else {
          tapCount[idx]++;
          lastReleaseTime[idx] = now;
          if (tapCount[idx] >= 2) {
            if (isHidType(ctx.slots[SLOT_DTAP].type)) {
              tapHidNonBlocking(ctx.slots[SLOT_DTAP]);
              sendFired(idx, SLOT_DTAP);
            }
            tapCount[idx] = 0;
          }
        }
      } else {
        tapCount[idx] = 0;
      }
    }
  }

  if (!ctx.serialMode && !fastPathActive[idx]) {
    if (btnStates[idx] == LOW && !holdTriggered[idx] && isHidType(ctx.slots[SLOT_HOLD].type)) {
      if ((now - pressStartTime[idx]) >= HOLD_TIME_MS) {
        holdTriggered[idx] = true;
        tapCount[idx] = 0;
        pressHid(ctx.slots[SLOT_HOLD]);
        sendFired(idx, SLOT_HOLD);
      }
    }
    if (btnStates[idx] == HIGH && tapCount[idx] == 1) {
      if ((now - lastReleaseTime[idx]) >= DTAP_WINDOW_MS) {
        if (isHidType(ctx.slots[SLOT_TAP].type)) {
          tapHidNonBlocking(ctx.slots[SLOT_TAP]);
          sendFired(idx, SLOT_TAP);
        }
        tapCount[idx] = 0;
      }
    }
  }
}

// ---------------- Логіка енкодерів ----------------
void processEncoder(int idx) {
  static const char *const ENC_NAMES[NUM_ENC] = {"ENC_1", "ENC_2", "ENC_3"};

  noInterrupts();
  int16_t steps = encSteps[idx];
  encSteps[idx] = 0;
  interrupts();
  if (steps == 0) return;

  int dir = (steps > 0) ? 1 : 0;          // 1 = RIGHT (за годинниковою), 0 = LEFT
  int count = (steps > 0) ? steps : -steps;
  if (count > MAX_ENC_STEPS_PER_LOOP) count = MAX_ENC_STEPS_PER_LOOP;

  for (int n = 0; n < count; n++) {
    const HidBinding b = hwConfig.encoders[idx][dir];
    bool hw = isHidType(b.type);
    if (hw) tapHidNonBlocking(b);
    sendEvent(ENC_NAMES[idx], dir == 1 ? "_RIGHT" : "_LEFT", hw);
  }
}

// ---------------- setup / loop ----------------
void setup() {
  USB.disconnect();
  USB.setManufacturer("VPT Tech");
  USB.setProduct("VPT MacroPad");
  EEPROM.begin(512);
  loadEEPROMConfig();
  Keyboard.begin();
  Mouse.begin();
  USB.connect();

  Serial.begin(115200);

  for (int i = 0; i < PENDING_SLOTS; i++) pendingReleases[i].active = false;

  for (int i = 0; i < NUM_BTNS; i++) {
    pinMode(btnPin(i), INPUT_PULLUP);
    lastReadings[i] = HIGH;
    btnStates[i] = HIGH;
    lastDebounceTimes[i] = 0;
    pressStartTime[i] = 0;
    lastReleaseTime[i] = 0;
    tapCount[i] = 0;
    holdTriggered[i] = false;
    fastPathActive[i] = false;
    pressCtx[i].serialMode = true;
    for (int s = 0; s < 3; s++) pressCtx[i].slots[s] = {ACT_NONE, 0, 0, 0};
  }

  for (int e = 0; e < NUM_ENC; e++) {
    pinMode(encCLKPins[e], INPUT_PULLUP);
    pinMode(encDTPins[e], INPUT_PULLUP);
    encIsrState[e] = readEncPins(e);
    encIsrDelta[e] = 0;
    encSteps[e] = 0;
    // Переривання замість опитування: кроки не губляться, навіть коли цикл
    // зайнятий відправкою HID-звітів або записом у флеш.
    attachInterrupt(digitalPinToInterrupt(encCLKPins[e]), ENC_ISRS[e], CHANGE);
    attachInterrupt(digitalPinToInterrupt(encDTPins[e]), ENC_ISRS[e], CHANGE);
  }
}

void loop() {
  processPendingReleases();

  for (int i = 0; i < NUM_BTNS; i++) {
    handleButtonLogic(i);
  }

  for (int e = 0; e < NUM_ENC; e++) {
    processEncoder(e);
  }

  pollSerialInput();
}
