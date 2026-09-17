"""Inspect preserved provider bytes; reasoning and error defaults are not answers."""
import hashlib,json

VERSION='O_PROVIDER_COMPLETION_v1'


def inspect_completion(raw):
    if isinstance(raw,bytes):raw=raw.decode('utf-8')
    events=[];codes=[]
    try:
        if raw.lstrip().startswith('{'):events=[json.loads(raw)]
        else:
            for line in raw.splitlines():
                if line.startswith('data:'):
                    data=line[5:].strip()
                    if data and data!='[DONE]':events.append(json.loads(data))
    except (ValueError,TypeError):codes.append('PROVIDER_RESPONSE_PARSE_FAILED')
    contents=[];reasoning=[];finishes=[]
    for event in events:
        for choice in event.get('choices') or []:
            if choice.get('index',0)!=0:codes.append('UNEXPECTED_MULTIPLE_CHOICES');continue
            msg=choice.get('delta') or choice.get('message') or {}
            for field,out in [('content',contents),('reasoning_content',reasoning)]:
                value=msg.get(field)
                if value is not None and not isinstance(value,str):codes.append('PROVIDER_TEXT_TYPE_UNSUPPORTED')
                elif value:out.append(value)
            if choice.get('finish_reason'):finishes.append(choice['finish_reason'])
    content=''.join(contents)
    if not content.strip():codes.append('PROVIDER_FINAL_CONTENT_EMPTY')
    if 'length' in finishes:codes.append('PROVIDER_OUTPUT_TRUNCATED')
    if not finishes or any(x!='stop' for x in finishes):codes.append('PROVIDER_NORMAL_STOP_NOT_PROVEN')
    return {'version':VERSION,'status':'BLOCK' if codes else 'PASS','blockers':list(dict.fromkeys(codes)),
            'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'content_chars':len(content),
            'reasoning_chars':sum(map(len,reasoning)),'finish_reasons':finishes,'raw_mutated':False,'model_requests':0}
