# 0021. Salt rotation and epochs: the replacement machine starts a new epoch; a recovered home stays a separate one

Date: 2026-11-05
Status: accepted

## Context

The only data home Caliper ever had became unavailable: the machine holding
`~/.caliper` — the salt, every extracted and derived record, the content
sidecars accumulating since 2026-08-24, and the scheduled collection job —
suffered hardware damage. Recovery outcome unknown; soldered storage often
does not come back.

Two facts about the design make this a decision rather than an operational
hiccup:

1. **Every reportable identifier is salted.** `project_ref`, `repo_ref`,
   `file_ref` and `top_dir_ref` are `sha256(salt | raw)` (ADR-0004, ADR-0012).
   Records hashed under two different salts never join — the ref-join
   contract the trace layer rests on (ADR-0019) holds only within one salt.
   `cli/paths.py` creates a fresh salt on a machine's first run and never
   rewrites it.
2. **Collection cannot wait.** Claude Code deletes session logs at
   `cleanupPeriodDays` (ADR-0011 postscript); a replacement machine that
   waits for recovery before extracting loses whatever rotates meanwhile.

So the replacement machine either starts collecting now under a salt that
cannot join the old history, or it waits and loses data. ADR-0012's
migration already refuses a both-populated target rather than guessing, but
nothing said what the rule is when two legitimate homes exist.

## Decision

**1. Rotate; do not wait.** The replacement machine ran its first extraction
on 2026-11-05 under a new salt. The set of records hashed under one salt is
an **epoch**. Joins, aggregates and trace edges are valid only within an
epoch; the schemas need no change because no record ever carried the salt
itself — the epoch is a property of a data home, not of a record.

**2. A recovered home is a separate epoch, never merged.** If the old
`~/.caliper` comes back, it is kept intact under its own salt beside the live
home (concretely: as its own tree, e.g. `~/.caliper-epoch-2026-08/`, readable
by pointing `CALIPER_HOME` at it). It is never re-hashed under the new salt
and never merged into the new tree. A report or serve view renders one
epoch and, where another epoch exists, says so and reports the cross-epoch
join as **absent — not attempted, not approximated**. Absent is not zero
applies to epochs exactly as it applies to a Cursor session's tokens.
Multi-epoch reading (one view that states two epochs' figures side by side,
unjoined) is scoped here as future work; today each epoch is read by setting
`CALIPER_HOME`.

**3. The restore-path gap, stated precisely.** Caliper has no export or
restore path. Copying `~/.caliper` to another machine restores it only onto
an *empty* home — that works today and is the one backup story that exists.
Once a second home has been populated there is no merge path: two salts
never join, and `cli/paths.py` refuses a both-populated migration rather
than guessing (ADR-0012). **Salt-preserving export/import is the missing
feature.** Until it exists the honest advice is: back up `~/.caliper`
(the salt above all — it is the one file nothing can regenerate) before a
machine is lost, not after.

## Consequences

- PROGRESS.md carries one status line pointing here; the rules live here.
- Every figure PROGRESS.md cites from the lost epoch is marked *not
  re-derivable* individually. Git signals are unaffected (they recompute
  from repos that still exist) and so is every frozen record under
  `data/evidence/` — ADR-0007, 0008, 0009 and 0013 stand.
- This loss is a real-world instance of ADR-0011's own premise: a
  collection gap loses data permanently and backfill is lossy by
  construction. The scheduler cannot help when the disk itself is the
  failure; export/import is the layer that would have.
- Revisit when: the old home is recovered (apply Decision 2 and record the
  outcome in a postscript), or when a second user needs to move machines
  (build Decision 3's export/import).
