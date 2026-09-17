"""Independent U qualitative review of verified dossiers; no O code/results.

Existing user rules only; no fitted weights or strategy promotion. Every raw
request/response remains owner-only. Missing macro/strategy gates cannot be
changed by model prose. Live quote requirements belong to execution, not review.
"""
import argparse
from datetime import datetime,timezone
from decimal import Decimal
import hashlib,json,os
from pathlib import Path
import httpx
from deepseek_flash_cap010_guard import _official_input_tokens,peak_upper_cny
from run_hk_bounded_native_members import private_save,balance
from dsa_drive_store import DriveStore,scoped_token
from o_provider_completion import inspect_completion

VERSION='U_INHERITED_QUALITATIVE_REVIEW_v1'
SYSTEM='''你是升级版U港股中短交易的逐股分析组件，与O原版独立。只使用所给已核验事实及明确缺口，不补外部记忆。遵循用户既有量价趋势、新闻催化、资金潮汐和宏观约束；不引入数值因子权重，不声称胜率。缺乏新利好不是自动否决；没有查到已验证新闻不等于没有风险。资金仅单通道时不能合并，不推断外资或机构身份。宏观缺口不是市场看空结论。
本轮是此前完整日线的盘中工程验收，不是当日盘前预测。宏观仓位上限和完整风险复核未齐时不得给BUY，只能OBSERVE或AVOID。观察分析可验收，不能冒充买入。不得用今日/盘中描述前一日的日线。不得改变Entry-v1/B+C，不能自行定价、假设持仓或新增策略。逐股解释支持与反对条件；第二买点和加仓在冻结模拟账户中禁止。买点不能用获知前价格回填。
只输出JSON对象{"members":[...]}。每项必须有code,decision(OBSERVE或AVOID),trend,news_state,capital_state,evidence_ids,thesis,counterpoint。后三个状态原样复用输入。evidence_ids至少包括本股price和technical证据，可引用本股其他输入ID；禁止新来源。thesis和counterpoint各用简短中文，不能包含任何阿拉伯数字，不重复报价/指标值，不提任何其他股票或未经输入证明的事实。只讨论输入明确支持的趋势、量能和限制。不得输出分数、排名或自由交易点位。覆盖requested_codes恰好每只一次。'''


def validate_member(row,source):
    required={'code','decision','trend','news_state','capital_state','evidence_ids','thesis','counterpoint'}
    if not isinstance(row,dict) or set(row)!=required:raise ValueError('U_REVIEW_SCHEMA')
    if row['code']!=source['code'] or row['decision'] not in ('OBSERVE','AVOID'):raise ValueError('U_REVIEW_DECISION')
    if row['trend']!=source['facts']['trend'] or row['news_state']!=source['news']['state'] or row['capital_state']!=source['capital']['status']:raise ValueError('U_REVIEW_FACT_LABEL_CONFLICT')
    ids=row['evidence_ids'];code=row['code']
    if not isinstance(ids,list) or not {'price:'+code,'technical:'+code}<=set(ids)<=set(source['evidence_ids']):raise ValueError('U_REVIEW_SOURCE_ID')
    import re
    for k in ('thesis','counterpoint'):
        if not isinstance(row[k],str) or not 8<=len(row[k])<=500 or re.search(r'\d',row[k]):raise ValueError('U_REVIEW_UNSUPPORTED_NUMERIC_CLAIM')
    return row


def validate_response(content,members):
    value=json.loads(content)
    if not isinstance(value,dict) or set(value)!={'members'} or not isinstance(value['members'],list):raise ValueError('U_REVIEW_JSON_SCHEMA')
    by={r['code']:r for r in members};seen=set();accepted=[];failures=[]
    for row in value['members']:
        code=row.get('code') if isinstance(row,dict) else None
        if code not in by or code in seen:raise ValueError('U_REVIEW_MEMBER_SET')
        seen.add(code)
        try:accepted.append(validate_member(row,by[code]))
        except ValueError as exc:failures.append({'code':code,'reason':str(exc)})
    for code in sorted(set(by)-seen):failures.append({'code':code,'reason':'U_REVIEW_MEMBER_MISSING'})
    return accepted,failures


