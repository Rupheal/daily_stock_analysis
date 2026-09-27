# DSA Foundation resource adapter

This adapter is a consumer of the Foundation Shared Resource Broker. It never
mints global claim, logical-cycle, or paid-quota authority.

Canonical Foundation inputs:
- `foundation.resource-claim-receipt/v1`
- `foundation.resource-claim-readback/v1`
- `foundation.quota-reservation-receipt/v1`
- `foundation.quota-reservation-readback/v1`

A signed/current Foundation proof is required at managed mutation boundaries.
Legacy/raw claim dictionaries may be parsed for diagnostics but remain
unverified and cannot authorize writes.

Global logical-cycle ownership belongs to Foundation. The SQLite `cycles`
table is host-local defense-in-depth only; an unproven schedule claim returns
`WAIT_FOUNDATION_GRANT` and never `EXECUTE`.

Global paid allowance/reservation authority also belongs to Foundation.
`configure_quota` and local `reserve_quota` are disabled. The adapter only
consumes/settles/releases/expires a verified Foundation reservation.

PR #6's `dsa-native-private-branch-writer` serialization remains enabled.
This change does not alter O/U model semantics, switch Production, call DC,
place orders, or add paid spend.
