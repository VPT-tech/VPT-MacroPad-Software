# Хостові тести прошивки (не потребують плати): make -C tests/firmware_sim
CXX ?= g++
CXXFLAGS ?= -std=gnu++17 -Wall -Wextra -Wno-unused-parameter -g -fsanitize=address,undefined

test: test_firmware fw_stdio fw_stdio_legacy
	./test_firmware

# Прошивка як процес реального часу для наскрізного тесту tests/test_e2e_hw_sync.py
fw_stdio: fw_stdio.cpp ../../firmware/VPT_MacroPad/VPT_MacroPad.ino mocks/*.h
	$(CXX) -std=gnu++17 -O1 -Imocks -x c++ fw_stdio.cpp -o $@

# Стара прошивка v1.0 (як у платах користувачів до оновлення) — перевірка сумісності програми
fw_stdio_legacy: fw_stdio.cpp legacy/VPT_MacroPad_v1_0.ino mocks/*.h
	$(CXX) -std=gnu++17 -O1 -Imocks '-DFW_SOURCE="legacy/VPT_MacroPad_v1_0.ino"' -x c++ fw_stdio.cpp -o $@

test_firmware: test_firmware.cpp ../../firmware/VPT_MacroPad/VPT_MacroPad.ino mocks/*.h
	$(CXX) $(CXXFLAGS) -Imocks -x c++ test_firmware.cpp -o $@

clean:
	rm -f test_firmware fw_stdio fw_stdio_legacy

.PHONY: test clean
