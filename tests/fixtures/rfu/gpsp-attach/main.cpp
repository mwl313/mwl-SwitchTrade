// Test-only homebrew. No commercial game, BIOS, save, or injected code.
// Two RFU exchanges carry an increasing in-RAM round number. A core reset or
// content reload restarts at round 1 and therefore fails the external harness.
#include "LinkRawWireless.hpp"

extern "C" void* memcpy(void* destination, const void* source, unsigned int size) {
  auto* out = static_cast<unsigned char*>(destination);
  auto* in = static_cast<const unsigned char*>(source);
  while (size--) *out++ = *in++;
  return destination;
}
extern "C" void* memset(void* destination, int value, unsigned int size) {
  auto* out = static_cast<unsigned char*>(destination);
  while (size--) *out++ = static_cast<unsigned char>(value);
  return destination;
}
[[noreturn]] void stopped() { while (true) asm volatile("nop"); }

extern "C" int main() {
  LinkRawWireless wireless;
  for (unsigned int round = 1; round <= 2; ++round) {
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
    }
    if (!wireless.finishConnection()) stopped();
    const unsigned int payload[] = {0x53544631, round};
    if (!wireless.sendData(payload, 2)) stopped();
    while (true) {
      Link::wait(228);
      LinkRawWireless::ReceiveDataResponse response;
      if (!wireless.receiveData(response)) stopped();
      if (response.dataSize > 0) {
        if (response.dataSize != 2 || response.data[0] != 0x53544831 ||
            response.data[1] != round) stopped();
        break;
      }
    }
    if (!wireless.disconnectClient(false, false, false, false)) stopped();
    wireless.deactivate();
  }
  stopped();
}
