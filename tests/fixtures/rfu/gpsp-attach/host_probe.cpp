// Test-only wrong-role fixture. Reuse the tiny freestanding runtime helpers.
#define main continuity_main
#include "main.cpp"
#undef main

extern "C" int main() {
  LinkRawWireless wireless;
  if (!wireless.activate() || !wireless.setup(2) || !wireless.startHost(false))
    stopped();
  // The qualification peer creates/removes RFU slots using public packets.
  // No game reset or memory inspection is used to verify slot retirement.
  stopped();
}
