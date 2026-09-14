// Test-only NI -> UNI peripheral clock-change oracle. No commercial content.
// Reuses discovery and the isolated fixture startup, NOT a product game driver.
#define QUALIFICATION_MAIN polling_qualification_main
#include "qualification.cpp"
#undef QUALIFICATION_MAIN

static unsigned char incoming[92];
static unsigned read_parent(LinkRawWireless& wireless) {
  LinkRawWireless::ReceiveDataResponse response;
  if (!wireless.receiveData(response)) stopped();
  if (response.dataSize > 23) stopped();
  // One parent and no children: retain the RFU byte count, not word padding.
  auto raw = wireless.sendCommand(0x13);
  if (!raw.success || !raw.dataSize || (raw.data[0] >> 24) != 5) return 0;
  memcpy(incoming, response.data, response.dataSize * 4);
  return response.dataSize * 4;
}

static void send_slot(LinkRawWireless& wireless, const unsigned char* slot, unsigned size) {
  unsigned words[4] = {};
  memcpy(words, slot, size);
  if (!wireless.sendData(words, (size + 3) / 4, size)) stopped();
}

extern "C" int main() {
  LinkRawWireless wireless;
  for (unsigned round = 1; round <= 2; ++round) {
    while (!start_pressed()) Link::wait(228);
    while (start_pressed()) Link::wait(228);
    if (!wireless.activate() || !wireless.setup(0) || !wireless.broadcastReadStart()) stopped();
    unsigned server_id = 0;
    while (!server_id) {
      Link::wait(228);
      auto response = wireless.sendCommand(0x1D);
      if (!response.success || response.dataSize > 28) stopped();
      for (unsigned i = 0; i + 7 <= response.dataSize; i += 7)
        if (trade_candidate(response.data + i)) server_id = response.data[i] & 0xFFFF;
    }
    if (!wireless.broadcastReadEnd() || !wireless.connect(server_id)) stopped();
    while (true) {
      LinkRawWireless::ConnectionStatus status;
      if (!wireless.keepConnecting(status)) stopped();
      if (status.phase == LinkRawWireless::ConnectionPhase::SUCCESS) break;
      if (status.phase == LinkRawWireless::ConnectionPhase::ERROR) stopped();
      Link::wait(228);
    }
    if (!wireless.finishConnection()) stopped();

    // Causal NI sender: no advancement until a matching native LLSF ACK.
    const unsigned char child[][16] = {
      {0x87, 0x04, 1, 12, 0, 26, 0, 0, 0},
      {0x8c, 0x08, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11},
      {0xac, 0x08, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23},
      {0xc2, 0x08, 24, 25}, {0, 0x0c}, {0x80, 0}
    };
    const unsigned sizes[] = {9, 14, 14, 4, 2, 2};
    for (unsigned i = 0; i < 6; ++i) {
      send_slot(wireless, child[i], sizes[i]);
      if (i == 5) break;
      while (true) {
        Link::wait(228);
        if (!read_parent(wireless)) continue;
        unsigned h = incoming[0] | incoming[1] << 8 | incoming[2] << 16;
        unsigned c = child[i][0] | child[i][1] << 8;
        if (((h >> 14) & 15) != ((c >> 10) & 15) || !(h & (1 << 13)) ||
            ((h >> 9) & 15) != ((c >> 5) & 15)) stopped();
        break;
      }
    }
    // Causal parent NI receiver, then enter RFU slave/clock-change wait.
    while (true) {
      Link::wait(228);
      if (!read_parent(wireless)) continue;
      unsigned h = incoming[0] | incoming[1] << 8 | incoming[2] << 16;
      unsigned state = (h >> 14) & 15;
      if (!state) break;
      if (state > 3 || (h & (1 << 13))) stopped();
      unsigned c = (state << 10) | (1 << 9) | (((h >> 9) & 15) << 5);
      const unsigned char ack[] = {static_cast<unsigned char>(c), static_cast<unsigned char>(c >> 8)};
      send_slot(wireless, ack, 2);
    }
    LinkRawWireless::CommandResult event;
    // Deliberately stop consuming RFU while Netplay callbacks remain active.
    // The host oracle sends twelve distinct UNI frames, exceeding gpSP's four
    // callback-ACK-before-admission slots if endpoint pacing is absent.
    Link::wait(228 * 90);
    if (!wireless.wait(event)) stopped();
    unsigned char previous[14] = {};
    for (unsigned sequence = 1;; ++sequence) {
      if (event.commandId == 0x29) break; // owned virtual radio room closed
      if (event.commandId == 0x27) { // technical RFU timeout, NOT a human timeout
        if (!wireless.wait(event)) stopped();
        --sequence;
        continue;
      }
      if (event.commandId != 0x28 || read_parent(wireless) != 76) stopped();
      const unsigned h = incoming[0] | incoming[1] << 8 | incoming[2] << 16;
      if (h != (70 | (4 << 14) | (1 << 18))) stopped();
      // Five 14-byte parent rows. Test counters live in row 0; row 1 must
      // reflect the prior child with rolling tag stripped, as in native gold.
      const unsigned char* row = incoming + 3;
      if (sequence <= 2) {
        for (unsigned i = 0; i < 70; ++i) if (row[i]) stopped();
      } else if (row[2] != round || (row[4] | row[5] << 8) != (sequence & 0xFFFF)) stopped();
      for (unsigned i = 0; i < 14; ++i)
        if (row[14 + i] != previous[i]) stopped();
      memcpy(previous, row, 14);
      const unsigned expected_tag = sequence <= 2 ? 0 : ((sequence - 3) & 7) << 5;
      unsigned char reply[16] = {14, 0x10};
      memcpy(reply + 2, row, 14);
      reply[2] = (reply[2] & 31) | expected_tag;
      unsigned words[4];
      memcpy(words, reply, 16);
      // This invokes real gpSP 0x25 -> slave clock -> adapter 0x28/0x27.
      // The next send cannot occur until an actual parent frame wakes it.
      if (!wireless.sendDataAndWait(words, 4, event, 16)) stopped();
    }
    wireless.deactivate();
  }
  stopped();
}