def write(p,x):
    with p.open('x') as h:json.dump(x,h,ensure_ascii=False,indent=2,allow_nan=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--scope',type=Path,required=True);p.add_argument('--packet',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    scope=json.loads(a.scope.read_text());packet=json.loads(a.packet.read_text());raw=a.packet.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==scope['packet_sha256'] and packet['U_denominator']==45
    assert os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and os.environ.get('GITHUB_EVENT_NAME')=='push'
    ready=[m for m in packet['members'] if m['status']=='BOUNDED_FACT_REPORT_VERIFIED']
    assert len(ready)==scope['progress_denominator']==44 and scope['maximum_requests']==2
    assert Decimal(scope['maximum_cost_cny'])==Decimal('0.40')
    a.out.mkdir(parents=True,exist_ok=False);summaries=[];total_reserved=Decimal(0);stop=False
    for batch_index in range(2):
        members=ready[batch_index*22:(batch_index+1)*22];root=a.out/('batch'+str(batch_index));root.mkdir()
        run_id=scope['run_id']+'-B'+str(batch_index);artifact=scope['artifact_prefix']+'-B'+str(batch_index)
        summary={'batch':batch_index,'members':len(members),'http_confirmed':0,'http_possible':0,'accepted_reviews':0,'status':'PENDING','actual_charge_cny':None}
        if stop:summary['status']='ISOLATED_AFTER_SHARED_FAILURE';summaries.append(summary);continue
        try:
            inputs=[{k:m[k] for k in ('code','name','data_session','facts','news','capital','evidence_ids')} for m in members]
            body={'model':'deepseek-flash','thinking':{'type':'disabled'},'max_tokens':8192,
                'temperature':0,'stream':False,'response_format':{'type':'json_object'},
                'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({'version':VERSION,'requested_codes':[m['code'] for m in members],'members':inputs,'macro':packet['macro'],'formal_BUY_allowed':False},ensure_ascii=False)}]}
            # Exact official tokenizer plus conservative margin; output cap bounds final content.
            upper=peak_upper_cny(_official_input_tokens(body),8192)
            if upper>Decimal('0.20') or total_reserved+upper>Decimal(scope['maximum_cost_cny']):raise ValueError('U_BUDGET_PRE_SEND_REJECT')
            write(root/'provider-request.json',body)
            write(root/'input-contract.json',{'version':VERSION,'packet_sha256':scope['packet_sha256'],'requested_codes':[m['code'] for m in members],'price_session':packet['target_session'],'input_asof':packet['asof'],'no_formal_signal':True})
            summary['pre_send_upper_cny']=str(upper);summary['pre_send_private']=private_save(root,artifact+'-PRE-SEND',run_id)
            if not summary['pre_send_private']['save_read_hash_restore']:raise ValueError('U_PRIVATE_PRE_SEND_FAILED')
            before=balance()
            if before<upper:raise ValueError('U_AVAILABLE_BALANCE_INSUFFICIENT')
            write(root/'private-balance-before.json',{'balance_cny':str(before),'retrieved_at':datetime.now(timezone.utc).isoformat()})
            with httpx.Client(timeout=30,follow_redirects=False) as c:
                c.headers['Authorization']='Bearer '+scoped_token(c);store=DriveStore(c,os.environ['DSA_DRIVE_FOLDER_ID'])
                claim=store.reserve_native_call(artifact,run_id,hashlib.sha256(raw).hexdigest(),'CI-'+os.environ['GITHUB_RUN_ID']+'-U'+str(batch_index))
            write(root/'private-claim.json',claim);total_reserved+=upper
            write(root/'budget-reservation.json',{'status':'reserved_before_send','upper_cny':str(upper),'actual_charge_cny':None})
            summary['http_possible']=1
            with httpx.Client(timeout=180,follow_redirects=False) as c:
                response=c.post('https://api.deepseek.com/chat/completions',headers={'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']},json=body)
            (root/'provider-response.json').write_bytes(response.content);summary['http_confirmed']=1;summary['http_status']=response.status_code
            response.raise_for_status();provider=response.json();usage=provider.get('usage') or {};summary['usage']=usage
            if type(usage.get('prompt_tokens')) is int and type(usage.get('completion_tokens')) is int:
                estimate=(Decimal(usage['prompt_tokens'])*2+Decimal(usage['completion_tokens'])*8)/1000000
                summary['usage_peak_estimate_cny']=str(estimate)
                if estimate>upper:raise ValueError('U_USAGE_EXCEEDS_RESERVATION')
            audit=inspect_completion(response.content);summary['completion']=audit
            if audit['status']!='PASS':raise ValueError('U_PROVIDER_COMPLETION_REJECT')
            accepted,failures=validate_response(provider['choices'][0]['message']['content'],members)
            write(root/'validated-reviews.json',{'version':VERSION,'accepted':accepted,'failures':failures,
                'qualified_BUY':0,'review_available_at':datetime.now(timezone.utc).isoformat(),'scope':'Bounded qualitative U review; no full macro/strategy/entry acceptance'})
            summary.update(status='BOUNDED_U_REVIEWS_VALIDATED' if not failures else 'PARTIAL_MEMBER_ISOLATION',accepted_reviews=len(accepted),failures=failures)
            try:
                after=balance();write(root/'private-balance-after.json',{'balance_cny':str(after),'retrieved_at':datetime.now(timezone.utc).isoformat()});summary['observed_balance_delta_cny']=str(before-after)
            except Exception:summary['observed_balance_delta_cny']=None
        except Exception as exc:
            summary['status']='ISOLATED';summary['reason']=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else type(exc).__name__
            if summary['http_possible']:stop=True
        finally:
            try:
                write(root/'summary.json',summary);summary['private_persistence']=private_save(root,artifact,run_id)
            except Exception as exc:summary['private_persistence']={'status':'FAIL','reason':type(exc).__name__};stop=True
            summaries.append(summary)
            result={'run_id':scope['run_id'],'workflow_run':os.environ['GITHUB_RUN_ID'],'track':'U','denominator':45,'reviewed_eligible_denominator':44,
                'members':summaries,'http_confirmed':sum(x['http_confirmed'] for x in summaries),'http_possible':sum(x['http_possible'] for x in summaries),
                'bounded_reviews_accepted':sum(x['accepted_reviews'] for x in summaries),'qualified_BUY':0,'orders':0,
                'maximum_cost_cny':scope['maximum_cost_cny'],'actual_charge_cny':None,'public_content':'Metadata only; raw and prose remain owner-only','production_promotion':False}
            (a.out/'SANITIZED_U_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
