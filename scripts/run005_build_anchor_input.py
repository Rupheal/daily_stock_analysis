"""Build a fail-closed Run005 historical PIT input package for one SSE addition anchor.

The original official notice-addition denominator is preserved. Securities without
21 complete predecision official HKEX bars are isolated with explicit reasons rather
than removed. No post-decision/outcome data is read.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import statistics
from html.parser import HTMLParser
from pathlib import Path

from scripts.run004_parse_hkex_pit_quotes import LINE1, LINE2, text_from_html
from src.services.dsa_pit_manifest import canonical_hash, validate_pit_manifest

_CODE = re.compile(r"^\d{1,5}$")
_SUSPENDED = re.compile(r"^\s*\*?\s*(?P<code>\d{1,5})\s+.+?\s+(?:HKD|RMB|USD)\s+TRADING\s+SUSPENDED\s*$", re.I)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._in_cell = True

    def handle_data(self, data):
        if self._in_cell and self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._in_cell:
            text = " ".join("".join(self._cell or []).split())
            self._row.append(html.unescape(text))
            self._cell = None
            self._in_cell = False
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_anchor(anchors_path: Path, anchor_id: str):
    root = json.loads(anchors_path.read_text(encoding="utf-8"))
    anchors = {a["anchor_id"]: a for a in root["anchors"]}
    if anchor_id not in anchors:
        raise ValueError("unknown_anchor_id")
    anchor = anchors[anchor_id]
    expected = [str(x).zfill(5) for x in anchor["expected_additions"]]
    if anchor["expected_additions_count"] != len(expected) or len(set(expected)) != len(expected):
        raise ValueError("anchor_denominator_invalid")
    return root, anchor, expected


def parse_sse_notice(path: Path, expected_codes):
    raw = path.read_bytes()
    decoded = None
    for enc in ("utf-8", "gb18030", "latin1"):
        try:
            decoded = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if decoded is None:
        raise ValueError("notice_decode_failed")
    parser = _TableParser(); parser.feed(decoded)
    additions = {}
    for cells in parser.rows:
        if len(cells) < 4:
            continue
        code = cells[0].strip()
        if not _CODE.fullmatch(code):
            continue
        code = code.zfill(5)
        direction = cells[-1].replace(" ", "")
        if "调入" not in direction:
            continue
        if code in additions:
            raise ValueError("duplicate_notice_addition:" + code)
        additions[code] = {
            "code": code,
            "english_name": cells[1].strip(),
            "chinese_name": cells[2].strip(),
            "direction": "ADD",
        }
    if set(additions) != set(expected_codes):
        missing = sorted(set(expected_codes) - set(additions))
        extra = sorted(set(additions) - set(expected_codes))
        raise ValueError(f"notice_addition_set_mismatch:missing={missing}:extra={extra}")
    return [additions[c] for c in expected_codes]


def _number(text, integer=False):
    if text == "-":
        return None
    cleaned = text.replace(",", "")
    return int(cleaned) if integer else float(cleaned)


def parse_partial_page(path: Path, expected_codes):
    text = text_from_html(path)
    start = text.find("PRV.CLO./")
    if start < 0:
        raise ValueError("quotation_header_missing:" + path.name)
    stop = text.find("SALES RECORD", start)
    section = text[start: stop if stop >= 0 else len(text)]
    lines = section.splitlines()
    expected = set(expected_codes)
    found = {}
    suspended = set()
    malformed = set()
    for i, line in enumerate(lines):
        sm = _SUSPENDED.match(line)
        if sm:
            code = sm.group("code").zfill(5)
            if code in expected:
                suspended.add(code)
            continue
        if i >= len(lines) - 1:
            continue
        m = LINE1.match(line)
        if not m:
            continue
        code = m.group("code").zfill(5)
        if code not in expected:
            continue
        m2 = LINE2.match(lines[i + 1])
        if not m2:
            malformed.add(code)
            continue
        if code in found:
            raise ValueError(f"duplicate_quote:{path.name}:{code}")
        row = {
            "code": code,
            "observed_name": " ".join(m.group("name").split()),
            "currency": m.group("cur"),
            "previous_close": _number(m.group("prev")),
            "closing": _number(m2.group("close")),
            "ask": _number(m.group("ask")),
            "bid": _number(m2.group("bid")),
            "high": _number(m.group("high")),
            "low": _number(m2.group("low")),
            "shares_traded": _number(m.group("shares"), True),
            "turnover": _number(m2.group("turnover"), True),
            "source_page_sha256": file_sha(path),
            "source_snippet": line.rstrip() + "\n" + lines[i + 1].rstrip(),
        }
        required = (row["closing"], row["high"], row["low"], row["shares_traded"])
        row["required_fields_complete"] = all(v is not None for v in required)
        found[code] = row
    return found, suspended, malformed


def _ret(closes, n):
    return (closes[-1] / closes[-1 - n] - 1.0) * 100.0


def feature_from_rows(code, rows, as_of):
    closes = [float(r["closing"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    volumes = [int(r["shares_traded"]) for r in rows]
    returns = [(b / a - 1.0) * 100.0 for a, b in zip(closes[:-1], closes[1:]) if a > 0]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    mean_prev20 = sum(volumes[:-1]) / 20
    recent_high = max(highs[-20:]); recent_low = min(lows[-20:])
    f = {
        "code": code,
        "as_of": as_of,
        "close": round(closes[-1], 6),
        "return_1d_pct": round(_ret(closes, 1), 6),
        "return_5d_pct": round(_ret(closes, 5), 6),
        "return_10d_pct": round(_ret(closes, 10), 6),
        "return_20d_pct": round(_ret(closes, 20), 6),
        "ma5": round(ma5, 6),
        "ma10": round(ma10, 6),
        "ma20": round(ma20, 6),
        "bias_ma5_pct": round((closes[-1] / ma5 - 1.0) * 100.0, 6),
        "bias_ma20_pct": round((closes[-1] / ma20 - 1.0) * 100.0, 6),
        "volume_ratio": round(volumes[-1] / mean_prev20, 6) if mean_prev20 else None,
        "realized_vol20_ann_pct": round(statistics.pstdev(returns) * math.sqrt(252), 6),
        "position_in_20d_range": round((closes[-1] - recent_low) / (recent_high - recent_low), 6) if recent_high > recent_low else None,
        "source": "HKEX Main Board Daily Quotations",
    }
    f["feature_sha256"] = canonical_hash(f)
    return f


def execute(args):
    anchors_path = Path(args.anchors)
    source_dir = Path(args.source_dir)
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    root, anchor, expected_codes = load_anchor(anchors_path, args.anchor_id)
    fetch_receipt = json.loads((source_dir / "source-fetch-receipt.json").read_text())
    if fetch_receipt["anchor_id"] != anchor["anchor_id"] or fetch_receipt["decision_at"] != anchor["decision_at"]:
        raise ValueError("fetch_receipt_anchor_mismatch")
    if fetch_receipt.get("outcome_data_fetched") is not False:
        raise ValueError("outcome_data_boundary_broken")
    sessions = fetch_receipt["selected_sessions"]
    if len(sessions) != root["history_requirement"]:
        raise ValueError("selected_session_count_mismatch")

    notice_path = source_dir / "raw" / "sse-notice.html"
    if file_sha(notice_path) != fetch_receipt["notice_sha256"]:
        raise ValueError("notice_hash_mismatch")
    members = parse_sse_notice(notice_path, expected_codes)
    member_by = {m["code"]: m for m in members}

    rows_by = {code: [] for code in expected_codes}
    failures = {code: [] for code in expected_codes}
    page_evidence = []
    for session in sessions:
        date = session["date"]
        page = source_dir / "raw" / "hkex" / session["file"]
        if file_sha(page) != session["sha256"]:
            raise ValueError("quote_page_hash_mismatch:" + date)
        found, suspended, malformed = parse_partial_page(page, expected_codes)
        page_evidence.append({"date": date, "url": session["url"], "sha256": session["sha256"], "bytes": session["bytes"]})
        for code in expected_codes:
            if code in suspended:
                failures[code].append({"date": date, "reason": "TRADING_SUSPENDED"})
            elif code in malformed:
                failures[code].append({"date": date, "reason": "MALFORMED_QUOTATION_ROW"})
            elif code not in found:
                failures[code].append({"date": date, "reason": "QUOTE_NOT_PRESENT"})
            elif not found[code]["required_fields_complete"]:
                failures[code].append({"date": date, "reason": "REQUIRED_MARKET_FIELD_MISSING"})
            else:
                row = found[code]; row["date"] = date
                rows_by[code].append(row)

    eligible = []
    isolated = []
    features = []
    evidence_rows = {}
    last_session = sessions[-1]["date"]
    for code in expected_codes:
        complete = len(rows_by[code]) == root["history_requirement"] and not failures[code]
        if complete:
            eligible.append(code)
            features.append(feature_from_rows(code, rows_by[code], last_session))
            evidence_rows[code] = rows_by[code]
        else:
            reasons = failures[code]
            isolated.append({
                "code": code,
                "english_name": member_by[code]["english_name"],
                "reason": "INSUFFICIENT_21_PREDECISION_OFFICIAL_BARS",
                "valid_bar_count": len(rows_by[code]),
                "required_bar_count": root["history_requirement"],
                "failures": reasons,
            })
            evidence_rows[code] = rows_by[code]

    if len(eligible) + len(isolated) != len(expected_codes):
        raise ValueError("denominator_accounting_failure")

    cohort = {
        "schema_version": 1,
        "anchor_id": anchor["anchor_id"],
        "notice_date": anchor["notice_date"],
        "decision_at": anchor["decision_at"],
        "source_url": anchor["source_url"],
        "source_notice_sha256": fetch_receipt["notice_sha256"],
        "original_additions_denominator": len(expected_codes),
        "members": members,
    }
    cohort_path = output / "cohort.json"; cohort_path.write_text(json.dumps(cohort, ensure_ascii=False, indent=2))

    coverage = {
        "schema_version": 1,
        "anchor_id": anchor["anchor_id"],
        "denominator": len(expected_codes),
        "eligible_count": len(eligible),
        "isolated_count": len(isolated),
        "eligible_codes": eligible,
        "isolated": isolated,
        "selected_sessions": [s["date"] for s in sessions],
    }
    coverage_path = output / "coverage.json"; coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2))

    evidence = {
        "schema_version": 1,
        "anchor_id": anchor["anchor_id"],
        "page_evidence": page_evidence,
        "member_rows": evidence_rows,
    }
    evidence_path = output / "quote-evidence.json"; evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))

    feature_payload = {
        "anchor_id": anchor["anchor_id"],
        "decision_at": anchor["decision_at"],
        "input_cutoff": anchor["decision_at"].replace("09:00:00", "08:00:00"),
        "original_denominator": len(expected_codes),
        "eligible_count": len(eligible),
        "isolated_count": len(isolated),
        "features": features,
    }
    feature_payload["input_sha256"] = canonical_hash(feature_payload)
    features_path = output / "pit-features.json"; features_path.write_text(json.dumps(feature_payload, ensure_ascii=False, indent=2))

    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    if config.get("config_id") != root["model_config_id"] or config.get("frozen_before_prediction") is not True:
        raise ValueError("model_config_not_frozen")

    quote_bundle_sha = canonical_hash(page_evidence)
    notice_available = anchor["notice_date"] + "T23:59:59+08:00"
    evidence_available = anchor["decision_at"].replace("09:00:00", "08:00:00")
    manifest = {
        "decision_at": anchor["decision_at"],
        "universe": {
            "universe_id": anchor["anchor_id"],
            "effective_at": anchor["decision_at"],
            "available_at": notice_available,
            "content_sha256": file_sha(cohort_path),
            "source": "SSE official notice dated before the decision clock; additions preserved as original denominator",
        },
        "evidence": [{
            "evidence_id": "HKEX_21_PREDECISION_DAILY_QUOTES_" + anchor["anchor_id"],
            "available_at": evidence_available,
            "content_sha256": quote_bundle_sha,
            "source": "HKEX Main Board Daily Quotations; selected pages are all strictly before the decision date and individually hashed",
            "vintage_status": "verified_as_available_then",
        }],
        "model_version": root["model_config_id"],
        "config_sha256": file_sha(config_path),
    }
    receipt = validate_pit_manifest(manifest)
    if receipt["pit_input_admissible"] is not True or receipt["prediction_generated"] is not False:
        raise ValueError("pit_manifest_not_admissible")
    (output / "pit-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (output / "pit-manifest-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))

    package = {
        "schema_version": 1,
        "run_id": root["run_id"],
        "anchor_id": anchor["anchor_id"],
        "decision_at": anchor["decision_at"],
        "original_denominator": len(expected_codes),
        "eligible_count": len(eligible),
        "isolated_count": len(isolated),
        "prediction_generated": False,
        "outcome_data_fetched": False,
        "pit_input_admissible": True,
        "input_sha256": feature_payload["input_sha256"],
        "manifest_sha256": receipt["manifest_sha256"],
        "quote_bundle_sha256": quote_bundle_sha,
        "files": {p.name: file_sha(p) for p in (cohort_path, coverage_path, evidence_path, features_path)},
    }
    package["package_sha256"] = canonical_hash(package)
    (output / "package-manifest.json").write_text(json.dumps(package, ensure_ascii=False, indent=2))
    print("RUN005_ANCHOR_INPUT_OK", json.dumps({
        "anchor_id": anchor["anchor_id"],
        "denominator": len(expected_codes),
        "eligible": len(eligible),
        "isolated": len(isolated),
        "input_sha256": feature_payload["input_sha256"],
        "manifest_sha256": receipt["manifest_sha256"],
    }))
    return package


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--anchors", required=True)
    p.add_argument("--anchor-id", required=True)
    p.add_argument("--source-dir", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    return p


if __name__ == "__main__":
    execute(parser().parse_args())
