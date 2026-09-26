# DSA Isolated Bundle v1 — recovery implementation

Status: **isolated engineering recovery candidate; not Production Authority**.

This file documents the replacement implementation created after the reported local-only
commit `bbf0f8c5230d12ee8cc256c61eafcc73831cf69d` could not be recovered from any durable
Git object store. This implementation is **not** claimed to be byte-identical to that lost
commit and receives a new Git commit identity.

## Purpose

`scripts/dsa_isolated_bundle_v1.py` composes existing accepted components without
re-implementing strategy logic:

`Formal Receipt Resolver -> Production Orchestrator -> Entry-v1 binding -> isolated journal replay`.

It does not call models, providers, brokers, or paid data sources. It does not create a
canonical journal, write Production state, switch a runtime pointer, or grant acceptance.

## Required identity inputs

A run must provide:

- exact 40-character code commit SHA;
- explicit input classification: `REAL`, `SYNTHETIC`, or `HISTORICAL_REPLAY`;
- target session, next session, execution clock, and verification clock;
- O/U formal inputs through the existing Resolver;
- Entry-v1 evidence file;
- an existing isolated copy of the canonical private journal;
- expected Git blob SHA-1 and canonical journal hash.

The journal identity is validated before orchestration. Empty journal initialization is
not a recovery mechanism and is not implemented here.

## Output and retry contract

Outputs are created under a caller-supplied directory and include:

- `bundle-spec.json`
- `resolver.json`
- `orchestrator.json` when both tracks are available
- `candidate-journal.json` and `replay.json` only when the existing orchestrator is replayable
- `bundle-receipt.json`
- `manifest.json`

The source journal bytes are compared before and after the run and must be unchanged.

A completed output directory is reusable only when its spec hash and every manifest file
hash match. An exact retry is a no-op. A changed spec or output-byte drift fails closed.

Interrupted work uses a sibling `.partial` directory. Compatible partial files may be
continued; conflicting bytes fail explicitly. An incomplete final directory is never
treated as complete.

## O/U independence

If either O or U is missing, the bundle returns `BLOCKED_INPUTS`. The available track's
identity and hash remain visible in the receipt; the missing track is not silently erased.
No aggregate completion is inferred from one available track.

## Natural-cycle boundary

Every bundle receipt sets:

- `formal_writes = 0`
- `production_pointer_switched = false`
- `real_orders = 0`
- `natural_cycle_credit = 0`
- `independent_factory_acceptance_required = true`

This is true for REAL, SYNTHETIC, and HISTORICAL_REPLAY inputs. A REAL-labelled engineering
bundle is still not a successful natural XHKG cycle. The separate Shadow real-cycle
acceptance contract remains authoritative for the required 5 genuine sessions.

## Example

```sh
python -m scripts.dsa_isolated_bundle_v1 \
  --root /isolated/repo \
  --target-session 2026-09-28 \
  --now 2026-09-28T09:31:00+08:00 \
  --next-session 2026-09-29 \
  --verification-clock 2026-09-28T09:32:00+08:00 \
  --entry-evidence /isolated/entry.json \
  --journal /isolated/canonical-journal-copy.json \
  --expected-blob <git-blob-sha1> \
  --expected-hash <canonical-journal-hash> \
  --out-dir /isolated/bundle-run-001 \
  --run-id DSA-BUNDLE-20260928-001 \
  --code-sha <exact-commit-sha> \
  --input-classification REAL
```

## Validation for this recovery

Targeted tests cover:

- complete isolated bundle creation without source mutation;
- exact retry no-op and byte preservation;
- spec drift rejection;
- compatible partial resume and incompatible partial rejection;
- missing-track visibility;
- SYNTHETIC/HISTORICAL_REPLAY zero natural-cycle credit;
- journal identity fail-closed;
- incomplete final directory rejection.

The recovery must additionally run existing Entry-v1, Orchestrator, Resolver, and Shadow
cycle acceptance regressions before durable delivery.

## Delivery rule

A local commit is not delivery. The recovery is deliverable only after the commit is
published to the existing Draft PR #5 branch and the remote commit plus all changed files
are independently read back and hashed. No main merge or Production promotion is part of
this recovery.