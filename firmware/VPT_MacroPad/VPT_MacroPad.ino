#include <Arduino.h>
#ifdef USB
#undef USB
#endif
#include <USB.h>
#include <Keyboard.h>
#include <KeyboardLayout.h>
#include <Mouse.h>
#include <EEPROM.h>

// Піни 9 основних кнопок (BTN_1 .. BTN_9)
const int buttonPins[9] = {20, 22, 12, 19, 27, 13, 18, 17, 14};

// Піни 3 енкодерів EC11 та їхніх кнопок (ENC_1 .. ENC_3)
const int encCLKPins[3] = {4, 8, 11};
const int encDTPins[3]  = {26, 7, 10};
const int encSWPins[3]  = {2, 6, 9};

// Стан енкодерів EC11 (код Грея)
uint8_t encPrevState[3] = {3, 3, 3};
int8_t  encDelta[3]     = {0, 0, 0};

// Таблиця переходів квадратурного енкодера EC11
const int8_t ENC_TABLE[16] = {
   0,  1, -1,  0,
  -1,  0,  0,  1,
   1,  0,  0, -1,
   0, -1,  1,  0
};

const unsigned long DEBOUNCE_DELAY = 20;
const unsigned long HOLD_TIME_MS   = 300;
const unsigned long DTAP_WINDOW_MS = 220;

// Типи дій у пам'яті EEPROM
enum ActionType : uint8_t {
  ACT_SERIAL    = 0, // Відправляти подію тільки в Python-програму
  ACT_NONE      = 1, // Не призначено
  ACT_HID_KEY   = 2, // Клавіша + модифікатори (param1 = mod mask, param2 = keycode)
  ACT_HID_MOUSE = 3, // Клік/колесо миші (param1 = button/wheel code)
  ACT_HID_MEDIA = 4  // Медіа-клавіша (param1 = код медіа-дії)
};

struct HidBinding {
  uint8_t type;
  uint8_t param1;
  uint8_t param2;
  uint8_t reserved;
};

struct EEPROMConfig {
  uint32_t magic;
  // 12 кнопок (0..8 = BTN_1..9, 9..11 = ENC_1_SW..ENC_3_SW), 3 слоти (0=TAP, 1=DTAP, 2=HOLD)
  HidBinding buttons[12][3];
  // 3 енкодери, 2 напрямки (0=LEFT, 1=RIGHT)
  HidBinding encoders[3][2];
};

const uint32_t EEPROM_MAGIC = 0x56505433; // "VPT3"
EEPROMConfig hwConfig;

// Стани 12 фізичних кнопок
bool lastReadings[12];
bool btnStates[12];
unsigned long lastDebounceTimes[12];

// Машина станів Multi-Tap
unsigned long pressStartTime[12];
unsigned long lastReleaseTime[12];
uint8_t tapCount[12];
bool holdTriggered[12];
bool fastPathActive[12];

// Неблокуюча черга відпускання для коротких тапів та енкодерів
struct PendingTapRelease {
  bool active;
  HidBinding binding;
  unsigned long releaseAt;
};
PendingTapRelease pendingReleases[8];

String inputBuffer = "";

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
  hwConfig.magic = EEPROM_MAGIC;
  for (int b = 0; b < 12; b++) {
    hwConfig.buttons[b][0] = {ACT_SERIAL, 0, 0, 0};
    hwConfig.buttons[b][1] = {ACT_NONE, 0, 0, 0};
    hwConfig.buttons[b][2] = {ACT_NONE, 0, 0, 0};
  }
  for (int e = 0; e < 3; e++) {
    hwConfig.encoders[e][0] = {ACT_SERIAL, 0, 0, 0};
    hwConfig.encoders[e][1] = {ACT_SERIAL, 0, 0, 0};
  }
}

void loadEEPROMConfig() {
  EEPROM.get(0, hwConfig);
  if (hwConfig.magic != EEPROM_MAGIC) {
    resetDefaultConfig();
    EEPROM.put(0, hwConfig);
    EEPROM.commit();
  }
}

void saveEEPROMConfig() {
  hwConfig.magic = EEPROM_MAGIC;
  EEPROM.put(0, hwConfig);
  EEPROM.commit();
}

String getBtnName(int idx) {
  if (idx < 9) return "BTN_" + String(idx + 1);
  return "ENC_" + String(idx - 8) + "_SW";
}

int parseBtnIndex(String name) {
  if (name.startsWith("BTN_")) {
    int n = name.substring(4).toInt();
    if (n >= 1 && n <= 9) return n - 1;
  } else if (name.startsWith("ENC_") && name.endsWith("_SW")) {
    int n = name.substring(4, 5).toInt();
    if (n >= 1 && n <= 3) return 8 + n;
  }
  return -1;
}

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

