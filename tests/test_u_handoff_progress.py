import hashlib,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_current_u45_handoff import audit
ROOT=Path(__file__).parents[1]


def test_new_handoff_exposes_real_progress_without_pretending_to_buy():
    d=json.loads((ROOT/'docs/runtime/RUN047_U45_HANDOFF.json').read_text())
    assert d['bounded_U_reports_verified']==d['bounded_U_model_reviews_accepted']==d['conditional_policy_plans']==44
    assert len(d['rows'])==45 and d['formal_U_accepted']==0
    assert all('CURRENT_ENTRY_EXECUTION_SIDECAR_MISSING' not in r['failures'] for r in d['rows'])
    assert d['runtime_authorization_is_not_a_data_gate']
    m=ROOT/'docs/runtime/RUN047_U_RELEASE_ACCEPTANCE.json'
    assert d['source_sha256']['model_review']==hashlib.sha256(m.read_bytes()).hexdigest()


def test_old_receipt_preserved_with_old_scope():
    d=json.loads((ROOT/'docs/runtime/RUN038_U45_HANDOFF_AUDIT.json').read_text())
    assert d['formal_U_accepted']==0 and d['feature_input_21_ready']==44
    assert d['failure_counts']['FORMAL_U_SIGNAL_ARTIFACT_MISSING']==45
