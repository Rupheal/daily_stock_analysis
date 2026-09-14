"""Private-journal CLI for existing DSA brief/review tasks; no network calls."""
import argparse
import json
from pathlib import Path
from src.services.dsa_prediction_ledger import canonical_hash
from src.services.dsa_simulation_ledger import new_journal, append, save_atomic, summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--journal',type=Path,required=True)
    p.add_argument('--config',type=Path)
    p.add_argument('--commands',type=Path)
    p.add_argument('--summary',type=Path,required=True)
    args=p.parse_args()
    old=json.loads(args.journal.read_text()) if args.journal.exists() else None
    if old is None and not args.config:
        p.error('Missing journal: recover authoritative persisted version; --config only for authorized initial creation')
    journal=old if old is not None else new_journal(json.loads(args.config.read_text()))
    if args.commands:
        for cmd in json.loads(args.commands.read_text()):journal=append(journal,cmd)
    save_atomic(args.journal,journal,canonical_hash(old) if old is not None else None)
    args.summary.parent.mkdir(parents=True,exist_ok=True)
    args.summary.write_text(json.dumps(summary(journal),ensure_ascii=False,indent=2))
    print(json.dumps({'journal_hash':canonical_hash(journal),'command_count':len(journal['commands']),
                      'model_http_requests':0,'real_orders':0}))

if __name__=='__main__':main()
