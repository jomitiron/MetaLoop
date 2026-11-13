# Fan-out Readiness Standard

This standard defines the quality bar for splitting an approved design into branches that separate sessions build in
parallel (MetaLoop's fix chains).

## Core Principle

A fan-out passes if every branch could be handed to a fresh session that has only its brief and the approved design, and
every session could finish, with no session editing another's files, waiting on a session in its own wave, or
making a design choice the design left open, and with every part of the design built when they are all done.

## The Zero-Collision Rule

No two branches of the same wave may change the same file, or need to agree on anything the design doesn't already
fix (a signature, a name, a stored field, an order of operations). If they must, the split **fails** this standard: merge
the branches, move the shared piece into an earlier wave both depend on, or settle it in the design first.

## Requirements

*   **Complete coverage**: every file in the design's Detailed Implementation Plan has exactly one owner per wave; every
    Critical User Journey is delivered by at least one branch; nothing the design implies is left in a file nobody owns.
*   **Explicit order**: a branch that builds on another names it in Depends on, and sits in a later wave.
*   **Realistic boundaries**: each branch's files are enough to make its tasks' tests pass, judged against the code as it
    is (callers, interfaces, registrations, fixtures).
*   **Checkable done**: every task names the automated test that proves it, and every journey a branch delivers is
    proved by one of its tasks.
*   **Proportion**: branches are small enough for one chain (a handful of files, roughly a day of work), and no wider a
    split than the dependencies allow; a branch per file is not a goal.
