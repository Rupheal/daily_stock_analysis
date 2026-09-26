"""Prospective adapter to the accepted Entry-v1 executor; no I/O or activation.

Evidence assertions must be authenticated upstream. Never turn a legacy quote
packet into an accepted morning report or infer missing order/fill timestamps.
"""
from __future__ import annotations

import copy
from decimal import Decimal

import exchange_calendars as xcals

from src.services.dsa_entry_policy import check_binding, dt, POLICY_HASH, POLICY_ID
from src.services.dsa_prediction_ledger import canonical_hash


def build_bound_entry(track, signal_cmd, packet, now):
    if not isinstance(packet, dict) or not isinstance(packet.get("binding"), dict):
        return [], ["ENTRY_POLICY_BINDING_REQUIRED"]
    candidate = copy.deepcopy(signal_cmd)
    try:
        binding = copy.deepcopy(packet["binding"])
        if binding.get("policy_id") != POLICY_ID or binding.get("policy_sha256") != POLICY_HASH:
            raise ValueError("ENTRY_POLICY_IDENTITY_MISMATCH")
        candidate["signal"]["entry_policy"] = binding
        candidate["at"] = packet["signal_at"]
        candidate["recorded_at"] = packet["signal_recorded_at"]
        reason = check_binding(candidate["signal"], candidate)
        if reason:
            raise ValueError("ENTRY_" + reason)
        if dt(candidate["recorded_at"]) > dt(now):
            raise ValueError("ENTRY_FUTURE_RECORDING")
        session = binding["session"]
        if session != track["target_session"]:
            raise ValueError("ENTRY_SESSION_MISMATCH")
        cal = xcals.get_calendar("XHKG")
        if not cal.is_session(session):
            raise ValueError("ENTRY_SESSION_NOT_TRADING")
        previous = cal.previous_session(session).date().isoformat()
        if binding["calendar"]["previous_session"] != previous:
            raise ValueError("ENTRY_PREVIOUS_SESSION_MISMATCH")
        if track["track"] == "U":
            zones = binding.get("native_buy_zones", {})
            for row in track["candidates"]:
                if row["action"] != "BUY":
                    continue
                zone = zones.get(row["code"], {})
                if (Decimal(str(zone.get("lower"))) != Decimal(str(row["zone_lower_hkd"]))
                        or Decimal(str(zone.get("upper"))) != Decimal(str(row["zone_upper_hkd"]))):
                    raise ValueError("ENTRY_NATIVE_ZONE_MISMATCH")
        # A distinct prospective binding must not mutate a historical SIGNAL ID.
        suffix = canonical_hash({"binding": binding, "at": candidate["at"],
                                 "recorded_at": candidate["recorded_at"]})[:16]
        sid = candidate["signal"]["id"] + "-entryv1-" + suffix
        candidate["signal"]["id"] = sid
        candidate["id"] = "signal-" + sid
        events = packet.get("events")
        if not isinstance(events, list):
            raise ValueError("ENTRY_EVENTS_REQUIRED")
        commands = []
        last_at = dt(candidate["at"])
        for event in events:
            if not isinstance(event, dict) or event.get("kind") not in (
                    "ENTRY_ORDER", "ENTRY", "ENTRY_CANCEL", "ENTRY_CLOCK", "MARK"):
                raise ValueError("ENTRY_EVENT_INVALID")
            c = copy.deepcopy(event)
            if c.get("account") != track["track"]:
                raise ValueError("ENTRY_ACCOUNT_MISMATCH")
            if c.get("signal_id") not in (None, sid):
                raise ValueError("ENTRY_SIGNAL_MISMATCH")
            at, recorded = dt(c["at"]), dt(c["recorded_at"])
            if not last_at <= at <= recorded <= dt(now):
                raise ValueError("ENTRY_EVENT_TIME_INVALID")
            if at.date().isoformat() != session:
                raise ValueError("ENTRY_EVENT_SESSION_MISMATCH")
            if not isinstance(c.get("id"), str) or not c["id"]:
                raise ValueError("ENTRY_EVENT_ID_REQUIRED")
            c["signal_id"] = sid
            commands.append(c)
            last_at = at
        if len({c["id"] for c in commands}) != len(commands):
            raise ValueError("ENTRY_EVENT_ID_DUPLICATE")
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError) as exc:
        message = str(exc)
        return [], [message if message.startswith("ENTRY_") else "ENTRY_BINDING_INVALID"]
    signal_cmd.clear()
    signal_cmd.update(candidate)
    return commands, []
