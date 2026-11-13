---
type: llm
---
PASS if the reply proposes running this as a structured loop with distinct phases (for example: verify or
investigate, plan with sign-off, parallel fixes on separate branches, review and merge) and says where the owner
decides (the plan, design or schema sign-offs, review items, merges).
FAIL if it simply starts fixing, or offers only a generic to-do list with no owner gates.
