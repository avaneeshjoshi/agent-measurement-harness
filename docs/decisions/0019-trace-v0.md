# 0019. Trace layer v0: ticket and commit edges, file-overlap matching

Date: 2026-09-01
Status: accepted

## Context

`trace_event.schema.json` has existed since the contracts were drafted — the
chain session → commit/PR → ticket/initiative → deployment → outcome, one edge
per record, confidence on every edge — with zero producers and zero records
(`harness/trace/` was a design README). Meanwhile two open questions need
exactly this data:

- **ADR-0002's unit question** (prompt vs segment vs session vs something
  larger) has been argued, not measured. A chain-rate — what fraction of
  sessions observably connect to commits, and commits to tickets — turns it
  empirical.
- **ADR-0006 finding 5** flagged session→commit joining as follow-up work, and
  serve's session detail page still labels nearby commits "temporal proximity,
  not attribution" because no attribution record exists.

A design constraint taken as input: real-world agent work lands as **many
small chunked commits per feature**, not one feature commit — so one session
legitimately produces many commits, and any matcher that assumes 1:1 is wrong
from the start.

## Decision

Three edge producers in `harness/trace/tracer.py` (`tracer-0.1.0`), run by
`caliper trace`, writing `<data>/trace/trace_events.jsonl` plus a run manifest.
Read-only over sources (git access is `log`/`rev-parse` only; the store is the
single write). No-match is absence: no edge, never a placeholder.

**1. commit → ticket** (`explicit_id_reference`, `known`). Ticket keys are
extracted from commit messages by a versioned regex,
`\b([A-Z][A-Z0-9]{1,9})-([0-9]{1,6})\b`, minus a prefix blocklist
(`UTF`, `ISO`, `SHA`, `MD`, `CRC`, `AES`, `RSA`, `TLS`, `SSL`, `RFC`, `CVE`,
`PEP`, `ADR`, `HTTP`, `HTTP2`, `API`, `ID`, `UUID`, `GUID`, `CI`, `RC`, `V`,
`X`, `UTC`, `GMT`, `ANSI`, `IEEE`, `OAUTH`, `BASE`, `ES`, `IPV`) that removes
key-shaped strings that are not ticket systems — without it, this repo's own
"ADR-0018" references would become ticket edges. The blocklist is versioned in
the module and extended only with a postscript here. Precedent for storing an
extracted identifier in the clear: `change_ref.pr_number` (ADR-0006);
`docs/conventions.md` scopes hashing to paths and org identity, and the schema
itself names "ticket key in commit/PR" as intended content-free evidence.

**2. session → ticket** (`branch_name_match`, `inferred`) from the same
extraction over `session.git_branch`, which is already stored in the clear.

**3. session → commit** (`file_overlap`, new enum value — see schema change):
**file-ref overlap is the mechanism; time is a tiebreaker only.** Timestamp
correlation as a primary method would require inventing an unvalidated slack
constant; deliberately refused.

- Session side: the union of `prompt_unit.files_edited[].file_ref` (salted
  hashes of absolute paths). Commit side: `git log --numstat` paths, hashed as
  `repo_root + "/" + relpath` with the same never-rewritten salt (ADR-0012) —
  the **ref-join contract**, pinned by a test that fails loudly if either side
  changes its path form.
- Candidates are scoped by the `project_ref` join (validated in ADR-0006) and
  a causality constraint — a session cannot produce a commit authored before
  it began. That is a direction check, not a clock window.
- Specificity scales confidence, per the chunked-commit reality (commit-side
  containment, so a small chunk fully inside a session's larger edit set
  scores high): full containment of ≥2 files → `inferred` 0.85; full
  containment of a single file → `inferred` 0.6 if that file appears in only
  that one commit, else `speculative` 0.25 (two things touching `main.py` in a
  small repo is weak evidence); partial containment ≥ 0.5 → `speculative`
  0.4 × containment; below 0.5 → no edge.
- One edge per commit, to the best-scoring candidate session; ties break to
  the session whose window sits closest before `authored_at` (then
  session_id, for determinism). The evidence string records the overlap
  fraction and the candidate count.

**Schema change:** `trace_event` 0.1.0 → 0.2.0, widening — `file_overlap`
added to the `link.method` enum, ranked between `vendor_tracking` and
`branch_name_match`. Labeling the mechanism `timestamp_correlation` would have
misdescribed it, which is exactly what the method field exists to prevent.

**Store:** one record per edge identity (trace_id, from, to, method);
re-runs over unchanged inputs keep existing records byte-for-byte
(`created_at` is the only per-run stamp and is excluded from equality).
`trace_id` anchors chains: commit-linked edges share `repo_ref:sha`;
branch-derived session→ticket edges use `s:session_id`.

**Surface (chain-rate):** `caliper trace` prints the fraction of commits with
a ticket edge, of repo-scoped sessions with a commit edge (by confidence
class), and of sessions with a branch ticket key — each with its n. Low rates
are a finding: they map where the chain breaks.

## First live run (2026-09-01, this machine)

289 commits, 313 sessions (86 repo-scoped with file refs): **0/289 commits
carry a ticket key, 0/313 branches carry one** — solo repos don't use ticket
systems; this is the honest baseline an enterprise deployment would be
compared against, not a failure. **12/86 repo-scoped sessions matched commits
by file overlap — 132 edges (23 inferred, 109 speculative)**: the matcher
works on real data, one session maps to many commits exactly as the
chunked-commit input predicted, and the speculative majority is single-common-
file matches that consumers can exclude (the schema's stated purpose for the
class).

## Consequences

- The ADR-0002 unit question is now measurable: chain-rate by method and
  class, instead of argument.
- serve's "temporal proximity, not attribution" label can eventually be
  replaced by real edges whose weakness is visible on the record; until a
  consumer ships, the label stands.
- **Collection boundary, recorded:** autonomous/CI/cloud agent sessions are
  not ingested — every connector reads local files, so end-to-end autonomous
  traffic is `not_yet_measurable` (the 193 `sdk`-origin prompts in
  `prompt_source_counts` are the only incidental cloud tracer). Building cloud
  ingestion is deliberately out of scope here.
- **Known limits, recorded not patched:** codex hashes patch-output paths as
  the log reports them (typically repo-relative), so codex ref-joins are
  expected to miss until measured and addressed — the ref-join contract is
  claude_code-first; numstat/blame don't follow renames (ADR-0006 limitation,
  inherited); files edited outside the repo never match; the scoring
  thresholds (0.85/0.6/0.25, the 0.5 floor) are v0 judgment calls, disclosed
  here, to be revisited only with labeled data and a postscript — not tuned
  against the numbers they produce.
- If file overlap proves too weak on richer data, that result gets reported
  (the chain-rate by class shows it directly) — the explicit alternative,
  falling back to a clock window, stays refused without a new ADR.
