---
name: Playbook validator card-id coverage
description: Any playbook section carrying card-id lists must be registered for validation or its ids are silently unchecked.
---

# Playbook validator card-id coverage

`validator._iter_card_ids()` only traverses a fixed set of locations: `cards.*`,
`roles.<ROLE_SECTIONS>`, plus the `(section, key)` pairs listed in
`schema.CARD_ID_LIST_FIELDS` (e.g. `discard_safety.prefer_discard`,
`discard_safety.never_discard_only`).

**Why:** A playbook can embed real card ids in sections beyond cards/roles (discard
safety lists). If a section is not registered, its ids are never checked against the
confirmed set / deck — invented or wrong ids pass validation silently.

**How to apply:** When you add a new playbook field that holds card-id lists, add its
`(section, key)` to `schema.CARD_ID_LIST_FIELDS`. The validator picks it up
automatically. Never invent card ids — confirm against `data/cards/EN_Card_Data.csv`.
