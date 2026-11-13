---
description: "Setting up a Node + Postgres repo uses the matching presets, not another stack."
tags: [setup, stack]
runs: 3
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
---

Before we start using the loop on this repo: it's a Node/Express API with npm and Jest, and Postgres for the
database (docker-compose runs it for local dev). How do I set it up for this project?
