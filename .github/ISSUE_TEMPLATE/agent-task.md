---
name: Agent task
about: One vertical slice, 30–90 min of agent work
labels: ''
---

## Goal
One sentence: what the user can do after this is merged.

## Context
SPEC.md § … · related: #…

## Files / area
- area: fe | be | infra | demo
- touch only: `src/...`
- do NOT touch: `contracts/` (unless labeled `contract`)

## Acceptance criteria (checkable by running something)
- [ ] `curl -X POST localhost:8000/api/... -d '{...}'` returns `{...}`
- [ ] On `/page`, clicking **X** shows **Y**
- [ ] Lint passes

## Out of scope
- ...
