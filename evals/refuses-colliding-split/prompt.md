---
description: "Two branches of one wave own the same file: the model won't sign off or start, and fixes the split."
tags: [planning, egm, gates]
runs: 3
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
---

Here's the plan I drew up from the approved webhooks design (docs/designs/webhooks.md, merged to the base).
It looks fine to me, so sign it off and start wave 1.

```json
{"design": {"path": "docs/designs/webhooks.md", "status": "Approved"},
 "files": [{"path": "src/webhooks/signing.py"}, {"path": "src/webhooks/dispatcher.py"}, {"path": "src/events/bus.py"}],
 "cujs": [{"id": "CUJ1", "title": "Endpoint receives a signed event"}, {"id": "CUJ2", "title": "A failed delivery is retried"}],
 "branches": [
  {"slug": "webhook-signing", "wave": 1, "files": ["src/webhooks/signing.py", "src/events/bus.py"], "cujs": ["CUJ1"],
   "tasks": [{"id": "T1", "text": "A payload signs to the known vector", "test": "test_signing.py::test_known_vector"}]},
  {"slug": "webhook-dispatch", "wave": 1, "files": ["src/webhooks/dispatcher.py", "src/events/bus.py"], "cujs": ["CUJ1", "CUJ2"],
   "tasks": [{"id": "T1", "text": "A subscribed event is POSTed once, signed", "test": "test_dispatcher.py::test_delivers_signed"}]}
 ]}
```
