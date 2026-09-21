#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
def run(cmd,cwd=None,env=None,timeout=None):subprocess.check_call(cmd,cwd=cwd,env=env,timeout=timeout)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--research-root',type=Path,required=True);ap.add_argument('--target-session',required=True);ap.add_argument('--snapshot-dir',type=Path,required=True);ap.add_argument('--macro',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--dry-run',action='store_true');a=ap.parse_args()
    root=a.research_root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);u=a.snapshot_dir/'U_UNIVERSE.json'
    macro=json.loads(a.macro.read_text()) if a.macro.exists() else {}
    macro_ready=macro.get('target_session')==a.target_session and (macro.get('result') or {}).get('formal_macro_cap_available') is True and (macro.get('regime') or {}).get('position_ceiling_pct') is not None
    member=out/'U_MEMBER.json';close=out/'U_CLOSE.json'
    run([sys.executable,str(root/'scripts/u_production_daily_member_v1.py'),'--universe',str(u),'--target-session',a.target_session,'--member-out',str(member),'--close-out',str(close)],cwd=root,timeout=3600)
    capital=out/'capital'
    run([sys.executable,str(root/'scripts/collect_hk_capital_evidence.py'),'--target-date',a.target_session,'--cutoff',a.target_session+'T17:20:00+08:00','--output',str(capital)],cwd=root,timeout=180)
    status={'schema_version':1,'target_session':a.target_session,'macro_ready':macro_ready,'real_orders':0}
    if not macro_ready:
        status['state']='WAIT_U_MACRO_AUTHORITY';(out/'STATUS.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status));return
    risk=out/'U_RISK.json';zone=out/'U_ZONE.json';packet=out/'U_PACKET.json'
    run([sys.executable,str(root/'scripts/u_daily_risk_evidence_v1.py'),'--universe',str(u),'--member',str(member),'--capital',str(capital/'receipt.json'),'--macro',str(a.macro.resolve()),'--target-session',a.target_session,'--out',str(risk)],cwd=root)
    run([sys.executable,str(root/'scripts/build_run055_u_strategy_zone_contract.py'),'--facts',str(member),'--handoff',str(u),'--macro',str(a.macro.resolve()),'--risk',str(risk),'--output',str(zone)],cwd=root)
    run([sys.executable,str(root/'scripts/dsa_daily_formal_packet_v1.py'),'--target-session',a.target_session,'--u-close',str(close),'--u-macro',str(a.macro.resolve()),'--u-risk',str(risk),'--u-zone',str(zone),'--out',str(packet)],cwd=root)
    if a.dry_run:
        status['state']='DRY_RUN_PREFLIGHT';(out/'STATUS.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status));return
    formal=out/'formal';formal.mkdir()
    run([sys.executable,str(root/'scripts/run056_u_formal_decision_prod_v1.py'),'--target-session',a.target_session,'--run-id','DSA-U-DAILY-'+a.target_session.replace('-',''),'--scope',str(root/'docs/runtime/RUN056_SCOPE.json'),'--member',str(member),'--close',str(close),'--macro',str(a.macro.resolve()),'--risk',str(risk),'--zone',str(zone),'--out',str(formal)],cwd=root,env=None,timeout=1800)
    p=formal/'SANITIZED_U_FORMAL_RESULT.json';d=json.loads(p.read_text());status.update(state='GENERATED' if str(d.get('state','')).startswith('PASS_FORMAL_U_DECISION') and int(d.get('formal_valid_rows',0))>0 else 'NOT_ACCEPTED',formal_state=d.get('state'),formal_valid_rows=d.get('formal_valid_rows'),qualified_BUY=d.get('qualified_BUY'))
    (out/'STATUS.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n');print(json.dumps(status))
if __name__=='__main__':main()
