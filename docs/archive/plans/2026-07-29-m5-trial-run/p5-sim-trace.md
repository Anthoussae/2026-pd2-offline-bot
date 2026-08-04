# P5 sim decision trace

ticks: 61
steps completed: town_preamble, waypoint, clear_radius, pickup, done
reflex fires: 13

## Engine log
- step town_preamble done: heal; repair; inventory; merc
- step waypoint done: arrived at (1000, 1000)
- reflex upkeep: combat-module upkeep
- reflex upkeep: combat-module upkeep
- reflex blood_warp: lost 350 hp within 2s
- reflex heal: hp 53% < 100%
- reflex upkeep: armor absorb 50% < 75%
- reflex upkeep: combat-module upkeep
- reflex upkeep: combat-module upkeep
- reflex upkeep: combat-module upkeep
- reflex upkeep: combat-module upkeep
- reflex upkeep: combat-module upkeep
- reflex upkeep: combat-module upkeep
- reflex heal: hp 93% < 100%
- reflex upkeep: combat-module upkeep
- step clear_radius done: clear for 5s
- step pickup done: nothing left to pick
- step done done: run complete

## Actions sent
- CastAtPoint  skill 83 verified, at (1000, 1004)
- MoveTo  to (1006, 1000)
- CastAtPoint  skill 83 verified, at (1010, 1000)
- AttackUnit  unit 1 at (1006, 1000)
- CastAtPoint  skill 367 verified, at (1003, 980)
- DrinkPotion  key 3 (healing)
- CastSelf  skill 68 verified, self-cast
- MoveTo  to (1001, 968)
- MoveTo  to (1003, 976)
- MoveTo  to (1005, 984)
- MoveTo  to (1007, 992)
- CastAtPoint  skill 95 verified, at (1006, 1000)
- CastAtPoint  skill 83 verified, at (1011, 992)
- MoveTo  to (1012, 1000)
- CastAtPoint  skill 83 verified, at (1016, 1000)
- AttackUnit  unit 4 at (1012, 1000)
- MoveTo  to (1020, 991)
- MoveTo  to (1014, 999)
- MoveTo  to (1010, 1004)
- CastAtPoint  skill 95 verified, at (1012, 1000)
- CastAtPoint  skill 83 verified, at (1014, 1004)
- AttackUnit  unit 2 at (1010, 1004)
- CastAtPoint  skill 83 verified, at (1014, 1004)
- MoveTo  to (1020, 997)
- MoveTo  to (1012, 1002)
- DrinkPotion  key 3 (healing)
- CastAtPoint  skill 95 verified, at (1010, 1004)
- MoveTo  to (1004, 1008)
- AttackUnit  unit 3 at (1004, 1008)
- MoveTo  to (1016, 1008)
- MoveTo  to (1006, 1000)
- PickUpItem  item 501 at (1006, 1000)
- PickUpItem  item 503 at (1010, 1004)
- MoveTo  to (1004, 1008)
- PickUpItem  item 504 at (1004, 1008)
- PickUpItem  item 504 at (1004, 1008)
- PickUpItem  item 504 at (1004, 1008)
- PickUpItem  item 504 at (1004, 1008)
- PickUpItem  item 504 at (1004, 1008)
- PickUpItem  item 504 at (1004, 1008)

## What the world did
- t0: town preamble (healed, inventory emptied)
- t1: waypoint to area 3
- t2: desecrate cast
- t4: desecrate cast
- t5: struck 1
- t6: took 350 damage, hp 650
- t6: blood warp to (1003, 980)
- t7: drank column 2 (hp 930, mana 350)
- t8: bone armor recast
- t9: monster 1 died of poison
- t10: accidentally picked up kind 700
- t13: revived 1 (1 up)
- t14: 1 monster(s) arrived
- t14: desecrate cast
- t16: desecrate cast
- t17: struck 4
- t21: monster 4 died of poison
- t21: revived 4 (2 up)
- t22: desecrate cast
- t23: struck 2
- t24: desecrate cast
- t27: monster 2 died of poison
- t27: drank column 2 (hp 1000, mana 145)
- t28: revived 2 (3 up)
- t30: struck 3
- t33: picked up kind 606
- t34: monster 3 died of poison
- t35: picked up kind 999
- t47: cleanse dropped 1 junk item(s)
- t58: cleanse dropped 0 junk item(s)

## Alerts raised
- INVENTORY FULL: item kind 997 at (1004, 1008) would not come up after 3 attempts. Skipping further non-potion pickups this game; the town preamble empties the inventory next game.
- INVENTORY FULL: item kind 997 at (1004, 1008) would not come up after 3 attempts. Skipping further non-potion pickups this game; the town preamble empties the inventory next game.
