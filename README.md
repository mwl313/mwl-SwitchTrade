# SwitchTrade

SwitchTrade lets two people trade Pokémon online between FireRed or LeafGreen running on Nintendo
Switch consoles.

Each player uses the SwitchTrade Windows app and a compatible USB Wi-Fi adapter. The app connects to
the nearby Switch, links both players through a private or public online room, and keeps the connection
active while they use the normal in-game trade flow.

## What you need

- Two Windows PCs
- Two Nintendo Switch consoles running FireRed or LeafGreen
- One compatible USB Wi-Fi adapter for each PC
- An internet connection for both players

## How to use it

1. Install SwitchTrade on both PCs.
2. Connect and select a Wi-Fi adapter in each app.
3. One player creates a Trade Room.
4. The other player joins with the room code or finds the room in the public list.
5. Follow the status panel and perform the requested action on each Switch.
6. Trade normally in the game, then end the connection from the app.

If something goes wrong, use **Export support logs**. SwitchTrade saves a privacy-filtered support
file to the Windows Desktop so the failed step can be investigated.

SwitchTrade is currently in beta. Support is limited to the games, Windows versions, and Wi-Fi
adapters accepted by the installed app.

## Supported Cards

Compatibility is determined by the adapter's exact USB ID, not only its brand or product name.

| Card | Chipset | USB ID | Status |
|---|---|---|---|
| Realtek RTL8192EU USB adapter | RTL8192EU | `0bda:818b` | **Confirmed** |
| ALFA AWUS036ACHM | MediaTek MT7610U | `0e8d:7610` | **Untested** |
| ALFA AWUS036ACM | MediaTek MT7612U | `0e8d:7612` | **Untested** |
| ALFA AWUS050NH / AWUS051NH family | Ralink RT2770 | `148f:2770` | **Untested** |
| ALFA AWUS036NH / AWUS036NEH family | Ralink RT3070 | `148f:3070` | **Untested** |
| ALFA AWUS051NHv2 / AWUS052 family | Ralink RT3572 | `148f:3572` | **Untested** |
| Realtek RTL8821CU USB adapter | RTL8821CU | `0bda:c811` | **Untested** |
| Any adapter with an unlisted USB ID | — | — | **Unsupported** |

**Confirmed** means SwitchTrade has passed real-hardware testing with that card. **Untested** means
the driver is included, but SwitchTrade has not yet confirmed the card on real hardware.

## Credits

Created by **Min W. Lim**.

SwitchTrade builds on research and open-source work by
[tornadus/frlg-ldn-trade](https://github.com/tornadus/frlg-ldn-trade),
[kinnay/LDN](https://github.com/kinnay/LDN),
[kinnay/NintendoClients](https://github.com/kinnay/NintendoClients),
[pret/pokefirered](https://github.com/pret/pokefirered), and
[GB-Link](https://github.com/GB-Link).

Third-party components retain their own licenses. See
[THIRD-PARTY-NOTICES.txt](legal/THIRD-PARTY-NOTICES.txt) and [bridge/LICENSE](bridge/LICENSE).
