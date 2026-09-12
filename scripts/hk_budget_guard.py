"""Durable, fail-closed spending guard for explicitly authorized research batches.

Estimates use all-cache-miss peak rates. Failed/unknown requests retain their
reservation. Request bodies and credentials are never included in the ledger.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock


class ResearchBudget:
    def __init__(self, path, *, limit, carry_upper, max_requests, model, host):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.limit = Decimal(limit)
        self.model, self.host = model, host
        self.max_requests = max_requests
        if not self.limit.is_finite() or self.limit <= 0:
            raise ValueError('Invalid authorized limit')
        carry = Decimal(carry_upper)
        if not carry.is_finite() or not 0 <= carry <= self.limit:
            raise ValueError('Invalid carry-forward amount')
        self.state = {'limit_cny': str(self.limit), 'carry_upper_cny': str(carry),
                      'requests': [], 'actual_account_charge_cny': None}
        # A completed or interrupted batch cannot silently be restarted.
        with self.path.open('x') as handle:
            json.dump(self.state, handle); handle.flush(); os.fsync(handle.fileno())

    def _save(self):
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w') as handle:
            json.dump(self.state, handle, indent=2); handle.flush(); os.fsync(handle.fileno())
        temporary.replace(self.path)

    def admit(self, request, input_validated):
        if request.url.host != self.host:
            if request.url.path.endswith('/chat/completions'):
                raise RuntimeError('Unapproved model endpoint')
            return None
        if request.method != 'POST' or not request.url.path.endswith('/chat/completions'):
            raise RuntimeError('Only the approved completion endpoint is allowed')
        with self.lock:
            if not input_validated:
                raise RuntimeError('Data gate not passed')
            body = json.loads(request.content)
            if body.get('model') != self.model or len(request.content) > 100000:
                raise RuntimeError('Unexpected model or oversized request')
            cap = body.get('max_tokens') or body.get('max_completion_tokens')
            if not isinstance(cap, int) or isinstance(cap, bool) or not 0 < cap <= 8192:
                raise RuntimeError('A bounded output cap is required')
            if body.get('tools') or any(not isinstance(m.get('content'), str) for m in body.get('messages', [])):
                raise RuntimeError('Only text-only native analysis is budgeted')
            # 150k estimated input-token ceiling exceeds the text payload byte
            # cap by 50%; output limit includes reasoning. This is not an invoice.
            upper = (Decimal(150000)*2 + Decimal(cap)*8)/1000000
            used = Decimal(self.state['carry_upper_cny']) + sum(Decimal(x['charge_upper_cny']) for x in self.state['requests'])
            if len(self.state['requests']) >= self.max_requests or used + upper > self.limit:
                raise RuntimeError('Authorized request count or CNY limit exceeded')
            row = {'sequence': len(self.state['requests'])+1,
                   'reserved_at': datetime.now(timezone.utc).isoformat(),
                   'payload_sha256': hashlib.sha256(request.content).hexdigest(),
                   'payload_bytes': len(request.content), 'output_cap': cap,
                   'reserved_cny': str(upper), 'charge_upper_cny': str(upper),
                   'status': 'reserved_before_send', 'usage': None}
            self.state['requests'].append(row)
            self._save()
            return row['sequence']

    def settle(self, sequence, usage, status):
        with self.lock:
            row = self.state['requests'][sequence-1]
            row['status'], row['usage'] = status, usage
            if usage:
                inp, out = usage.get('prompt_tokens'), usage.get('completion_tokens')
                if all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (inp, out)):
                    peak = (Decimal(inp)*2 + Decimal(out)*8)/1000000
                    row['usage_peak_estimate_cny'] = str(peak)
                    # Never release unknown/failed charges and never silently
                    # accept provider usage beyond the reservation.
                    if peak > Decimal(row['reserved_cny']):
                        row['charge_upper_cny'] = str(peak)
                        self._save()
                        raise RuntimeError('Provider usage exceeded reserved estimate; stop batch')
                    if status == 'response_received':
                        row['charge_upper_cny'] = str(peak)
            self._save()


def decode_usage(raw):
    """Accept native JSON or SSE transport without rewriting its content."""
    try:
        value = json.loads(raw)
        return value.get('usage')
    except (ValueError, AttributeError):
        usage = None
        for line in raw.splitlines():
            if not line.startswith('data: '):
                continue
            try:
                packet = json.loads(line[6:])
                if packet.get('usage'):
                    usage = packet['usage']
            except ValueError:
                continue
        return usage
