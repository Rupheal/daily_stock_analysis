"""Synthetic integration fixtures: no market evidence or natural-cycle credit."""
import copy
import hashlib
import json

import pytest

from scripts.dsa_entry_binding_v1 import build_bound_entry
from scripts.dsa_isolated_entry_replay_v1 import replay_candidate
from scripts.dsa_production_orchestrator_v1 import orchestrate, O_UPSTREAM
from scripts.dsa_formal_receipt_resolver_v1 import resolve
from src.services.dsa_entry_policy import POLICY_HASH, POLICY_ID
from src.services.dsa_simulation_ledger import new_journal, replay
from src.services.dsa_prediction_ledger import canonical_hash

EV = {"verified": True, "source": "synthetic-fixture", "sha256": "a"*64}
DAY = "2026-09-24"
def t(h): return DAY + "T" + h + "+08:00"

def quote(at):
    return {**EV, "code": "00148", "at": at, "received_at": at,
            "price": "10", "cny_per_hkd": "1", "tradable": True,
            "adjustment": "raw", "lot_size": 100, "lot_verified": True,
            "fx_evidence": {**EV, "at": t("09:00:00")}, "mode": "tick",
            "session_phase": "continuous", "quote_kind": "firm_ask",
            "first_eligible_price_verified": True, "quantity_verified": True,
            "available_qty": 600}

def packet():
    return {"signal_at": t("09:20:00"), "signal_recorded_at": t("09:20:00"),
            "binding": {"policy_id": POLICY_ID, "policy_sha256": POLICY_HASH,
                "session": DAY, "frozen_at": t("09:20:00"), "report_session": "AM",
                "morning_report_accepted": True,
                "calendar": {**EV, "at": t("09:00:00"), "session": DAY,
                    "previous_session": "2026-09-23", "is_trading_day": True},
                "references": {"00148": {**EV, "code": "00148", "close": "10",
                    "at": "2026-09-23T16:00:00+08:00", "session": "2026-09-23",
                    "comparable_basis": True, "corporate_actions_verified": True,
                    "price_basis": "execution_raw_comparable"}}},
            "events": [
                {"id": "order-command", "account": "O", "kind": "ENTRY_ORDER",
                 "at": t("09:21:00"), "recorded_at": t("09:21:00"), "code": "00148",
                 "quote": quote(t("09:21:00")),
                 "order": {"id": "order1", "qty": 600, "limit_price": "10.1", "fee_reserve_cny": "10"},
                 "fee_evidence": {**EV, "at": t("09:21:00"), "currency": "CNY", "amount_cny": "10"}},
                {"id": "fill-command", "account": "O", "kind": "ENTRY", "code": "00148",
                 "at": t("09:30:00"), "recorded_at": t("09:30:00"), "order_id": "order1",
                 "quote": quote(t("09:30:00")), "fill_qty": 300, "fee_cny": "2",
                 "fee_evidence": {**EV, "at": t("09:30:00"), "currency": "CNY", "amount_cny": "2"}}]}

def inputs(tmp_path):
    timing = {"cutoff": t("08:59:00"), "available_at": t("09:00:00"),
              "valid_until": t("10:00:00"), "next_session": "2026-09-25"}
    o = {"status": "ACCEPTED_O_FORMAL_TOP3", "target_session": DAY,
         "official_O_denominator": 662, "operational_O_denominator": 659,
         "missing_count": 0, "qualified_buy_in_Top3": 1, "signal_timing": timing,
         "Top3": [{"code": "00148", "rank": 1, "sentiment_score": 80,
                   "action": "buy", "action_family": "buy", "industry": "fixture",
                   "buyable_verified": True}]}
    u = {"state": "PASS_FORMAL_U_DECISION_WAIT_NO_BUY", "target_session": DAY,
         "denominator": 45, "formal_valid_rows": 45, "qualified_BUY": 0,
         "Top3": [], "rows": [], "signal_timing": timing}
    root = tmp_path/"docs/runtime"; root.mkdir(parents=True)
    op, up = [root/(k+"_PRODUCTION_FORMAL_LATEST.json") for k in ("O", "U")]
    op.write_text(json.dumps(o)); up.write_text(json.dumps(u))
    return o, u, op, up

def commands(tmp_path, ev=None, now=None):
    o,u,op,up = inputs(tmp_path)
    assert resolve(tmp_path, DAY)["state"] == "READY"
    return orchestrate(o,u,DAY,now or t("09:35:00"),"2026-09-25",op,up,
                       {"O": ev if ev is not None else packet()},True)

