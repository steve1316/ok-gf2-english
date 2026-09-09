# Global Client Tasks

## Overview

The task set for the **Global (Steam, English)** client. It is separate from the CN tasks documented
in [daily-tasks.md](daily-tasks.md) and [weekly-tasks.md](weekly-tasks.md), and matches the English
text on screen directly rather than translating it.

Pick which set you get in **Settings -> Region -> Game Client**. It defaults to `Global`, and the app
has to be restarted after changing it.

Game terms below use the wording from the Global / Steam client. See [../glossary.md](../glossary.md)
for the full mapping.

Global ships its own Loop automation, which the bot starts and then leaves to run. That is why this
task set is so much smaller than the CN one - most of the daily routine is the game's own job, and
these tasks cover what Loop does not.

---

## Global Daily

Runs each enabled step in order, starting from the home screen. Every step is a switch of its own.

| Setting | What it does |
|---|---|
| `Start Loop` | Opens the Dispatch Room and starts the in-game Loop automation, then waits for it to finish |
| `Claim Free Packs` | Claims the shop supply boxes that are currently free |
| `Run Event Supply` | Auto-battles the last Supply stage of each running event, spending as much Expenditure as it can |
| `Claim Boundary Push Rewards` | Collects the Breakthrough rewards under Commissions |
| `Crew Deck` | Visits Tea Time at the coffee machine, Delicious Cuisine at the kitchen, and optionally waters the flower |

