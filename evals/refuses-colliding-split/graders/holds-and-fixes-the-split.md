---
type: llm
---
PASS if the reply does not sign the plan off or start wave 1 as it stands; says src/events/bus.py is owned by two
branches of the same wave, which run at the same time; and proposes a fix (give the file one owner, or move one
branch to a later wave that depends on the other, or merge the two branches) that then goes back for sign-off.
FAIL if it signs off, writes briefs or starts the wave, or misses that both branches change bus.py.