void tapHidNonBlocking(const HidBinding &b) {
  // Колесо миші не потребує release
  if (b.type == ACT_HID_MOUSE && (b.param1 == 4 || b.param1 == 5)) {
    pressHid(b);
    return;
  }
  pressHid(b);
  unsigned long now = millis();
  for (int i = 0; i < 8; i++) {
    if (!pendingReleases[i].active) {
      pendingReleases[i] = {true, b, now + 8};
      return;
    }
  }
  // Якщо всі слоти зайняті — звільняємо найстаріший
  releaseHid(pendingReleases[0].binding);
  pendingReleases[0] = {true, b, now + 8};
}

void processPendingReleases() {
  unsigned long now = millis();
  for (int i = 0; i < 8; i++) {
    if (pendingReleases[i].active && (long)(now - pendingReleases[i].releaseAt) >= 0) {
      releaseHid(pendingReleases[i].binding);
      pendingReleases[i].active = false;
    }
  }
}

HidBinding parseBindingSpec(String spec) {
  spec.trim();
  if (spec == "NONE") return {ACT_NONE, 0, 0, 0};
  if (spec == "SERIAL") return {ACT_SERIAL, 0, 0, 0};
  if (spec.startsWith("HID_KEY:")) {
    int p1 = spec.indexOf(':', 8);
    if (p1 != -1) {
      uint8_t mod = (uint8_t)spec.substring(8, p1).toInt();
      uint8_t key = (uint8_t)spec.substring(p1 + 1).toInt();
      return {ACT_HID_KEY, mod, key, 0};
    }
  } else if (spec.startsWith("HID_MOUSE:")) {
    uint8_t mb = (uint8_t)spec.substring(10).toInt();
    return {ACT_HID_MOUSE, mb, 0, 0};
  } else if (spec.startsWith("HID_MEDIA:")) {
    uint8_t mc = (uint8_t)spec.substring(10).toInt();
    return {ACT_HID_MEDIA, mc, 0, 0};
  }
  return {ACT_SERIAL, 0, 0, 0};
}

void processSerialCommand(String cmd) {
  if (cmd == "PING_VPT_MACROPAD") {
    Serial.println("PONG_VPT_MACROPAD_V1");
  } else if (cmd == "ENTER_BOOTLOADER") {
    rp2040.rebootToBootloader();
  } else if (cmd == "SAVE_EEPROM") {
    saveEEPROMConfig();
    Serial.println("EEPROM_SAVED");
  } else if (cmd == "RESET_HW") {
    resetDefaultConfig();
    saveEEPROMConfig();
  } else if (cmd.startsWith("SET_KEY:")) {
    String rest = cmd.substring(8);
    int firstColon = rest.indexOf(':');
    if (firstColon == -1) return;
    String target = rest.substring(0, firstColon);
    String tail = rest.substring(firstColon + 1);

    if (target.startsWith("ENC_") && (target.endsWith("_L") || target.endsWith("_R"))) {
      int encIdx = target.substring(4, 5).toInt() - 1;
      int dir = target.endsWith("_R") ? 1 : 0;
      if (encIdx >= 0 && encIdx < 3) {
        hwConfig.encoders[encIdx][dir] = parseBindingSpec(tail);
      }
      return;
    }

    int btnIdx = parseBtnIndex(target);
    if (btnIdx < 0 || btnIdx >= 12) return;

    int slot = 0;
    String spec = tail;
    if (tail.startsWith("TAP:")) { slot = 0; spec = tail.substring(4); }
    else if (tail.startsWith("DTAP:")) { slot = 1; spec = tail.substring(5); }
    else if (tail.startsWith("HOLD:")) { slot = 2; spec = tail.substring(5); }

    hwConfig.buttons[btnIdx][slot] = parseBindingSpec(spec);
  }
}

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
  inputBuffer.reserve(256);

  for (int i = 0; i < 8; i++) {
    pendingReleases[i].active = false;
  }

  for (int i = 0; i < 12; i++) {
    int pin = (i < 9) ? buttonPins[i] : encSWPins[i - 9];
    pinMode(pin, INPUT_PULLUP);
    lastReadings[i] = HIGH;
    btnStates[i] = HIGH;
    lastDebounceTimes[i] = 0;
    pressStartTime[i] = 0;
    lastReleaseTime[i] = 0;
    tapCount[i] = 0;
    holdTriggered[i] = false;
    fastPathActive[i] = false;
  }

  for (int e = 0; e < 3; e++) {
    pinMode(encCLKPins[e], INPUT_PULLUP);
    pinMode(encDTPins[e], INPUT_PULLUP);
    uint8_t s = (digitalRead(encCLKPins[e]) ? 1 : 0) | (digitalRead(encDTPins[e]) ? 2 : 0);
    encPrevState[e] = s;
    encDelta[e] = 0;
  }
}

void sendSerialLine(const String &msg) {
  if (Serial && Serial.availableForWrite() >= (int)(msg.length() + 2)) {
    Serial.println(msg);
  }
}

