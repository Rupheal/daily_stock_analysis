# DSA evidence chain and research candidates v1

Status: isolated engineering candidate. Natural cycles remain 0/5. No workflow,
Production pointer, formal writer, accepted Authority or historical receipt is changed.
The existing Entry-v1 and timing rules remain in force. Explicit opt-in arguments
below connect these modules to existing entrypoints; live schedulers do not enable them.

## Producer publication and consumer observation

Actual call paths:

- `dsa_daily_o_production_v1.py --delivery-root <isolated-store>`: existing O
  production saves O_FORMAL, records generation observation, then publishes those bytes.
- `dsa_daily_u_production_v1.py --delivery-root <isolated-store>`: existing U
  production saves SANITIZED_U_FORMAL_RESULT, records generation observation, then publishes.
- `dsa_formal_receipt_resolver_v1.py --delivery-spec <map.json>`: observes and
  verifies explicitly pinned publications before existing receipt selection.
- `dsa_formal_timing_seal_v1.py` with all four chain arguments below verifies
  supplied event ordering before the existing candidate timing seal. Sealed candidates
  are then eligible for the existing Resolver/Orchestrator/Entry-v1 checks, not exempt
  from them. This release does not activate an end-to-end live early-morning workflow.

Independent file-store transport entrypoints (no model or network calls):

```sh
python -m scripts.dsa_receipt_delivery_v1 publish --receipt /isolated/source/receipt.json --generation /isolated/source/generation.json --root /isolated/store
python -m scripts.dsa_receipt_delivery_v1 consume --directory /isolated/store/<receipt-sha256> --sha256 <receipt-sha256> --observation /isolated/consumer/observation.json
```

Resolver delivery spec is an object with optional O and U keys. Each value contains
`directory`, exact `sha256`, and separate `observation` path. Unspecified tracks retain
the existing resolver behavior. Publication/observation is not formal acceptance.

Generation evidence contains account O/U, target_session, receipt_sha256 and
`generation_observed_at`; the existing generation recorder produces it. Generation
observation is not historical publication or first availability. `publication.json`
records the post-publication observation, location, receipt and generation hashes.
`first_publication_at` remains null. A crash after rename can only establish a later
recovery observation. Consumer evidence records the time bytes were actually read,
publication hash and raw receipt hash. An identical retry preserves its first observation.
Use a new observation path for a genuinely different consumer attempt.

The chain-enabled timing seal requires `--delivery`, `--consumer`, `--acceptance`,
and `--acceptance-sha` together, in addition to its existing `--receipt`,
`--timing-evidence`, `--now`, and `--out` arguments. External acceptance JSON must contain:

- accepted=true and a nonempty authority_reference;
- account and target_session matching generation;
- raw receipt_sha256 and consumer_sha256;
- accepted_at and frozen_at with time zones.

The caller must retrieve and authenticate that acceptance through the existing
formal Authority mechanism. A hash pins bytes; it does not authenticate the issuer.
This module **never creates or authenticates formal acceptance**. Its return flags
say so. Synthetic tests supply fictional acceptance and cannot serve as that mechanism.

Timing evidence keeps the existing four fields and their source references. The
available_at evidence hash must equal the consumer observation file hash, and its
value equals that observation time: a conservative candidate availability boundary,
not a claim of earliest global availability. The chain requires
cutoff <= generation observation <= publication observation <= consumer observation
<= external acceptance <= freeze <= explicit validation clock. Morning cutoff,
consumer observation, acceptance and freeze must be on decision_session, by 09:25 HKT.
Existing XHKG/valid_until/next_session/Entry rules still apply. market_data_session
remains separate from decision_session. No file mtime or current clock backfills history.

Sealing adds metadata and therefore changes receipt bytes. The return value pins
source_receipt_sha256, timing_evidence_sha256 and output sha256 separately; it declares
`sealed_bytes_publication_verified=false`. Publication of the sealed artifact and
its formal acceptance are separate outstanding evidence, not inherited from the raw
receipt. Running the legacy seal without chain arguments does not prove this chain.

The file store uses content-addressed staging, immutable file writes and directory
rename. Partial matching stages can resume; mismatches and changed outputs fail.
This is a same-filesystem isolated/shared-directory adapter, not GitHub/Drive delivery.
Thread-level atomic-write and simulated interruption tests are included. Real process
kill, power-loss durability, Windows filesystem and remote transport remain unverified.

## Official-list effective-date reconciliation

