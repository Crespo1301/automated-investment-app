# Passthrough Contracts

This document is the safety spine of the project. Every handoff between subsystems should remain understandable, testable, and replayable.

## 1. Market Ingress -> Strategy Engine

### Purpose

Convert broker- or provider-specific events into one normalized internal event format.

### Required Fields

- `correlation_id`
- `source`
- `symbol`
- `timestamp`
- `event_kind`
- `price`
- `volume` when applicable
- `session_state`

### Guarantees

- Downstream systems do not need to understand vendor-specific payload shapes.
- Each event is attributable to a source and time.
- Events can be replayed in backtests and incident review.

### Common Failure Modes

- websocket disconnects
- missing or delayed bars
- out-of-order timestamps
- duplicate messages after reconnect

## 2. Strategy Engine -> AI Scorer

### Purpose

Provide the model with a trade candidate that already has deterministic evidence behind it.

### Required Fields

- `candidate_id`
- `strategy_id`
- `symbol`
- `direction`
- `trigger_evidence`
- `feature_snapshot`
- `proposed_entry`
- `proposed_stop`

### Guarantees

- AI receives a bounded, strategy-aware payload.
- The model is ranking an existing candidate, not freeform inventing one.
- Candidate provenance remains attached after scoring.

### Common Failure Modes

- stale features
- incomplete evidence payloads
- prompt inflation from irrelevant context

## 3. AI Scorer -> Risk Engine

### Purpose

Pass along an enriched candidate while preserving deterministic review control.

### Required Fields

- all candidate fields
- `model_name`
- `model_score`
- `model_summary`
- `score_timestamp`

### Guarantees

- Risk engine can ignore AI fields and still operate.
- AI output is additive, not authoritative.
- Every score is traceable to a model and time.

### Common Failure Modes

- malformed model output
- timeout or provider outage
- low-confidence scores treated too aggressively

## 4. Risk Engine -> Broker Adapter

### Purpose

Translate a reviewed trade candidate into an approved execution intent.

### Required Fields

- `intent_id`
- `candidate_id`
- `symbol`
- `side`
- `order_type`
- `approved_quantity`
- `approved_notional`
- `risk_budget_used`
- `mode`

### Guarantees

- Broker adapter receives a final execution instruction.
- Rejections remain explicit and do not silently disappear.
- Paper and live intents share the same shape.

### Common Failure Modes

- stale position cache
- approval based on incorrect buying power
- missing broker-specific field translation

## 5. Broker Adapter -> Portfolio State

### Purpose

Feed fills, cancellations, and rejections back into the control plane.

### Required Fields

- `broker_order_id`
- `intent_id`
- `status`
- `filled_quantity`
- `average_fill_price`
- `broker_timestamp`

### Guarantees

- Portfolio state can reconcile with broker truth.
- The dashboard can show order lifecycle state.
- Trade history remains attributable to the original intent.

### Common Failure Modes

- partial fills not propagated correctly
- order update race conditions
- broker session changes or maintenance windows

## Documentation Rule

Before adding a new lane or external integration, document:

1. input payload
2. output payload
3. required invariants
4. observable failure modes
5. replay or audit expectations