def journal():
    return new_journal({"accounts": {"U": "300000", "O": "300000"},
        "u_denominator": 45, "o_upstream_commit": O_UPSTREAM,
        "rules": {"max_positions": 3, "ticket_cny": "60000", "ticket_cap": ".2",
                  "total_cap": ".6", "industry_cap": ".4"}})

def run(j, cmds):
    raw = json.dumps(j).encode()
    blob = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    return replay_candidate(raw, blob, canonical_hash(j), cmds)

def test_resolver_orchestrator_entry_ledger_and_retry(tmp_path):
    r=commands(tmp_path); j=journal(); before=copy.deepcopy(j)
    assert r["state"] == "READY_FOR_ENTRY_V1_REPLAY"
    result=run(j,r["commands"])
    assert result["state"] == "ISOLATED_FILL_REPLAYED"
    assert result["new_fills"] == 1
    assert replay(result["candidate"])["O"]["cash"] == "296998"
    assert j == before
    retry=run(result["candidate"],r["commands"])
    assert retry["pending_count"] == 0 and retry["candidate"] == result["candidate"]
    mutated=copy.deepcopy(r["commands"]);mutated[1]["fee_evidence"]["amount_cny"]="99"
    with pytest.raises(ValueError,match="CONTENT_DRIFT"):
        run(result["candidate"],mutated)

@pytest.mark.parametrize("case",["late", "pm", "unaccepted", "policy", "previous", "future", "account"])
def test_invalid_binding_never_produces_entry(tmp_path,case):
    p=packet()
    if case=="late": p["signal_recorded_at"]=t("09:25:01")
    if case=="pm": p["binding"]["report_session"]="PM"
    if case=="unaccepted": p["binding"]["morning_report_accepted"]=False
    if case=="policy": p["binding"]["policy_sha256"]="b"*64
    if case=="previous": p["binding"]["calendar"]["previous_session"]="2026-09-22"
    if case=="future": p["events"][1]["recorded_at"]=t("09:36:00")
    if case=="account": p["events"][0]["account"]="U"
    r=commands(tmp_path,p)
    assert r["state"]=="BUY_ENTRY_BLOCKED"
    assert not any(c["kind"] in ("ENTRY","ENTRY_ORDER") for c in r["commands"])

@pytest.mark.parametrize("case",["before", "closed", "above", "below", "fee", "lot", "quantity", "code", "fx", "funds"])
def test_executor_checks_actual_fill_not_packet_label(tmp_path,case):
    p=packet(); fill=p["events"][1]
    if case in ("before","closed"):
        at=t("09:29:59" if case=="before" else "10:00:00")
        fill.update(at=at,recorded_at=at);fill["quote"].update(at=at,received_at=at)
    if case=="above": fill["quote"]["price"]="10.16"
    if case=="below": fill["quote"]["price"]="9.89"
    if case=="fee": del fill["fee_evidence"]
    if case=="lot": fill["quote"]["lot_verified"]=False
    if case=="quantity": fill["quote"]["quantity_verified"]=False
    if case=="code": fill["quote"]["code"]="99999"
    if case=="fx": fill["quote"]["fx_evidence"]["at"]=t("09:40:00")
    if case=="funds": p["events"][0]["order"]["qty"]=60000
    r=commands(tmp_path,p,now=t("10:00:00"))
    result=run(journal(),r["commands"])
    assert result["state"]=="ISOLATED_POLICY_REJECTED"
    assert result["new_fills"]==0

def test_partial_fill_consumes_slot_and_expiry_cancels(tmp_path):
    p=packet(); second=copy.deepcopy(p["events"][0]); second.update(id="second-order",at=t("09:31:00"),recorded_at=t("09:31:00"))
    second["order"]["id"]="order2"
    p["events"].extend([second,{"id":"expiry","kind":"ENTRY_CLOCK","account":"O","at":t("10:00:00"),"recorded_at":t("10:00:00")}])
    r=commands(tmp_path,p,now=t("10:00:00"));result=run(journal(),r["commands"])
    events=result["events"]["O"]
    assert result["new_fills"]==1
    assert any(e.get("reason")=="DAILY_SLOT_USED" for e in events)
    assert any(e["kind"]=="ENTRY_CANCEL" and e["remaining_qty"]==300 for e in events)

def test_journal_source_identity_required():
    raw=json.dumps(journal()).encode()
    with pytest.raises(ValueError,match="BLOB_MISMATCH"):
        replay_candidate(raw,"0"*40,canonical_hash(journal()),[])