void handleButtonLogic(int idx) {
  int pin = (idx < 9) ? buttonPins[idx] : encSWPins[idx - 9];
  bool reading = digitalRead(pin);
  unsigned long now = millis();

  if (reading != lastReadings[idx]) {
    lastDebounceTimes[idx] = now;
  }

  bool anySerial = (hwConfig.buttons[idx][0].type == ACT_SERIAL) ||
                   (hwConfig.buttons[idx][1].type == ACT_SERIAL) ||
                   (hwConfig.buttons[idx][2].type == ACT_SERIAL);

  if ((now - lastDebounceTimes[idx]) > DEBOUNCE_DELAY) {
    if (reading != btnStates[idx]) {
      btnStates[idx] = reading;
      String bName = getBtnName(idx);

      bool hasMulti = (hwConfig.buttons[idx][1].type != ACT_NONE) || (hwConfig.buttons[idx][2].type != ACT_NONE);

      if (btnStates[idx] == LOW) {
        pressStartTime[idx] = now;
        holdTriggered[idx] = false;

        sendSerialLine(bName + "_PRESSED");

        if (!anySerial) {
          if (!hasMulti && hwConfig.buttons[idx][0].type >= ACT_HID_KEY) {
            fastPathActive[idx] = true;
            pressHid(hwConfig.buttons[idx][0]);
          } else {
            fastPathActive[idx] = false;
          }
        }
      } else {
        sendSerialLine(bName + "_RELEASED");

        if (!anySerial) {
          if (fastPathActive[idx]) {
            releaseHid(hwConfig.buttons[idx][0]);
            fastPathActive[idx] = false;
          } else if (holdTriggered[idx]) {
            if (hwConfig.buttons[idx][2].type >= ACT_HID_KEY) {
              releaseHid(hwConfig.buttons[idx][2]);
            }
            holdTriggered[idx] = false;
            tapCount[idx] = 0;
          } else {
            if (hwConfig.buttons[idx][1].type == ACT_NONE) {
              if (hwConfig.buttons[idx][0].type >= ACT_HID_KEY) {
                tapHidNonBlocking(hwConfig.buttons[idx][0]);
              }
              tapCount[idx] = 0;
            } else {
              tapCount[idx]++;
              lastReleaseTime[idx] = now;
              if (tapCount[idx] >= 2) {
                if (hwConfig.buttons[idx][1].type >= ACT_HID_KEY) {
                  tapHidNonBlocking(hwConfig.buttons[idx][1]);
                }
                tapCount[idx] = 0;
              }
            }
          }
        }
      }
    }
  }
  lastReadings[idx] = reading;

  if (!anySerial && !fastPathActive[idx]) {
    if (btnStates[idx] == LOW && !holdTriggered[idx] && hwConfig.buttons[idx][2].type >= ACT_HID_KEY) {
      if ((now - pressStartTime[idx]) >= HOLD_TIME_MS) {
        holdTriggered[idx] = true;
        tapCount[idx] = 0;
        pressHid(hwConfig.buttons[idx][2]);
      }
    }
    if (btnStates[idx] == HIGH && tapCount[idx] == 1) {
      if ((now - lastReleaseTime[idx]) >= DTAP_WINDOW_MS) {
        if (hwConfig.buttons[idx][0].type >= ACT_HID_KEY) {
          tapHidNonBlocking(hwConfig.buttons[idx][0]);
        }
        tapCount[idx] = 0;
      }
    }
  }
}

void checkEncoderEC11(int idx, String encName) {
  uint8_t s = (digitalRead(encCLKPins[idx]) ? 1 : 0) | (digitalRead(encDTPins[idx]) ? 2 : 0);
  if (s != encPrevState[idx]) {
    int8_t step = ENC_TABLE[(encPrevState[idx] << 2) | s];
    encPrevState[idx] = s;
    encDelta[idx] += step;

    if (s == 3) {
      int dir = -1;
      if (encDelta[idx] >= 2) dir = 1;       // RIGHT (За годинниковою)
      else if (encDelta[idx] <= -2) dir = 0; // LEFT (Проти годинникової)
      encDelta[idx] = 0;

      if (dir != -1) {
        HidBinding b = hwConfig.encoders[idx][dir];
        if (b.type >= ACT_HID_KEY) {
          tapHidNonBlocking(b);
        }
        sendSerialLine(encName + (dir == 1 ? "_RIGHT" : "_LEFT"));
      }
    }
  }
}

void loop() {
  processPendingReleases();

  for (int i = 0; i < 12; i++) {
    handleButtonLogic(i);
  }

  checkEncoderEC11(0, "ENC_1");
  checkEncoderEC11(1, "ENC_2");
  checkEncoderEC11(2, "ENC_3");

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      inputBuffer.trim();
      if (inputBuffer.length() > 0) {
        processSerialCommand(inputBuffer);
      }
      inputBuffer = "";
    } else {
      inputBuffer += c;
      if (inputBuffer.length() > 240) inputBuffer = "";
    }
  }
}