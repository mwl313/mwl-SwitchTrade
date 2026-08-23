# WSL dual-radio FRLG discovery capture — 2026-08-24

- Capture window: 08:14:08.52–08:18:23.43 KST
- User flow: connect both Switches, enter room, approach chair, trade one Pokémon, end, leave
- Switch A used the Internet to satisfy the game license check; router traffic is not trade traffic.
- Both radios hopped channels 1–13 at 0.4 s dwell, staggered.
- RTL8192EU: 13,341 packets, kernel drop 0.
- RTL8188EU: 7,061 packets, kernel drop 0.
- Local LDN host/BSSID: `a4:c1:e8:66:73:25`
- Local LDN peer: `98:41:5c:79:41:38`
- Decoded rooms: CH11 at 08:15:48, then a new CH1 room at 08:16:05; peer joined at 08:16:10.
- Full analysis: `docs/25-goldencapture-2차-WSL-결과.md`

These PCAPs prove discovery/channel/card RX. They are not a continuous trade replay gold because
channel hopping intentionally leaves gaps. Use a fixed-channel capture for protocol reconstruction.
