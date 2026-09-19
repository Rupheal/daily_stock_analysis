"""Run056 formal U45 decision/ranking with private raw provider evidence.

This is the first current-session formal U strategy decision after the dated
macro-cap, source-bound risk evidence and Run055 strategy-zone contract. It
never places orders or writes the simulation journal. Public output contains
only structured decisions/metadata; provider request/response remains private.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median

import httpx

from deepseek_flash_cap010_guard import _official_input_tokens, peak_upper_cny
from run_hk_bounded_native_members import private_save, balance
from dsa_drive_store import DriveStore, scoped_token
from o_provider_completion import inspect_completion

VERSION = "U_FORMAL_DECISION_RANKING_v1"
MODEL = "deepseek-flash"
TARGET_SESSION = "2026-09-17"
EXPECTED_RUN_ID = "TRI-DSA-RESUME-20260917-056"
ARTIFACT_PREFIX = "DSA-RUN056-U-FORMAL"
DECISIONS = {"BUY_CANDIDATE", "WATCH", "AVOID", "BLOCKED_DATA"}
CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}

SYSTEM = r'''你是升级版U港股中短交易的正式逐股决策与横截面排序组件，与O原版完全独立。只使用输入中给出的已核验事实、明确时间和明确缺口；禁止调用外部记忆，禁止补造新闻、资金身份、价格、行业风险或宏观事实。

本轮目标是对同一冻结规则下的U候选做可比较的策略优先级判断。score为0到100的“U中短线策略优先级分”，不是概率、收益率、仓位或目标价。两个批次必须使用同一绝对标尺：高分要求量价/趋势/相对强弱/可核验资金或事件证据出现较强共振且风险可管理；中等分表示条件性观察；弱势或证据不足应较低。不得因为宏观仓位上限改变score或rank；宏观仓位由外层独立约束，本请求不提供宏观打分输入。

资金规则：VERIFIED只说明给定日期、给定通道的已验证流量；ONE_SESSION_ONLY_NOT_A_TREND不能说成持续机构趋势；NOT_DISCLOSED_IN_TOP10不是零流量；不得推断“外资/机构/主力”最终身份。新闻规则：有界搜索未发现事件不等于没有风险；issuer primary review不是完整风险覆盖。sector risk若NOT_SEPARATELY_SOURCE_BOUND，必须在判断中视作明确的不确定性，不能伪装成安全。

当前日线与前一日技术锚点时间不同，必须按字段时间使用：current_bar是目标日收盘事实；prior_technical是前一交易日形成的技术锚点。不得把prior MA/RSI/MACD冒充目标日实时指标。可用current_return_from_prior_close_pct和current_volume_vs_prior_session做目标日变化判断。

正式decision只允许BUY_CANDIDATE、WATCH、AVOID、BLOCKED_DATA。BUY_CANDIDATE只是可进入后续执行Gate的候选，不是订单。没有足够的源绑定支持/风险依据时宁可WATCH或BLOCKED_DATA。不能为了凑Top3强行BUY。

买入区间不得输出任意价格数字。BUY_CANDIDATE必须只从allowed_zone_anchors里选择zone_low_anchor和zone_high_anchor两个名称，并选择一个zone_thesis_code；系统随后用原始证据值确定性解析。非BUY必须两个anchor都为NONE且zone_thesis_code=WITHHOLD。不得用未来报价、Entry-v1执行带或未提供的价格构造策略区间。

reason_codes只能从给定allowed_reason_codes选择，至少2个、最多6个；必须同时体现支持或反对判断的关键依据，不能创造新代码。confidence只允许LOW/MEDIUM/HIGH。

只输出JSON对象：{"members":[...]}
每项键必须恰好为：code,decision,score,confidence,reason_codes,zone_low_anchor,zone_high_anchor,zone_thesis_code。
覆盖requested_codes恰好一次，不多不少。不得输出解释性自由文本、目标价、止损、仓位、排名、其他股票信息或任何未要求字段。'''


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def finite_number(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def index_by(rows, key="code"):
    out = {}
    for row in rows:
        code = str(row[key])
        if code in out:
            raise ValueError("DUPLICATE_MEMBER_CODE")
        out[code] = row
    return out


def load_inputs(paths):
    member = json.loads(paths["member"].read_text())
    close = json.loads(paths["close"].read_text())
    macro = json.loads(paths["macro"].read_text())
    risk = json.loads(paths["risk"].read_text())
    zone = json.loads(paths["zone"].read_text())
    if member.get("U_denominator") != 45 or close.get("denominator") != 45 or risk.get("counts", {}).get("denominator") != 45 or zone.get("denominator") != 45:
        raise ValueError("U45_DENOMINATOR_MISMATCH")
    if close.get("target_session") != TARGET_SESSION or zone.get("target_session") != TARGET_SESSION:
        raise ValueError("TARGET_SESSION_MISMATCH")
    if macro.get("regime", {}).get("position_ceiling_pct") != 30 or zone.get("macro_position_ceiling_pct") != 30:
        raise ValueError("RUN053_MACRO_CAP_MISMATCH")
    if zone.get("state") != "PASS_CONTRACT_ONLY_FORMAL_MEMBER_ZONES_PENDING_RUN056":
        raise ValueError("RUN055_NOT_ACCEPTED")
    return member, close, macro, risk, zone


def make_member_inputs(member, close, risk, zone):
    base = index_by(member["members"])
    current = index_by(close["facts"])
    riskmap = index_by(risk["rows"])
    zonemap = index_by(zone["rows"])
    codes = set(base) | set(current) | set(riskmap) | set(zonemap)
    if len(codes) != 45 or not (set(base) == set(current) == set(riskmap) == set(zonemap)):
        raise ValueError("U45_MEMBER_SET_MISMATCH")
    rows = []
    for code in sorted(codes):
        b, c, r, z = base[code], current[code], riskmap[code], zonemap[code]
        eligible = bool(r.get("eligible"))
        if eligible != bool(z.get("eligible")):
            raise ValueError("ELIGIBILITY_CONFLICT")
        facts = b.get("facts") or {}
        prior_close = finite_number(facts.get("close"))
        cur_close = finite_number(c.get("close"))
        cur_volume = finite_number(c.get("volume"))
        prior_volume = finite_number(facts.get("volume_shares"))
        if cur_close is None or prior_close is None or cur_close <= 0 or prior_close <= 0:
            raise ValueError("PRICE_ANCHOR_MISSING")
        anchors = {
            "PRIOR_SUPPORT20": finite_number(facts.get("observed_support20")),
            "PRIOR_MA20": finite_number(facts.get("ma20")),
            "PRIOR_MA10": finite_number(facts.get("ma10")),
            "PRIOR_MA5": finite_number(facts.get("ma5")),
            "PRIOR_CLOSE": prior_close,
            "CURRENT_LOW": finite_number(c.get("low")),
            "CURRENT_OPEN": finite_number(c.get("open")),
            "CURRENT_CLOSE": cur_close,
        }
        anchors = {k: v for k, v in anchors.items() if v is not None and v > 0}
        capital = r.get("capital_evidence") or {}
        event = r.get("company_event_evidence") or {}
        review = r.get("qualitative_review") or {}
        issuer = r.get("issuer_primary_review") or {}
        sector = r.get("sector_risk_evidence") or {}
        rows.append({
            "code": code,
            "name": r.get("name") or b.get("name"),
            "eligible": eligible,
            "current_bar": {k: finite_number(c.get(k)) for k in ("open", "high", "low", "close", "volume")},
            "current_return_from_prior_close_pct": (cur_close / prior_close - 1.0) * 100.0,
            "current_volume_vs_prior_session": (cur_volume / prior_volume) if cur_volume is not None and prior_volume and prior_volume > 0 else None,
            "prior_technical": {
                "asof_session": b.get("data_session"),
                "return_1d_pct": finite_number(facts.get("return_1d_pct")),
                "return_5d_pct": finite_number(facts.get("return_5d_pct")),
                "return_20d_pct": finite_number(facts.get("return_20d_pct")),
                "ma5": finite_number(facts.get("ma5")),
                "ma10": finite_number(facts.get("ma10")),
                "ma20": finite_number(facts.get("ma20")),
                "rsi14": finite_number(facts.get("rsi14")),
                "macd_histogram_2x": finite_number((facts.get("macd") or {}).get("histogram_2x")),
                "volume_vs_previous5": finite_number(facts.get("volume_vs_previous5")),
                "support20": finite_number(facts.get("observed_support20")),
                "resistance20": finite_number(facts.get("observed_resistance20")),
                "trend": facts.get("trend"),
            },
            "capital": {
                "state": capital.get("state"),
                "net_buy_hkd": capital.get("net_buy_hkd"),
                "date": capital.get("date"),
                "persistence": capital.get("persistence"),
                "ultimate_investor_identity": capital.get("ultimate_investor_identity"),
            },
            "company_event": {
                "state": event.get("state"),
                "issuer_primary_reviewed": issuer.get("reviewed"),
                "full_risk_coverage_proven": issuer.get("full_risk_coverage_proven"),
            },
            "sector_risk_state": sector.get("state"),
            "prior_qualitative_review_state": review.get("state"),
            "allowed_zone_anchors": anchors,
            "run055_zone_status": z.get("zone_status"),
            "risk_missingness_explicit": z.get("risk_missingness_explicit") is True,
        })
    ineligible = [x["code"] for x in rows if not x["eligible"]]
    if ineligible != ["09618"]:
        raise ValueError("EXPECTED_09618_ONLY_INELIGIBLE")
    return rows


def global_context(rows):
    eligible = [r for r in rows if r["eligible"]]
    def med(key):
        vals = [r[key] for r in eligible if r.get(key) is not None and math.isfinite(float(r[key]))]
        return median(vals) if vals else None
    prior5 = [r["prior_technical"].get("return_5d_pct") for r in eligible]
    prior5 = [x for x in prior5 if x is not None and math.isfinite(float(x))]
    rsi = [r["prior_technical"].get("rsi14") for r in eligible]
    rsi = [x for x in rsi if x is not None and math.isfinite(float(x))]
    return {
        "eligible_count": len(eligible),
        "median_current_return_from_prior_close_pct": med("current_return_from_prior_close_pct"),
        "median_current_volume_vs_prior_session": med("current_volume_vs_prior_session"),
        "median_prior_return_5d_pct": median(prior5) if prior5 else None,
        "median_prior_rsi14": median(rsi) if rsi else None,
        "positive_current_return_count": sum(r["current_return_from_prior_close_pct"] > 0 for r in eligible),
        "verified_capital_count": sum(r["capital"].get("state") == "VERIFIED" for r in eligible),
        "sector_risk_source_bound_count": sum(r.get("sector_risk_state") != "NOT_SEPARATELY_SOURCE_BOUND" for r in eligible),
    }


def validate_model_row(row, source, scope):
    keys = {"code", "decision", "score", "confidence", "reason_codes", "zone_low_anchor", "zone_high_anchor", "zone_thesis_code"}
    if not isinstance(row, dict) or set(row) != keys:
        raise ValueError("RUN056_SCHEMA")
    if row["code"] != source["code"] or row["decision"] not in DECISIONS:
        raise ValueError("RUN056_DECISION")
    if type(row["score"]) is not int or not 0 <= row["score"] <= 100:
        raise ValueError("RUN056_SCORE")
    if row["confidence"] not in CONFIDENCE:
        raise ValueError("RUN056_CONFIDENCE")
    allowed_reasons = set(scope["formal_reason_code_set"])
    reasons = row["reason_codes"]
    if not isinstance(reasons, list) or not 2 <= len(reasons) <= 6 or len(set(reasons)) != len(reasons) or not set(reasons) <= allowed_reasons:
        raise ValueError("RUN056_REASON_CODES")
    if source.get("sector_risk_state") == "NOT_SEPARATELY_SOURCE_BOUND" and "SECTOR_RISK_NOT_SOURCE_BOUND" not in reasons:
        raise ValueError("RUN056_SECTOR_MISSINGNESS_DROPPED")
    if source["capital"].get("state") == "NOT_DISCLOSED_IN_TOP10" and "CAPITAL_ACCUMULATION_VERIFIED" in reasons:
        raise ValueError("RUN056_CAPITAL_INVENTED")
    if source["capital"].get("state") != "VERIFIED" and "CAPITAL_OUTFLOW_VERIFIED" in reasons:
        raise ValueError("RUN056_CAPITAL_OUTFLOW_INVENTED")
    allowed_zone = set(scope["zone_contract"]["allowed_anchor_names"])
    thesis_set = set(scope["zone_thesis_code_set"])
    low, high, thesis = row["zone_low_anchor"], row["zone_high_anchor"], row["zone_thesis_code"]
    if thesis not in thesis_set:
        raise ValueError("RUN056_ZONE_THESIS")
    if row["decision"] == "BUY_CANDIDATE":
        if low not in allowed_zone or high not in allowed_zone or thesis == "WITHHOLD":
            raise ValueError("RUN056_BUY_ZONE_ANCHOR_REQUIRED")
        if low not in source["allowed_zone_anchors"] or high not in source["allowed_zone_anchors"]:
            raise ValueError("RUN056_BUY_ZONE_ANCHOR_VALUE_MISSING")
        if source["allowed_zone_anchors"][low] > source["allowed_zone_anchors"][high]:
            raise ValueError("RUN056_BUY_ZONE_ANCHOR_ORDER")
    else:
        if low != "NONE" or high != "NONE" or thesis != "WITHHOLD":
            raise ValueError("RUN056_NONBUY_ZONE_MUST_WITHHOLD")
    return row


def validate_response(content, members, scope):
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {"members"} or not isinstance(value["members"], list):
        raise ValueError("RUN056_RESPONSE_SCHEMA")
    by = {m["code"]: m for m in members}
    seen = set(); accepted = []; isolated = []
    for row in value["members"]:
        code = row.get("code") if isinstance(row, dict) else None
        if code not in by or code in seen:
            raise ValueError("RUN056_MEMBER_SET")
        seen.add(code)
        try:
            accepted.append(validate_model_row(row, by[code], scope))
        except ValueError as exc:
            isolated.append({"code": code, "reason": str(exc)})
    for code in sorted(set(by) - seen):
        isolated.append({"code": code, "reason": "RUN056_MEMBER_MISSING"})
    return accepted, isolated


def public_row(model_row, source, batch_index, raw_hash):
    action = model_row["decision"]
    zone_status = "WITHHELD_UNKNOWN"
    lower = upper = None
    formal_action = action
    validation = "PASS"
    if action == "BUY_CANDIDATE":
        low_name, high_name = model_row["zone_low_anchor"], model_row["zone_high_anchor"]
        lower = source["allowed_zone_anchors"][low_name]
        upper = source["allowed_zone_anchors"][high_name]
        if not (math.isfinite(lower) and math.isfinite(upper) and 0 < lower <= upper):
            formal_action = "BLOCKED_DATA"; validation = "ZONE_NUMERIC_RESOLUTION_FAILED"
            lower = upper = None
        else:
            formal_action = "BUY"; zone_status = "APPROVED_NUMERIC"
    decision_id = hashlib.sha256(json.dumps({
        "version": VERSION, "code": source["code"], "target": TARGET_SESSION,
        "model": model_row, "anchors": source["allowed_zone_anchors"], "raw_hash": raw_hash,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {
        "code": source["code"],
        "name": source["name"],
        "eligible": source["eligible"],
        "model_decision": model_row["decision"],
        "formal_action": formal_action,
        "score": model_row["score"],
        "confidence": model_row["confidence"],
        "reason_codes": model_row["reason_codes"],
        "zone_status": zone_status,
        "zone_lower_hkd": lower,
        "zone_upper_hkd": upper,
        "zone_low_anchor": model_row["zone_low_anchor"],
        "zone_high_anchor": model_row["zone_high_anchor"],
        "zone_thesis_code": model_row["zone_thesis_code"],
        "risk_missingness_explicit": source["risk_missingness_explicit"],
        "sector_risk_state": source["sector_risk_state"],
        "capital_state": source["capital"].get("state"),
        "capital_date": source["capital"].get("date"),
        "capital_persistence": source["capital"].get("persistence"),
        "macro_position_ceiling_pct": 30,
        "macro_changed_score_or_rank": False,
        "formal_decision_id": decision_id,
        "provider_batch": batch_index,
        "provider_raw_sha256": raw_hash,
        "validation": validation,
        "buyable_verified": formal_action == "BUY",
        "entry_v1_applied": False,
        "execution_quote_used": False,
        "order_created": False,
        "fill_created": False,
    }


def finalize(all_rows, ineligible, input_hashes, batch_summaries):
    valid = sorted(all_rows, key=lambda r: (-r["score"], r["code"]))
    for i, row in enumerate(valid, 1):
        row["rank"] = i
    buys = [r for r in valid if r["formal_action"] == "BUY" and r["buyable_verified"]]
    top3 = [{k:r[k] for k in ("code","name","rank","score","formal_action","zone_lower_hkd","zone_upper_hkd","reason_codes","confidence")} for r in buys[:3]]
    top10 = [{k:r[k] for k in ("code","name","rank","score","formal_action","reason_codes","confidence")} for r in valid[:10]]
    confirmed = sum(x.get("http_confirmed", 0) for x in batch_summaries)
    possible = sum(x.get("http_possible", 0) for x in batch_summaries)
    return {
        "schema_version": 1,
        "run_id": EXPECTED_RUN_ID,
        "target_session": TARGET_SESSION,
        "track": "U",
        "state": "PASS_FORMAL_U_DECISION_WITH_BUYS" if buys else "PASS_FORMAL_U_DECISION_WAIT_NO_BUY",
        "denominator": 45,
        "eligible": 44,
        "retained_ineligible": [ineligible],
        "formal_valid_rows": len(valid),
        "qualified_BUY": len(buys),
        "Top3": top3,
        "Top10": top10,
        "rows": valid,
        "input_sha256": input_hashes,
        "macro_overlay": {"position_ceiling_pct": 30, "changes_native_score_or_rank": False, "final_position_decision": "USER"},
        "resource_accounting": {
            "model_http_requests_confirmed": confirmed,
            "model_http_requests_possible": possible,
            "provider_model": MODEL,
            "request_batches": len(batch_summaries),
            "pre_send_cost_upper_cny": str(sum(Decimal(x.get("pre_send_upper_cny", "0")) for x in batch_summaries)),
            "observed_balance_delta_cny": str(sum(Decimal(x["observed_balance_delta_cny"]) for x in batch_summaries if x.get("observed_balance_delta_cny") is not None)) if any(x.get("observed_balance_delta_cny") is not None for x in batch_summaries) else None,
            "actual_charge_cny": None,
            "accepted_rows": len(valid),
            "isolated_rows": sum(len(x.get("isolated_rows", [])) for x in batch_summaries),
            "qualified_BUY": len(buys),
            "real_orders": 0,
            "simulation_writes": 0,
            "auto_recharge": False,
        },
        "batch_summaries": batch_summaries,
        "boundary": "Formal U strategy decision/ranking only. Top3 may contain fewer than three. No Entry-v1 intersection, quote, order, fill, or simulation journal write.",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", type=Path, required=True)
    ap.add_argument("--member", type=Path, required=True)
    ap.add_argument("--close", type=Path, required=True)
    ap.add_argument("--macro", type=Path, required=True)
    ap.add_argument("--risk", type=Path, required=True)
    ap.add_argument("--zone", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    scope = json.loads(a.scope.read_text())
    if scope.get("run_id") != EXPECTED_RUN_ID or scope.get("maximum_requests", scope.get("provider_plan", {}).get("maximum_requests")) not in (None, 2):
        raise ValueError("RUN056_SCOPE_MISMATCH")
    paths = {"member":a.member,"close":a.close,"macro":a.macro,"risk":a.risk,"zone":a.zone}
    member, close, macro, risk, zone = load_inputs(paths)
    rows = make_member_inputs(member, close, risk, zone)
    eligible = [r for r in rows if r["eligible"]]
    if len(eligible) != 44:
        raise ValueError("RUN056_ELIGIBLE_COUNT")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1" or os.environ.get("GITHUB_EVENT_NAME") != "push":
        raise ValueError("RUN056_ONE_SHOT_PUSH_ONLY")
    a.out.mkdir(parents=True, exist_ok=False)
    input_hashes = {k:sha256_path(v) for k,v in paths.items()}
    context = global_context(rows)
    reason_codes = scope["formal_reason_code_set"]
    zone_thesis = scope["zone_thesis_code_set"]
    allowed_anchors = scope["zone_contract"]["allowed_anchor_names"]
    max_cost = Decimal(scope["provider_plan"]["maximum_cost_cny"])
    summaries=[]; public=[]; reserved=Decimal("0"); stop=False
    for batch_index in range(2):
        members = eligible[batch_index*22:(batch_index+1)*22]
        root = a.out / f"batch{batch_index}"; root.mkdir()
        artifact = f"{ARTIFACT_PREFIX}-B{batch_index}"
        run_id = scope["run_id"] + f"-B{batch_index}"
        summary = {"batch":batch_index,"members":len(members),"status":"PENDING","http_possible":0,"http_confirmed":0,"accepted_rows":0,"isolated_rows":[],"actual_charge_cny":None}
        if stop:
            summary["status"]="ISOLATED_AFTER_SHARED_FAILURE";summaries.append(summary);continue
        body = {
            "model": MODEL,
            "thinking": {"type":"disabled"},
            "max_tokens": 4096,
            "temperature": 0,
            "stream": False,
            "response_format": {"type":"json_object"},
            "messages": [
                {"role":"system","content":SYSTEM},
                {"role":"user","content":json.dumps({
                    "version":VERSION,
                    "target_session":TARGET_SESSION,
                    "requested_codes":[m["code"] for m in members],
                    "global_u_context":context,
                    "allowed_reason_codes":reason_codes,
                    "allowed_zone_anchors":allowed_anchors + ["NONE"],
                    "allowed_zone_thesis_codes":zone_thesis,
                    "members":members,
                    "macro_not_part_of_score_or_rank":True,
                    "force_three_buys":False,
                },ensure_ascii=False)}
            ],
        }
        try:
            upper = peak_upper_cny(_official_input_tokens(body), 4096)
            if upper > Decimal("0.30") or reserved + upper > max_cost:
                raise ValueError("RUN056_BUDGET_PRE_SEND_REJECT")
            summary["pre_send_upper_cny"] = str(upper)
            write(root/"provider-request.json",body)
            write(root/"input-contract.json",{
                "version":VERSION,"target_session":TARGET_SESSION,"requested_codes":[m["code"] for m in members],
                "input_sha256":input_hashes,"macro_not_in_model_score":True,"no_execution":True,
            })
            summary["pre_send_private"] = private_save(root, artifact+"-PRE-SEND", run_id)
            if not summary["pre_send_private"].get("save_read_hash_restore"):
                raise ValueError("RUN056_PRIVATE_PRE_SEND_FAILED")
            before = balance()
            if before < upper:
                raise ValueError("RUN056_AVAILABLE_BALANCE_INSUFFICIENT")
            write(root/"private-balance-before.json",{"balance_cny":str(before),"retrieved_at":datetime.now(timezone.utc).isoformat()})
            request_hash = hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(",", ":")).encode()).hexdigest()
            with httpx.Client(timeout=30, follow_redirects=False) as c:
                c.headers["Authorization"] = "Bearer " + scoped_token(c)
                store = DriveStore(c, os.environ["DSA_DRIVE_FOLDER_ID"])
                claim = store.reserve_native_call(artifact, run_id, request_hash, "CI-"+os.environ["GITHUB_RUN_ID"]+f"-U56-{batch_index}")
            write(root/"private-claim.json",claim);summary["http_possible"]=1;reserved += upper
            with httpx.Client(timeout=180, follow_redirects=False) as c:
                response = c.post("https://api.deepseek.com/chat/completions",headers={"Authorization":"Bearer "+os.environ["DEEPSEEK_API_KEY"]},json=body)
            (root/"provider-response.json").write_bytes(response.content);summary["http_confirmed"]=1;summary["http_status"]=response.status_code
            response.raise_for_status()
            audit = inspect_completion(response.content);write(root/"provider-completion-audit.json",audit)
            if audit.get("status") != "PASS":
                raise ValueError("RUN056_PROVIDER_COMPLETION_REJECT")
            provider = response.json();usage=provider.get("usage") or {};summary["usage"]=usage
            if type(usage.get("prompt_tokens")) is int and type(usage.get("completion_tokens")) is int:
                estimate=(Decimal(usage["prompt_tokens"])*2+Decimal(usage["completion_tokens"])*8)/1000000
                summary["usage_peak_estimate_cny"]=str(estimate)
                if estimate > upper:
                    raise ValueError("RUN056_USAGE_EXCEEDS_RESERVATION")
            content=provider["choices"][0]["message"]["content"]
            accepted, isolated = validate_response(content,members,scope)
            raw_hash=hashlib.sha256(response.content).hexdigest();summary["provider_raw_sha256"]=raw_hash
            by={m["code"]:m for m in members}
            for r in accepted:
                public.append(public_row(r,by[r["code"]],batch_index,raw_hash))
            summary["accepted_rows"]=len(accepted);summary["isolated_rows"]=isolated
            summary["status"]="FORMAL_ROWS_VALIDATED" if not isolated else "PARTIAL_MEMBER_ISOLATION"
            write(root/"validated-private-rows.json",{"accepted":accepted,"isolated":isolated,"raw_sha256":raw_hash})
            try:
                after=balance();summary["observed_balance_delta_cny"]=str(before-after)
                write(root/"private-balance-after.json",{"balance_cny":str(after),"retrieved_at":datetime.now(timezone.utc).isoformat()})
            except Exception:
                summary["observed_balance_delta_cny"]=None
        except Exception as exc:
            summary["status"]="ISOLATED";summary["reason"]=str(exc)[:160] if isinstance(exc,(ValueError,AssertionError)) else type(exc).__name__
            if summary.get("http_possible"):
                stop=True
        finally:
            try:
                write(root/"summary.json",summary);summary["private_persistence"]=private_save(root,artifact,run_id)
                if not summary["private_persistence"].get("save_read_hash_restore"):
                    stop=True
            except Exception as exc:
                summary["private_persistence"]={"status":"FAIL","reason":type(exc).__name__};stop=True
            summaries.append(summary)
            print(json.dumps(summary,ensure_ascii=False),flush=True)
    if len(public) + sum(len(x.get("isolated_rows",[])) for x in summaries) != 44:
        # A shared failure may intentionally stop the second paid batch. Never call that a full formal run.
        state={
            "schema_version":1,"run_id":scope["run_id"],"target_session":TARGET_SESSION,"track":"U",
            "state":"NO_GO_INCOMPLETE_FORMAL_PROVIDER_COVERAGE","denominator":45,"eligible":44,"retained_ineligible":["09618"],
            "formal_valid_rows":len(public),"qualified_BUY":0,"Top3":[],"Top10":[],"rows":public,
            "input_sha256":input_hashes,"batch_summaries":summaries,
            "resource_accounting":{"model_http_requests_confirmed":sum(x.get("http_confirmed",0) for x in summaries),"model_http_requests_possible":sum(x.get("http_possible",0) for x in summaries),"real_orders":0,"simulation_writes":0,"auto_recharge":False},
            "boundary":"Incomplete formal provider coverage is fail-closed; no rank/BUY promoted."
        }
        write(a.out/"SANITIZED_U_FORMAL_RESULT.json",state);print(json.dumps({"state":state["state"],"formal_valid_rows":len(public)}));return
    result=finalize(public,"09618",input_hashes,summaries)
    write(a.out/"SANITIZED_U_FORMAL_RESULT.json",result)
    print(json.dumps({"state":result["state"],"qualified_BUY":result["qualified_BUY"],"Top3":result["Top3"],"Top10":result["Top10"],"resources":result["resource_accounting"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