`Crew Deck` walks to each station on a timer, and those timings depend on where your character
spawns, so the defaults are a starting guess rather than an answer. Measure your own - see
[Walk timings](#walk-timings).

All three stations are visited in a **single trip** into the deck. Every walk is timed from the
entrance, so after each station the bot walks back the way it came rather than leaving and coming in
again. If a walk does not land where it should, it backs out and re-enters to get back to a known
spot instead of guessing.

### Steps that stop early

Each step checks whether its work is already done before spending anything:

- **Claim Free Packs** only buys a box whose own dialog reads `Free` and shows no price. A paid pack
  opened by accident is cancelled rather than left blocking the shop.
- **Run Event Supply** reads the ticket count in the top-right of each event page and moves on if
  it is `0`, rather than walking the map to a stage it cannot run. A banner slot with no event behind
  it is reported and skipped the same way - see [Event banners](#event-banners).
- **Claim Boundary Push Rewards** reads the Breakthrough card's reward progress and stops if it is
  already complete.
- **Crew Deck** reads the buff icons in the corner of the deck the moment it arrives, so a station
  already used today costs a glance rather than the walk out to it, and it checks how many dishes are
  already in effect before cooking another. `Water Flower` is the exception - watering grants no buff,
  so there is nothing to read from the entrance and that one always costs its walk. It reads the
  counter under the `Water` button once it gets there and leaves the flower alone if it is already
  watered.

---

## Global Weekly

| Setting | What it does |
|---|---|
| `Claim Peak Value Rewards` | Collects the rewards from Peak Value Assessment. Does not fight anything |

Boss Fight and Expansion Drills are **not** included. Both need an English auto-battle routine, which
does not exist yet.

---

## Event banners

Events are opened from the banners stacked down the top-left of the home screen. Which banner holds
the event you want is not fixed - a new event can push an older one down, and two can run at once - so
one setting names the positions to open. It belongs to the `Run Event Supply` step and is ignored when
that step is switched off:

| Setting | What it means | Default |
|---|---|---|
| `Event Banner Slots` | Banner positions, counting from the top | `1` |

Count from the top banner, which is slot `1`. Write a single number for one event, or a comma-separated
list for two, up to slot `3`:

| Setting | What runs |
|---|---|
| `1` | The top banner only |
| `2` | The second banner only, when the event you want sits below another one |
| `1,2` | Both, top one first |
| `2,3` | The second and third banners, in that order |

Each slot is opened, run and returned from in turn, so two events each get their own ticket check and
spend their own Expenditure. A slot with no banner behind it logs `No event banner in slot N on the
home screen` and the run moves on to the next one.

Only the top banner's position is measured - the rest are stepped down from it, since every event
draws its own art and there is nothing fixed to recognise. If a slot reports no banner when one is
plainly there, that step is off for your resolution. The constants are `EVENT_BANNER` and
`BANNER_PITCH` in `src/global/GlobalDailyTask.py`.

### Events split into parts

Later events have no `Supply` button of their own. They divide into parts, one card each along the
bottom of the event page, and the bot opens the highest-numbered part that is not marked
`Not enabled`, then switches from the `Story` tab it lands on to `Supply`. Nothing needs setting for
this - it is picked up from the page.

---

## Walk timings

The Crew Deck is a walkable 3D area, so the bot reaches each station by holding movement keys for a
fixed time. Three settings hold those durations, nested under the `Crew Deck` toggle:

| Setting | Route | Default |
|---|---|---|
| `Tea Time Walk` | holds `A`, `W`, then `D` | `0.636-1.25-0.495` |
| `Delicious Cuisine Walk` | holds `S` | `0.747` |
| `Water Flower Walk` | holds `D`, `S`, then `D` | `0.95-1.03-3.08` |

The defaults came from one machine and one spawn point, so treat them as a starting guess. To measure
your own, run the recorder from the repository root:

```pwsh
python tools/record_walk.py
```

Switch to the game, walk from the Crew Deck entrance to the station by hand, then press Esc. It
prints the durations it timed, names the setting they belong to, and tells you if the route you
walked is not one the bot knows. Backspace clears a fluffed attempt without restarting it.

---

## Watering the flower

`Water Flower` is a fourth setting under `Crew Deck`, and it ships **switched off**. It needs a
one-time bit of setup you have to do by hand:

**Move the flower pot to the Hangar Passage.** It sits in the Armory Passage by default, and
`Water Flower Walk` is timed from the Hangar Passage. Leave the pot where it starts and the bot walks
into empty space, finds no prompt, and says so.

Once the pot has been moved and the setting is on, the bot walks to the pot, opens `Manage Flower`,
and presses `Water` if the day's watering has not been used. It never touches `Make Into Hairflower`,
which sits directly below `Manage Flower` in the same list and would harvest the flower instead.

---

## The `Run: ` tasks

Each of these runs exactly **one** step and nothing else, which is how you check a single flow
without sitting through the rest. They carry only the settings their own step reads - `Run: Event
Supply` keeps `Event Banner Slots`, `Run: Crew Deck` keeps the walk timings, and the rest take no
settings at all.

| Task | Runs |
|---|---|
| `Run: Go Home` | Opens Commissions and returns home. Changes nothing |
| `Run: Start Loop` | `Start Loop` |
| `Run: Claim Free Packs` | `Claim Free Packs` |
| `Run: Event Supply` | `Run Event Supply` |
| `Run: Claim Boundary Push` | `Claim Boundary Push Rewards` |
| `Run: Claim Peak Value` | `Claim Peak Value Rewards` |
| `Run: Crew Deck` | `Crew Deck` - makes the drink, cooks the dish, waters the flower |

Start with **`Run: Go Home`**. It buys nothing, fights nothing and spends nothing - it only proves the
bot can recognise the home screen and find its way back, which every other task depends on.

Each Crew Deck activity is once a day, so `Run: Crew Deck` spends the drink, the dish and the day's
watering every time. A walk that stops short of its station reports that it found no prompt, which is
what tells you a timing needs adjusting.

---

## Known gaps

- **`Claim Peak Value Rewards` has never been run against the game.** Its steps were written without
  seeing the reward screen, so expect it to fail at the claim button and save a frame under
  `debug_frames/`.
- **Boss Fight and Expansion Drills are missing**, as above.
- **The Wishlist is not automated.** Only the free supply boxes are claimed.

When a flow cannot make sense of a screen it saves that frame to `debug_frames/` and logs every line
of text it read. That folder is not cleared between runs, unlike `screenshots/`, so those frames are
what to attach to a bug report.