Existing snapshot CLI adds `--effective-evidence /isolated/proof.json`. It downloads
its existing public source set and invokes freeze -> normalized reconciliation ->
existing identity/type/exclusion checks. Only O_UNIVERSE_CANDIDATE.json,
U_UNIVERSE_CANDIDATE.json and candidate SNAPSHOT_STATUS.json are emitted. R0 proof
cannot be combined with this path, and identity failure cannot silently fall back to R0.
No formal freeze, historical list or live denominator is overwritten.

Proof JSON fields:

- target_session, timezone-aware cutoff, source_archive relative to the proof directory;
- channels with exactly SSE and SZSE;
- each channel: list_update_date, base_effective_session, covered_through_session,
  baseline_evidence, coverage_evidence, service_calendar, amendments;
- every source reference: relative file, sha256, https url, observed_at;
- service_calendar: source reference, covered_from, covered_through, sorted unique sessions;
- amendment: unique id, published_at, effective_rule (EXPLICIT_DATE or NEXT_SERVICE_DAY),
  effective_session, source reference, ordered changes;
- each change: five-digit code, action ADD/REMOVE/SELL_ONLY/REPLACE_IDENTITY; ADD and
  replacement carry row in the existing channel format; replacement also carries exact before.

Baseline evidence must match the actual downloaded source bytes and list date label.
Coverage must span baseline through target. NEXT_SERVICE_DAY uses the next declared
Southbound service day after Hong Kong publication date, not the next XHKG trading day.
Removed/sell-only status is recorded per channel; another channel's valid membership
is not silently deleted. Unknown actions/flags, missing intervals, duplicate amendments,
identity conflicts and source-byte drift fail closed.

`tests/test_dsa_effective_membership_v1.py` contains a complete **synthetic** normalized
proof and snapshot integration fixture. It is a shape example, never official evidence.
The code validates internal consistency and hashes; it cannot establish that source
extraction or announcement search coverage is semantically complete. Outputs explicitly
mark both independent checks false. Current real evidence still lacks a complete SZSE
amendment-coverage proof. SSE next-service-day evidence alone cannot establish the union.
Actual public notices must be archived and normalized with review before real candidate use.

## U observable input matrix and offline comparison

`dsa-u-observable-input-contract-v1.json` defines research candidate A-G inputs,
source classes, units, frequencies, timestamp requirements, missing handling and
verification methods. Source entry URLs are navigation only, not proof of free data
entitlement or historical point-in-time availability. Unverified endpoints are null.
No new data provider, paid retrieval, automated calibration or business default is enabled.
Investor identity remains unavailable; prices, volume and Southbound totals do not infer it.
The existing formal U identity/weights/threshold/capital gates remain unchanged.

```sh
python -m scripts.dsa_u_observable_candidate_v1 --input /isolated/input.json --contract docs/runtime/dsa-u-observable-input-contract-v1.json --config /isolated/research-config.json --out /isolated/research-result.json
```

Input: cutoff and observations array. Each observation has field, value, unit,
evidence_class (direct or derived_verified), source {url,sha256}, event_time,
published_at, available_at, observed_at, and derivation_inputs when derived.
All times include zones; event <= published <= available <= observed <= cutoff.

Configuration: status=RESEARCH_ONLY_NOT_AUTHORITY, training_end <= frozen_at < cutoff,
training_dataset_sha256, training_receipt_sha256, weights for all A-G summing to one,
max_age_seconds by required field, and normalization by field {mean,std,direction}.
std is positive; direction is integer +1/-1. These are supplied frozen **research**
parameters, not calibrated or authoritative defaults. The tool validates references
and ordering but does not retrieve source bytes or recompute training statistics.

Complete inputs produce standardized per-engine values and compare an equal-weight
baseline, supplied frozen weights, and leave-one-engine-out sensitivity. These are
scores, not performance estimates or trading instructions. Missing, stale, future,
inferred, nonfinite or incompatible required data causes ABSTAIN with per-engine
reasons; no zero imputation or partial aggregate. Formal regime and capital remain null.
The synthetic test fixture supplies hypothetical values to exercise behavior, not
empirical efficacy. Real PIT archives, verified derivation methods, training provenance
and out-of-sample evaluation remain prerequisites to any policy proposal.

## Validation and rollback

Run the three new test modules plus affected Entry/timing/generation/resolver/snapshot
regressions. Dependency failures must be distinguished from test failures. No full
model environment or paid source is required. Separate Codex bundle files are unchanged.

Rollback this candidate commit on the repair branch. Its opt-in outputs are isolated;
no formal ledger or operational-data rollback is needed. Keep PR5 Draft, no main merge,
no Production switch, no automatic /TO activation.
