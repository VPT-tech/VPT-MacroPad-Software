#pragma once
struct MockUSB {
  void disconnect() {}
  void connect() {}
  void setManufacturer(const char *) {}
  void setProduct(const char *) {}
};
extern MockUSB USB;
