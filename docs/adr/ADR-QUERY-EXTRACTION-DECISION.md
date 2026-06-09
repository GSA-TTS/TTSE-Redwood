---
status: proposed
date: 2026-06-08
decision-makers: ["Heman", "Siva"]
approvers: ["Mateus"]
---

# ADR: Decision for Sender Query Extraction

## Why we need this
We want to add database query extraction to the sender side without changing the existing file transfer flow.

## What stays unchanged
- Policy check
- Compression
- Manifest creation
- Staging and transfer

Only the input step changes: source file mode or query extraction mode.

## Options considered
- Ibis as primary extraction library
- ConnectorX as primary extraction library
- Both from day one

## Decision
Use Ibis as the primary path now.

Keep ConnectorX as an optional optimization path later for very large extracts.

## Why this decision
- We need cross-database consistency more than max raw speed right now.
- Ibis gives better portability and less database-specific branching.
- Existing transfer flow remains intact, reducing rollout risk.

## How it works together
- Sender-side query inputs are provided by sender-controlled configuration.
- Ibis runs the query and writes a data file.
- Existing transfer steps process that file exactly as today.
- ConnectorX can be added later behind a threshold/feature flag.

## Revisit triggers
Revisit this decision if:
- Large extracts repeatedly miss performance targets.
- Ibis introduces unexpected complexity for key databases.

## Next planning items
- Implement adapter selector (file mode vs query mode).
- Implement sender query spec validation.
- Implement Ibis extraction adapter.
- Add logging, audit events, and runtime controls.
- Add tests for unchanged file flow and new query flow.
