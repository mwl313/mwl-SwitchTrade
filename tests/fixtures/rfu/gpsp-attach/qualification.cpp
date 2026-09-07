// Final qualification homebrew: human-input gate, sustained real RFU traffic,
// and two rooms in the same game memory. No commercial content or saves.
#define main continuity_main
#include "main.cpp"
#undef main

static bool start_pressed() {
  return !(*reinterpret_cast<volatile unsigned short*>(0x04000130) & (1 << 3));
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
    LinkRawWireless::Server server;
    while (true) {
      Link::wait(228);
      LinkRawWireless::BroadcastReadPollResponse response;
      if (!wireless.broadcastReadPoll(response)) stopped();
      if (response.serversSize) { server = response.servers[0]; break; }
    }
    if (!wireless.broadcastReadEnd() || !wireless.connect(server.id)) stopped();
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
