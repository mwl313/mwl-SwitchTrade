'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  clientPointToNative,
  configureNativeCanvas,
  drawBitmapText,
  drawDialogueWindow,
  drawNeutralWindow,
  drawSelectionCursor,
  EMERALD_UI_PALETTE,
} from '../SwitchTrade-UI-Kit/emerald-ui-primitives';

type Screen = 'main' | 'host' | 'join' | 'public' | 'passcode' | 'lobby' | 'configuration';
type LobbyRole = 'host' | 'guest';

const MAIN_ITEMS = ['Host a Trade Group', 'Join a Trade Group', 'Configuration'];
const PUBLIC_GROUPS = [
  { name: "MAY'S TRADE ROOM", owner: 'LITTLEROOT', status: 'OPEN', code: 'TREE42' },
  { name: 'KANTO LINK CLUB', owner: 'PALLET', status: 'WAIT', code: 'RED151' },
  { name: 'NIGHT TRADES', owner: 'SLATEPORT', status: 'OPEN', code: 'MOON25' },
];

function drawBase(context: CanvasRenderingContext2D, title: string) {
  context.fillStyle = '#5fc89f';
  context.fillRect(0, 0, 240, 160);
  context.fillStyle = '#48b78e';
  context.fillRect(0, 0, 240, 4);
  context.fillRect(0, 155, 240, 5);
  drawBitmapText(context, title, 8, 9, {
    color: EMERALD_UI_PALETTE.title,
    shadow: EMERALD_UI_PALETTE.titleShadow,
  });
  drawBitmapText(context, 'SWITCHTRADE', 232, 9, { align: 'right' });
}

function drawMenuItem(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  selected: boolean,
  color: string = EMERALD_UI_PALETTE.ink,
  shadow: string = EMERALD_UI_PALETTE.inkShadow,
) {
  if (selected) drawSelectionCursor(context, x, y);
  drawBitmapText(context, text, x + 10, y, { color, shadow });
}

function drawHint(context: CanvasRenderingContext2D, line1: string, line2 = '') {
  drawDialogueWindow(context, { x: 5, y: 116, width: 230, height: 38 });
  drawBitmapText(context, line1, 16, 128);
  if (line2) {
    drawBitmapText(context, line2, 16, 140, {
      color: EMERALD_UI_PALETTE.blue,
      shadow: EMERALD_UI_PALETTE.blueShadow,
    });
  }
}

function clipped(value: string, empty: string, max = 22) {
  return (value || empty).slice(0, max);
}

