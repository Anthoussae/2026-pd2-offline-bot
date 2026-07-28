# M1 spike log — Python perception + input vs live PD2 client

Machine: the Windows/PD2 box. Session date: 2026-07-28.
Phase file: [01-perception-input-spike.md](01-perception-input-spike.md).

## Environment

- Pre-existing Python 3.8.2 (64-bit, `C:\Python38`) — used for the spike.
  Python 3.12.10 installed via winget in parallel for the real project
  (slow download; the spike did not wait for it).
- venv at `spike/.venv38`, **pymem 1.14.0**.
- BH headers fetched from Project-Diablo-2/BH @ main on 2026-07-28
  (repo last pushed 2026-07-14 → current for Season 13).

## Offset derivation (citations)

| Value | Source | Detail |
|---|---|---|
| Player unit ptr | D2Ptrs.h:235 | `VARPTR(D2CLIENT, PlayerUnit, UnitAny*, 0x11BBFC, 0x11D050)`; macro (D2Ptrs.h:82-89) indexes `._113c` first → **0x11BBFC** for PD2's 1.13c. **Verified correct empirically.** |
| UnitAny.pPlayerData | D2Structs.h:698-703 | +0x14 (union) ✓ |
| UnitAny.dwAct | D2Structs.h:704 | +0x18 (0-based; +1 for display) ✓ |
| UnitAny.pPath | D2Structs.h:708-713 | +0x2C (union) ✓ |
| UnitAny.pStats | D2Structs.h:726 | +0x5C ✓ |
| PlayerData.szName | D2Structs.h:214 | +0x00, char[16] ✓ |
| Path.xPos / yPos | D2Structs.h:398,400 | +0x02 / +0x06 (WORD world coords) ✓ |
| StatList base list | D2Structs.h:442-443 | +0x24 `Stat[]`, +0x28 count — **base stats only, do not use** |
| StatList full list | D2Structs.h:452-453 | +0x48 `pSetStat[]`, +0x4C count — **the merged list incl. item/skill bonuses; this is the correct source** |
| Stat indices | empirical | 0=str 1=energy 2=dex 3=vit 6=hp 7=maxhp 8=mana 9=maxmana 10=stamina 11=maxstamina 12=level 13=exp 14=gold 15=goldbank |
| Fixed-point stats | empirical | **only** hp/maxhp/mana/maxmana/stamina/maxstamina need `>>8`; attributes, level, gold, experience are plain integers |

## Steps taken and results

1. **Attach.** `pymem.Pymem("Game.exe")` initially failed:
   `CouldNotOpenProcess`. Cause: **PD2 runs elevated**; our shell did
   not (`Path`/`Owner`/`CommandLine` of Game.exe all masked = higher
   integrity process). **Fix: run the Python process as Administrator**
   (UAC). Not a code problem — an operating requirement, and it belongs
   in the manual (M7).
2. **Module enumeration (elevated): works.** 115 modules; 64-bit Python
   reads the 32-bit client without trouble (no 32-bit Python needed —
   phase-file fallback not required). Confirmed the **real PD2 client**
   is what we attach to: `ProjectDiablo.dll` (0x10000000), `PD2_EXT.dll`,
   `BH.dll` all loaded alongside `D2CLIENT.dll` @ 0x6FAB0000.
3. **State read: correct.**
   `name='MaqiuDoubing' lvl=91 act=1 pos=(12622,5095)` — matches the
   live character.
   - **Stat bug caught by the user**: first read gave `hp=955/920`
     (current > max, implausible). Cause: D2 keeps *two* stat arrays on
     the StatList — the base array (0x24) holds pre-gear values, the
     full array (`pSetStat`, 0x48) holds the computed totals. Dumping
     both settled it:
     base `hp=961/920 mana=378/213 str=105` vs
     full `hp=961/1141 mana=378/378 str=122`. Only the full list is
     coherent. **Use the full list.**
   - Second bug exposed by the same dump: only hp/mana/stamina are
     fixed-point; applying `>>8` to attributes/level/gold zeroed them.
4. **Window geometry**: `'Diablo II'` hwnd, client 1536x864 at screen
   (0,0); centre (768,432). Windowed, borderless.
5. **Synthetic input: works — with an important incident.**
   `SendInput` click at (928,392) was delivered to the game, but the
   game had the **ESC menu open**, so the click activated
   **"Save and Exit Game"**: player unit went NULL and
   `MaqiuDoubing.d2s` + `pd2_shared.stash` were written at 00:42:37
   (timestamps confirm). No data loss — a normal save-and-exit — but
   the *movement* test did not happen.
   - The probe's foreground guard worked (it verified the game window
     was frontmost before clicking); what was missing is a **UI-state**
     guard.

## Findings

- **Both pillars are proven**: out-of-process reads return correct live
  values and track movement in real time; synthetic input reaches the
  client and moves the character.
- **Verify derived values against reality, not just against plausible
  structure.** The HP bug looked fine structurally (the offsets *were*
  right) but was semantically wrong — caught only because a human
  noticed `955/920` was impossible. Perception work in M2 needs
  cross-checks against what the game displays.
- **Elevation is mandatory** for perception (and therefore for the bot
  as a whole). Document in the manual; consider a friendly error when
  the bot is started unelevated.
- **UI state must gate every input.** This is the spike's most valuable
  finding: the same screen coordinate means different things depending
  on which panel is open. BH's `Constants.h:65-89` defines the UI enum
  (`UI_GAME 0x00`, `UI_ESCMENU_MAIN 0x09`, `UI_NPCSHOP 0x0C`,
  `UI_WPMENU 0x14`, …) and `D2Ptrs.h:156` exposes `GetUiVar_I`, but as
  a *function*, not a readable variable — locating the underlying UI
  array (or another readable indicator) is **an M2 task**, and it is a
  precondition for any input in M4/M5.
- Reading is safe and passive; **writing input is the dangerous half**,
  and it needs its own preconditions layer before the bot acts
  unattended.

6. **Re-test after the user re-entered the game** (Rogue Encampment,
   no menu open — verified by screen capture before sending input; this
   screenshot-then-act pattern is a cheap safety check worth keeping
   while UI-state detection is missing).
   Click at screen (250,550) on open ground:
   ```
   before: pos=(5866, 5742)   click target=(250,550)
     pos=(5864, 5743) -> (5863, 5744) -> (5862, 5746) -> ...
   after:  pos=(5862, 5757)   moved=YES
   ```
   Character walked; position tracked the walk smoothly at 10 Hz.

## Tier reached

- **T0** ✓ attach + module enumeration.
- **T1** ✓ static reads correct (name, level, act, stats).
- **T2** ✓ dynamic reads track live movement at 10 Hz.
- **T3** ✓ synthetic click moves the character.

**Spike passes** (T2 + T3 = both pillars proven).

## Recommendation

Proceed to M2 planning — nothing found here undermines plan B; the
architecture is validated where it matters (offsets from BH are correct
for the live S13 client, pymem is sufficient, input reaches the game).
Carry three requirements forward:

1. M2 must find a readable **UI-state** indicator (and in-game vs menu
   detection generally) before any input work lands.
2. The bot requires **Administrator** — manual + startup check.
3. Input layer (M3) should refuse to act unless: game window
   foreground **and** `UI_GAME` **and** player unit non-NULL.
