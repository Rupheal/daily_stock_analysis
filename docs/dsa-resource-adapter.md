# DSA Foundation resource adapter

The DSA adapter consumes grants from the Foundation Shared Resource Broker. It
does not implement a second broker, switch Production, place orders, call the
physical Shadow/DC runtime, or create paid usage. The machine-readable contract
is `docs/runtime/DSA_RESOURCE_ADAPTER_MANIFEST_V1.json`.

Every mutation supplies `resource_id`, `claim_id`, `run_id`, and a positive
`fencing_epoch`. Durable state rejects an older epoch. Logical daily work is
single-flight by `target_session + track + contract_hash`; duplicate transports
attach/wait or return the completed receipt instead of repeating side effects.

O and U computation remains parallel and produces immutable receipts. One
serialized projection writer advances `LATEST` only by `(target_session,
generation)` and retains delayed older receipts. Git branch publication verifies
the observed base and expected tree, performs a non-force fast-forward push, and
reads the ref back. A collision must re-read and reconcile.

Drive artifacts remain immutable. An ambiguous POST is never blindly retried:
the caller repeats the artifact-ID lookup and accepts only an exact hash/run
match; duplicates or mismatches fail closed. Simulation journals additionally
retain parent-hash, same-count, fork, immutable snapshot, and readback guards.

Quota reservations use exact decimal units and support reserve, consume,
release, and expire. This adapter does not make provider calls; a Foundation
reservation is a prerequisite rather than permission to auto-recharge.

Rollback is a revert of the adapter commit. Existing immutable evidence and
journal history must not be deleted or rewritten; disable new claim issuance
and leave PR #6 workflow serialization enabled while reverting.