export default function Home() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [screen, setScreen] = useState<Screen>('main');
  const [selection, setSelection] = useState(0);
  const [groupName, setGroupName] = useState('MY TRADE GROUP');
  const [visibility, setVisibility] = useState<'PRIVATE' | 'PUBLIC'>('PRIVATE');
  const [passcode, setPasscode] = useState('');
  const [lobbyRole, setLobbyRole] = useState<LobbyRole>('host');
  const [lobbyName, setLobbyName] = useState('MY TRADE GROUP');
  const [lobbyCode, setLobbyCode] = useState('LINK25');
  const [ready, setReady] = useState(false);

  const itemCount = screen === 'main' ? 3
    : screen === 'host' ? 3
    : screen === 'join' ? 2
    : screen === 'public' ? PUBLIC_GROUPS.length
    : screen === 'passcode' ? 2
    : screen === 'lobby' ? 2
    : 2;

  const go = useCallback((next: Screen, index = 0) => {
    setScreen(next);
    setSelection(index);
  }, []);

  const openLobby = useCallback((role: LobbyRole, name: string, code: string) => {
    setLobbyRole(role);
    setLobbyName(name);
    setLobbyCode(code);
    setReady(false);
    go('lobby');
  }, [go]);

  const activate = useCallback((index = selection) => {
    if (screen === 'main') {
      go((['host', 'join', 'configuration'] as Screen[])[index]);
    } else if (screen === 'host') {
      if (index === 1) setVisibility((value) => value === 'PRIVATE' ? 'PUBLIC' : 'PRIVATE');
      if (index === 2) openLobby('host', clipped(groupName, 'MY TRADE GROUP'), 'LINK25');
    } else if (screen === 'join') {
      go(index === 0 ? 'public' : 'passcode');
    } else if (screen === 'public') {
      const group = PUBLIC_GROUPS[index];
      if (group.status === 'OPEN') openLobby('guest', group.name, group.code);
    } else if (screen === 'passcode') {
      if (index === 1 && passcode.length >= 4) openLobby('guest', 'PRIVATE TRADE GROUP', passcode);
    } else if (screen === 'lobby') {
      if (index === 0) setReady((value) => !value);
      if (index === 1) go('main');
    } else if (screen === 'configuration') {
      if (index === 1) go('main');
    }
  }, [go, groupName, openLobby, passcode, screen, selection]);

  const back = useCallback(() => {
    if (screen === 'main') return;
    if (screen === 'public' || screen === 'passcode') go('join');
    else if (screen === 'lobby') go(lobbyRole === 'host' ? 'host' : 'join');
    else go('main');
  }, [go, lobbyRole, screen]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = configureNativeCanvas(canvas);

    if (screen === 'main') {
      drawBase(context, 'LINK DESK');
      drawNeutralWindow(context, { x: 28, y: 30, width: 184, height: 78 });
      MAIN_ITEMS.forEach((item, index) => drawMenuItem(context, item, 41, 43 + index * 19, selection === index));
      drawHint(context, 'Choose how you want to connect.', 'ENTER Confirm   ESC Back');
    } else if (screen === 'host') {
      drawBase(context, 'HOST GROUP');
      drawNeutralWindow(context, { x: 15, y: 27, width: 210, height: 82 });
      drawBitmapText(context, 'GROUP NAME', 29, 39, { color: EMERALD_UI_PALETTE.green, shadow: EMERALD_UI_PALETTE.greenShadow });
      drawMenuItem(context, clipped(groupName, 'TYPE A NAME'), 28, 53, selection === 0);
      context.fillStyle = '#d5d2cb';
      context.fillRect(38, 65, 170, 1);
      drawMenuItem(context, `VISIBILITY: ${visibility}`, 28, 73, selection === 1);
      drawMenuItem(context, 'CREATE GROUP', 28, 91, selection === 2, EMERALD_UI_PALETTE.blue, EMERALD_UI_PALETTE.blueShadow);
      drawHint(context, selection === 0 ? 'Type a name with your keyboard.' : 'The group opens before the Switch.', 'UP/DOWN Move   ENTER Select');
    } else if (screen === 'join') {
      drawBase(context, 'JOIN GROUP');
      drawNeutralWindow(context, { x: 23, y: 34, width: 194, height: 66 });
      drawMenuItem(context, 'Browse Public Groups', 36, 50, selection === 0);
      drawMenuItem(context, 'Enter Group Passcode', 36, 73, selection === 1);
      drawHint(context, 'Find a group or use a private code.', 'ENTER Confirm   ESC Back');
    } else if (screen === 'public') {
      drawBase(context, 'PUBLIC GROUPS');
      drawNeutralWindow(context, { x: 7, y: 25, width: 226, height: 84 });
      PUBLIC_GROUPS.forEach((group, index) => {
        const y = 37 + index * 22;
        drawMenuItem(context, group.name, 17, y, selection === index);
        drawBitmapText(context, `${group.owner}  ${group.status}`, 215, y, {
          align: 'right',
          color: group.status === 'OPEN' ? EMERALD_UI_PALETTE.green : EMERALD_UI_PALETTE.red,
          shadow: group.status === 'OPEN' ? EMERALD_UI_PALETTE.greenShadow : EMERALD_UI_PALETTE.redShadow,
        });
      });
      drawHint(context, PUBLIC_GROUPS[selection].status === 'OPEN' ? 'This group is ready to join.' : 'This host is waiting for a Switch.', 'ENTER Join   ESC Back');
    } else if (screen === 'passcode') {
      drawBase(context, 'PRIVATE GROUP');
      drawNeutralWindow(context, { x: 31, y: 36, width: 178, height: 65 });
      drawBitmapText(context, 'GROUP PASSCODE', 47, 49, { color: EMERALD_UI_PALETTE.green, shadow: EMERALD_UI_PALETTE.greenShadow });
      drawMenuItem(context, clipped(passcode, 'TYPE CODE', 8), 46, 65, selection === 0);
      drawMenuItem(context, 'JOIN GROUP', 46, 84, selection === 1, EMERALD_UI_PALETTE.blue, EMERALD_UI_PALETTE.blueShadow);
      drawHint(context, 'Enter the code shared by your host.', 'Letters and numbers only');
    } else if (screen === 'configuration') {
      drawBase(context, 'CONFIGURATION');
      drawNeutralWindow(context, { x: 7, y: 25, width: 226, height: 85 });
      drawBitmapText(context, 'RTL8192EU  0BDA:818B', 19, 37, { color: EMERALD_UI_PALETTE.green, shadow: EMERALD_UI_PALETTE.greenShadow });
      drawBitmapText(context, 'BETA CANDIDATE / AUTO', 19, 50);
      drawBitmapText(context, 'RTL8188EU  0BDA:8179', 19, 67, { color: EMERALD_UI_PALETTE.red, shadow: EMERALD_UI_PALETTE.redShadow });
      drawBitmapText(context, 'QUARANTINED / OBSERVE', 19, 80);
      drawMenuItem(context, 'RECHECK HARDWARE', 19, 96, selection === 0, EMERALD_UI_PALETTE.blue, EMERALD_UI_PALETTE.blueShadow);
      if (selection === 1) drawSelectionCursor(context, 159, 96);
      drawBitmapText(context, 'BACK', 169, 96);
      drawHint(context, 'Only healthy certified cards run.', 'Profiles make new drivers easy to add');
    } else {
      drawBase(context, 'TRADE GROUP LOBBY');
      drawNeutralWindow(context, { x: 7, y: 24, width: 226, height: 86 });
      drawBitmapText(context, clipped(lobbyName, 'TRADE GROUP', 26), 19, 36, { color: EMERALD_UI_PALETTE.green, shadow: EMERALD_UI_PALETTE.greenShadow });
      drawBitmapText(context, `CODE  ${lobbyCode}`, 19, 50, { color: EMERALD_UI_PALETTE.blue, shadow: EMERALD_UI_PALETTE.blueShadow });
      drawBitmapText(context, `${lobbyRole.toUpperCase()} ENDPOINT`, 19, 64);
      drawBitmapText(context, ready ? 'READY - WAITING FOR PEER' : 'NOT READY', 19, 77, {
        color: ready ? EMERALD_UI_PALETTE.green : EMERALD_UI_PALETTE.red,
        shadow: ready ? EMERALD_UI_PALETTE.greenShadow : EMERALD_UI_PALETTE.redShadow,
      });
      drawMenuItem(context, ready ? 'CANCEL READY' : 'I AM READY', 19, 95, selection === 0);
      if (selection === 1) drawSelectionCursor(context, 157, 95);
      drawBitmapText(context, 'LEAVE', 167, 95);
      drawHint(context, ready ? 'Open Direct Corner on your Switch.' : 'Share the code, then mark ready.', ready ? 'The app will guide the next step.' : 'ENTER Select   ESC Back');
    }
  }, [groupName, lobbyCode, lobbyName, lobbyRole, passcode, ready, screen, selection, visibility]);

  useEffect(draw, [draw]);

  function onKeyDown(event: React.KeyboardEvent<HTMLCanvasElement>) {
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setSelection((selection + itemCount - 1) % itemCount);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setSelection((selection + 1) % itemCount);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      activate();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      back();
    } else if (screen === 'host' && selection === 0) {
      if (event.key === 'Backspace') setGroupName((value) => value.slice(0, -1));
      else if (event.key.length === 1 && /^[a-z0-9 '!-]$/i.test(event.key)) setGroupName((value) => (value + event.key.toUpperCase()).slice(0, 22));
    } else if (screen === 'passcode' && selection === 0) {
      if (event.key === 'Backspace') setPasscode((value) => value.slice(0, -1));
      else if (event.key.length === 1 && /^[a-z0-9]$/i.test(event.key)) setPasscode((value) => (value + event.key.toUpperCase()).slice(0, 8));
    }
  }

  function onPointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    const point = clientPointToNative(event.currentTarget, event.clientX, event.clientY);
    let index: number | null = null;
    if (screen === 'main' && point.y >= 38 && point.y < 97) index = Math.min(2, Math.floor((point.y - 38) / 19));
    else if (screen === 'host' && point.y >= 48 && point.y < 108) index = Math.min(2, Math.floor((point.y - 48) / 20));
    else if (screen === 'join' && point.y >= 45 && point.y < 91) index = Math.min(1, Math.floor((point.y - 45) / 23));
    else if (screen === 'public' && point.y >= 33 && point.y < 99) index = Math.min(2, Math.floor((point.y - 33) / 22));
    else if (screen === 'passcode' && point.y >= 59 && point.y < 99) index = Math.min(1, Math.floor((point.y - 59) / 20));
    else if ((screen === 'lobby' || screen === 'configuration') && point.y >= 90 && point.y < 109) index = point.x < 145 ? 0 : 1;
    if (index !== null) {
      setSelection(index);
      activate(index);
    }
    event.currentTarget.focus();
  }

  const status = screen === 'lobby' && ready ? 'WAITING FOR PEER' : 'DEMO BUILD';

  return (
    <main className="app-shell">
      <header className="device-header">
        <div>
          <p className="eyebrow">LOCAL LINK UTILITY</p>
          <h1>SwitchTrade</h1>
        </div>
        <div className="device-state" aria-label={`Application status: ${status}`}>
          <span className="status-light" />
          {status}
        </div>
      </header>

      <section className="console" aria-label="SwitchTrade application controls">
        <div className="screen-bezel">
          <div className="switchtrade-pixel-shell">
            <div className="switchtrade-pixel-viewport" data-scale="4">
              <canvas
                ref={canvasRef}
                className="switchtrade-pixel-canvas"
                width="240"
                height="160"
                role="application"
                aria-label={`SwitchTrade ${screen} screen. Selection ${selection + 1} of ${itemCount}.`}
                tabIndex={0}
                onKeyDown={onKeyDown}
                onPointerDown={onPointerDown}
              />
            </div>
          </div>
        </div>
        <footer className="control-strip">
          <span><kbd>↑</kbd><kbd>↓</kbd> Move</span>
          <span><kbd>Enter</kbd> Confirm</span>
          <span><kbd>Esc</kbd> Back</span>
        </footer>
      </section>
    </main>
  );
}