def test_generation_observation_is_not_availability(tmp_path):
    from scripts.dsa_producer_generation_v1 import record_generated
    p=tmp_path/"raw.json";p.write_text(json.dumps({"target_session":DAY}))
    sidecar=record_generated(p,"O",DAY); before=sidecar.read_bytes()
    assert record_generated(p,"O",DAY).read_bytes()==before
    data=json.loads(before)
    assert data["consumer_available_at"] is None and data["formal_accepted_at"] is None
    p.write_text(json.dumps({"target_session":DAY,"changed":True}))
    with pytest.raises(ValueError,match="GENERATION_CONFLICT"):
        record_generated(p,"O",DAY)


def test_actual_cli_leaves_source_unchanged_and_refuses_output_reuse(tmp_path):
    import subprocess, sys
    inputs(tmp_path)
    source=tmp_path/"source.json"; raw=json.dumps(journal()).encode(); source.write_bytes(raw)
    ev=tmp_path/"evidence.json";ev.write_text(json.dumps({"O":packet()}))
    out=tmp_path/"isolated"
    blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    args=[sys.executable,"-m","scripts.dsa_isolated_entry_replay_v1","--root",str(tmp_path),
          "--target-session",DAY,"--now",t("09:35:00"),"--next-session","2026-09-25",
          "--entry-evidence",str(ev),"--journal",str(source),"--expected-blob",blob,
          "--expected-hash",canonical_hash(journal()),"--out-dir",str(out)]
    first=subprocess.run(args,capture_output=True,text=True)
    assert first.returncode==0,first.stderr
    assert json.loads(first.stdout)["state"]=="ISOLATED_FILL_REPLAYED"
    assert source.read_bytes()==raw
    saved=(out/"candidate-journal.json").read_bytes()
    assert subprocess.run(args,capture_output=True).returncode!=0
    assert (out/"candidate-journal.json").read_bytes()==saved


def test_u_cannot_omit_or_broaden_native_zone(tmp_path):
    r=commands(tmp_path);signal=copy.deepcopy(r["commands"][0])
    signal["account"]="U"
    track={"track":"U","target_session":DAY,"candidates":[{
        "code":"00148","action":"BUY","zone_lower_hkd":"9.95","zone_upper_hkd":"10.05"}]}
    for zone in ({}, {"00148":{"lower":"9.9","upper":"10.1"}}):
        p=packet();p["binding"]["native_buy_zones"]=zone
        for e in p["events"]:e["account"]="U"
        cs,bs=build_bound_entry(track,copy.deepcopy(signal),p,t("09:35:00"))
        assert not cs and bs


def test_holiday_assertion_cannot_override_calendar(tmp_path):
    r=commands(tmp_path);signal=copy.deepcopy(r["commands"][0]);p=packet()
    def shift(obj):return json.loads(json.dumps(obj).replace(DAY,"2026-10-01").replace("2026-09-23","2026-09-30"))
    signal,p=shift(signal),shift(p)
    cs,bs=build_bound_entry({"track":"O","target_session":"2026-10-01"},signal,p,"2026-10-01T09:35:00+08:00")
    assert not cs and bs==["ENTRY_SESSION_NOT_TRADING"]


def test_u_accepted_zone_and_cap_reach_versioned_executor(tmp_path):
    o,u,op,up=inputs(tmp_path)
    o.update(qualified_buy_in_Top3=0,Top3=[])
    u.update(state="PASS_FORMAL_U_DECISION_BUY",qualified_BUY=1,
             Top3=[{"code":"00148","rank":1,"score":80,"formal_action":"BUY"}],
             rows=[{"code":"00148","rank":1,"score":80,"formal_action":"BUY",
                    "validation":"PASS","buyable_verified":True,"industry":"fixture",
                    "zone_status":"APPROVED","zone_lower_hkd":9.95,"zone_upper_hkd":10.1,
                    "macro_position_ceiling_pct":30}])
    op.write_text(json.dumps(o));up.write_text(json.dumps(u))
    p=packet();p["binding"]["native_buy_zones"]={"00148":{
        **EV,"at":t("09:00:00"),"code":"00148","lower":"9.95","upper":"10.1"}}
    for e in p["events"]:e["account"]="U"
    r=orchestrate(o,u,DAY,t("09:35:00"),"2026-09-25",op,up,{"U":p},True)
    result=run(journal(),r["commands"])
    assert result["state"]=="ISOLATED_FILL_REPLAYED"
    assert replay(result["candidate"])["U"]["cash"]=="296998"
    assert not replay(result["candidate"])["O"]["positions"]
