---
type: llm
---
PASS if the reply sets the project up with a project profile (.metaloop/project.json) made from the presets for Node
with PostgreSQL (for example init_project.py --stack node --db postgres), says to fill in what the preset marks FILL IN
(such as how the app starts or how its test data is seeded) and commit the file, and then says to create a run and run
the doctor. It is correct for MetaLoop to run its own PostgreSQL instances (in Docker or native) for the gate and the
verify loop instead of the project's docker-compose one, and to suggest adjusting the profile to match the project.

FAIL if it tells the user to edit the kit's own scripts for their stack, or uses a stack preset other than node, or a
database other than PostgreSQL.
