"""Run056 v2 orchestration patch: retain ineligible 09618 without fabricated anchors.

The formal provider request still covers exactly the 44 eligible members. The
45th denominator member remains explicitly retained/ineligible with no price
anchor requirement and can never enter ranking, BUY or a strategy zone.
"""
import run056_u_formal_decision as base


def make_member_inputs(member, close, risk, zone):
    bmap = base.index_by(member["members"])
    cmap = base.index_by(close["facts"])
    rmap = base.index_by(risk["rows"])
    zmap = base.index_by(zone["rows"])
    if not (set(bmap) == set(cmap) == set(rmap) == set(zmap)) or len(bmap) != 45:
        raise ValueError("U45_MEMBER_SET_MISMATCH")
    rows=[]
    for code in sorted(bmap):
        b,c,r,z=bmap[code],cmap[code],rmap[code],zmap[code]
        eligible=bool(r.get("eligible"))
        if eligible != bool(z.get("eligible")):
            raise ValueError("ELIGIBILITY_CONFLICT")
        facts=b.get("facts") or {}
        capital=r.get("capital_evidence") or {}
        event=r.get("company_event_evidence") or {}
        review=r.get("qualitative_review") or {}
        issuer=r.get("issuer_primary_review") or {}
        sector=r.get("sector_risk_evidence") or {}
        if not eligible:
            rows.append({
                "code":code,
                "name":r.get("name") or b.get("name"),
                "eligible":False,
                "current_bar":{k:base.finite_number(c.get(k)) for k in ("open","high","low","close","volume")},
                "current_return_from_prior_close_pct":None,
                "current_volume_vs_prior_session":None,
                "prior_technical":{"asof_session":b.get("data_session"),"trend":facts.get("trend")},
                "capital":{"state":capital.get("state"),"net_buy_hkd":capital.get("net_buy_hkd"),"date":capital.get("date"),"persistence":capital.get("persistence"),"ultimate_investor_identity":capital.get("ultimate_investor_identity")},
                "company_event":{"state":event.get("state"),"issuer_primary_reviewed":issuer.get("reviewed"),"full_risk_coverage_proven":issuer.get("full_risk_coverage_proven")},
                "sector_risk_state":sector.get("state"),
                "prior_qualitative_review_state":review.get("state"),
                "allowed_zone_anchors":{},
                "run055_zone_status":z.get("zone_status"),
                "risk_missingness_explicit":z.get("risk_missingness_explicit") is True,
                "retained_ineligible_reason":z.get("reason") or "CURRENT_OFFICIAL_BUY_ELIGIBILITY_FALSE",
            })
            continue
        prior_close=base.finite_number(facts.get("close"));cur_close=base.finite_number(c.get("close"))
        cur_volume=base.finite_number(c.get("volume"));prior_volume=base.finite_number(facts.get("volume_shares"))
        if prior_close is None or cur_close is None or prior_close<=0 or cur_close<=0:
            raise ValueError("ELIGIBLE_PRICE_ANCHOR_MISSING:"+code)
        anchors={
            "PRIOR_SUPPORT20":base.finite_number(facts.get("observed_support20")),
            "PRIOR_MA20":base.finite_number(facts.get("ma20")),
            "PRIOR_MA10":base.finite_number(facts.get("ma10")),
            "PRIOR_MA5":base.finite_number(facts.get("ma5")),
            "PRIOR_CLOSE":prior_close,
            "CURRENT_LOW":base.finite_number(c.get("low")),
            "CURRENT_OPEN":base.finite_number(c.get("open")),
            "CURRENT_CLOSE":cur_close,
        }
        anchors={k:v for k,v in anchors.items() if v is not None and v>0}
        rows.append({
            "code":code,
            "name":r.get("name") or b.get("name"),
            "eligible":True,
            "current_bar":{k:base.finite_number(c.get(k)) for k in ("open","high","low","close","volume")},
            "current_return_from_prior_close_pct":(cur_close/prior_close-1.0)*100.0,
            "current_volume_vs_prior_session":(cur_volume/prior_volume) if cur_volume is not None and prior_volume and prior_volume>0 else None,
            "prior_technical":{
                "asof_session":b.get("data_session"),
                "return_1d_pct":base.finite_number(facts.get("return_1d_pct")),
                "return_5d_pct":base.finite_number(facts.get("return_5d_pct")),
                "return_20d_pct":base.finite_number(facts.get("return_20d_pct")),
                "ma5":base.finite_number(facts.get("ma5")),
                "ma10":base.finite_number(facts.get("ma10")),
                "ma20":base.finite_number(facts.get("ma20")),
                "rsi14":base.finite_number(facts.get("rsi14")),
                "macd_histogram_2x":base.finite_number((facts.get("macd") or {}).get("histogram_2x")),
                "volume_vs_previous5":base.finite_number(facts.get("volume_vs_previous5")),
                "support20":base.finite_number(facts.get("observed_support20")),
                "resistance20":base.finite_number(facts.get("observed_resistance20")),
                "trend":facts.get("trend"),
            },
            "capital":{"state":capital.get("state"),"net_buy_hkd":capital.get("net_buy_hkd"),"date":capital.get("date"),"persistence":capital.get("persistence"),"ultimate_investor_identity":capital.get("ultimate_investor_identity")},
            "company_event":{"state":event.get("state"),"issuer_primary_reviewed":issuer.get("reviewed"),"full_risk_coverage_proven":issuer.get("full_risk_coverage_proven")},
            "sector_risk_state":sector.get("state"),
            "prior_qualitative_review_state":review.get("state"),
            "allowed_zone_anchors":anchors,
            "run055_zone_status":z.get("zone_status"),
            "risk_missingness_explicit":z.get("risk_missingness_explicit") is True,
        })
    ineligible=[x["code"] for x in rows if not x["eligible"]]
    if ineligible != ["09618"]:
        raise ValueError("EXPECTED_09618_ONLY_INELIGIBLE")
    return rows


base.make_member_inputs = make_member_inputs

if __name__ == "__main__":
    base.main()
