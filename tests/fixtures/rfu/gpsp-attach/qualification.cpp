// Final qualification homebrew: human-input gate, sustained real RFU traffic,
// and two rooms in the same game memory. No commercial content or saves.
#define main continuity_main
#include "main.cpp"
#undef main

static bool start_pressed() {
  return !(*reinterpret_cast<volatile unsigned short*>(0x04000130) & (1 << 3));
}

// Independent game-side discovery gate, after stock gpSP's RFU command path.
// Native configGameData layout (not Switch search-record offsets): gname13,
// checksum1, uname8. Only the qualified English FR/LG empty Trade profile.
static bool trade_candidate(const unsigned* server) {
  const auto* data = reinterpret_cast<const unsigned char*>(server + 1);
  const auto* game = data + 2;
  const auto* name = data + 16;
  unsigned sum = 0;
  bool terminated = false;
  for (unsigned i = 0; i < 8; ++i) {
    sum += game[i] + name[i];
    terminated |= name[i] == 0xFF;
  }
  const unsigned compatibility = game[0] | (game[1] << 8);
  return data[0] == 2 && data[1] == 0 && ((server[0] >> 16) & 255) != 0xFF &&
      (compatibility == 0x1002 || compatibility == 0x1402) &&
      game[4] == 0 && game[5] == 0 && game[6] == 0 && game[7] == 0 &&
      game[8] == 0 && game[9] == 0 && game[10] == 4 &&
      game[11] <= 1 && game[12] == 0 && game[13] == ((~sum) & 0xFF) &&
      name[0] != 0xFF && terminated;
}

extern "C" int main() {
  LinkRawWireless wireless;
  for (unsigned round = 1; round <= 2; ++round) {
    // Test-only substitute for the human choosing Join Group, not an emulator
    // reset/launch command. Netplay/RFU mode probes must work before this.
    while (!start_pressed()) Link::wait(228);
    while (start_pressed()) Link::wait(228);
    if (!wireless.activate() || !wireless.setup(0)) stopped();
    if (!wireless.broadcastReadStart()) stopped();
    unsigned server_id = 0;
    while (true) {
      Link::wait(228);
      // The library's string helper removes embedded zero bytes. Native game
      // metadata is binary: inspect the public raw RFU response instead.
      auto response = wireless.sendCommand(0x1D);
      if (!response.success || response.dataSize > 28) stopped();
      bool found = false;
      for (unsigned i = 0; i < response.dataSize; i += 7) {
        if (i + 7 > response.dataSize) stopped();
        if (trade_candidate(response.data + i)) {
          server_id = response.data[i] & 0xFFFF;
          found = true;
          break;
        }
      }
      if (found) break;
    }
    if (!wireless.broadcastReadEnd() || !wireless.connect(server_id)) stopped();
    while (true) {
      Link::wait(228);
      LinkRawWireless::ConnectionStatus status;
      if (!wireless.keepConnecting(status)) stopped();
      if (status.phase == LinkRawWireless::ConnectionPhase::SUCCESS) break;
      if (status.phase == LinkRawWireless::ConnectionPhase::ERROR) stopped();
    }
    if (!wireless.finishConnection()) stopped();
    bool connected = true;
    for (unsigned sequence = 1; connected; ++sequence) {
      const unsigned payload[] = {0x53544632, round, sequence};
      if (!wireless.sendData(payload, 3)) stopped();
      while (true) {
        Link::wait(228);
        LinkRawWireless::SystemStatusResponse state;
        if (!wireless.getSystemStatus(state)) stopped();
        if (state.adapterState != LinkRawWireless::State::CONNECTED) {
          connected = false;
          break;  // Real radio-room loss, delivered by the product RFU path.
        }
        LinkRawWireless::ReceiveDataResponse response;
        if (!wireless.receiveData(response)) stopped();
        if (response.dataSize > 0) {
          if (response.dataSize != 3 || response.data[0] != 0x53544832 ||
              response.data[1] != round || response.data[2] != sequence) stopped();
          break;
        }
      }
    }
    wireless.deactivate();
  }
  stopped();
}
