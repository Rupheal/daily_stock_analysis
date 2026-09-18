"""Run028-only pre-send DeepSeek Flash cost guard.

Uses DeepSeek's official V4.1 prompt recipe/tokenizer to count the concrete
OpenAI-format chat request before any provider send.  Peak CNY rates are used
regardless of time of day, plus an input-token safety margin.  This module only
patches the external research budget gate; it does not modify frozen upstream
prompts, model parameters, strategy logic or provider responses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os

VERSION = "DSA_DEEPSEEK_FLASH_CAP010_v1"
HARD_CAP_CNY = Decimal("0.10")
AUTHORIZED_CEILING_ENV = "DSA_AUTHORIZED_PER_MEMBER_CNY"
ALLOW_ESCALATION_ENV = "DSA_ALLOW_CAP_ESCALATION"
PEAK_INPUT_CNY_PER_M = Decimal("2")
PEAK_OUTPUT_CNY_PER_M = Decimal("8")
DEFAULT_INPUT_MARGIN_TOKENS = 2048
TOKENIZER_REPO_COMMIT = "8cadfede7063c896b944e7bae05daa3549ae97ea"


def peak_upper_cny(input_tokens: int, output_cap: int, *, margin_tokens: int = DEFAULT_INPUT_MARGIN_TOKENS) -> Decimal:
    if type(input_tokens) is not int or input_tokens < 0:
        raise ValueError("INVALID_INPUT_TOKEN_COUNT")
    if type(output_cap) is not int or output_cap <= 0:
        raise ValueError("INVALID_OUTPUT_TOKEN_CAP")
    if type(margin_tokens) is not int or margin_tokens < 0:
        raise ValueError("INVALID_TOKEN_MARGIN")
    return ((Decimal(input_tokens + margin_tokens) * PEAK_INPUT_CNY_PER_M)
            + (Decimal(output_cap) * PEAK_OUTPUT_CNY_PER_M)) / Decimal(1_000_000)


def _official_input_tokens(body: dict) -> int:
    path = os.environ.get("DSA_DEEPSEEK_V41_TOKENIZER")
    if not path:
        raise RuntimeError("OFFICIAL_TOKENIZER_PATH_MISSING")
    from deepseek_recipe import ChatCompletionRequest, ConversionOptions, DeepseekV41Encoding, Tokenizer

    # Only fields that determine the rendered conversation are supplied.  The
    # output cap/temperature/stream transport do not add prompt tokens.
    request = ChatCompletionRequest({"model": body.get("model"), "messages": body.get("messages")})
    converted = request.convert(ConversionOptions())
    tokenizer = Tokenizer.from_file(path)
    encoding = DeepseekV41Encoding().with_tokenizer(tokenizer)
    token_ids = encoding.encode(converted.conversation)
    count = len(token_ids)
    if count <= 0:
        raise RuntimeError("OFFICIAL_TOKENIZER_EMPTY_RESULT")
    return count


def install_into_budget_guard():
    import hk_budget_guard as guard

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
            expected_thinking = os.environ.get('DSA_EXPECT_THINKING')
            if expected_thinking and body.get('thinking') != {'type': expected_thinking}:
                raise RuntimeError('NATIVE_CONFIG_NOT_PRESENT_ON_WIRE')
            if body.get('model') != self.model or self.model != 'deepseek-flash':
                raise RuntimeError('Unexpected model')
            if len(request.content) > 100000:
                raise RuntimeError('Oversized request')
            cap = body.get('max_tokens') or body.get('max_completion_tokens')
            if not isinstance(cap, int) or isinstance(cap, bool) or not 0 < cap <= 8192:
                raise RuntimeError('A bounded output cap is required')
            if body.get('tools') or any(not isinstance(m.get('content'), str) for m in body.get('messages', [])):
                raise RuntimeError('Only text-only native analysis is budgeted')
            allow_escalation = os.environ.get(ALLOW_ESCALATION_ENV) == '1'
            authorized_ceiling = Decimal(os.environ.get(AUTHORIZED_CEILING_ENV, str(HARD_CAP_CNY)))
            if not authorized_ceiling.is_finite() or authorized_ceiling < HARD_CAP_CNY:
                raise RuntimeError('INVALID_AUTHORIZED_CNY_CEILING')
            if self.limit != HARD_CAP_CNY:
                if not allow_escalation or self.limit < HARD_CAP_CNY or self.limit > authorized_ceiling:
                    raise RuntimeError('RUN028_LIMIT_OUTSIDE_AUTHORIZED_CEILING')
            if Decimal(self.state['carry_upper_cny']) != 0:
                raise RuntimeError('RUN028_REQUIRES_ZERO_CARRY')
            if len(self.state['requests']) >= 1 or self.max_requests != 1:
                raise RuntimeError('RUN028_SINGLE_REQUEST_ONLY')

            input_tokens = _official_input_tokens(body)
            margin = int(os.environ.get('DSA_INPUT_TOKEN_MARGIN', str(DEFAULT_INPUT_MARGIN_TOKENS)))
            upper = peak_upper_cny(input_tokens, cap, margin_tokens=margin)
            if upper > self.limit:
                if os.environ.get('DSA_BUDGET_PROBE_ONLY') == '1' and allow_escalation and upper <= authorized_ceiling:
                    row = {
                        'sequence': 1,
                        'reserved_at': datetime.now(timezone.utc).isoformat(),
                        'payload_sha256': hashlib.sha256(request.content).hexdigest(),
                        'payload_bytes': len(request.content),
                        'output_cap': cap,
                        'official_v41_input_tokens': input_tokens,
                        'input_token_safety_margin': margin,
                        'peak_input_cny_per_m': str(PEAK_INPUT_CNY_PER_M),
                        'peak_output_cny_per_m': str(PEAK_OUTPUT_CNY_PER_M),
                        'pre_send_peak_upper_cny': str(upper),
                        'required_cap_cny': str(upper),
                        'hard_cap_cny': str(self.limit),
                        'authorized_ceiling_cny': str(authorized_ceiling),
                        'reserved_cny': '0',
                        'charge_upper_cny': '0',
                        'status': 'dry_envelope_requires_cap_raise',
                        'usage': None,
                    }
                    self.state['requests'].append(row)
                    self._save()
                    raise RuntimeError('RUN028_DRY_ENVELOPE_REQUIRES_CAP_RAISE')
                raise RuntimeError('RUN028_CNY_PRE_SEND_CAP_EXCEEDED')

            row = {
                'sequence': 1,
                'reserved_at': datetime.now(timezone.utc).isoformat(),
                'payload_sha256': hashlib.sha256(request.content).hexdigest(),
                'payload_bytes': len(request.content),
                'output_cap': cap,
                'official_v41_input_tokens': input_tokens,
                'input_token_safety_margin': margin,
                'peak_input_cny_per_m': str(PEAK_INPUT_CNY_PER_M),
                'peak_output_cny_per_m': str(PEAK_OUTPUT_CNY_PER_M),
                'pre_send_peak_upper_cny': str(upper),
                'hard_cap_cny': str(self.limit),
                'authorized_ceiling_cny': str(authorized_ceiling),
                'tokenizer_repo_commit': TOKENIZER_REPO_COMMIT,
                # Reserve the full authorized hard cap so settle() can only
                # tighten it after actual provider usage is returned.
                'reserved_cny': str(self.limit),
                'charge_upper_cny': str(self.limit),
                'status': 'reserved_before_send',
                'usage': None,
            }
            self.state['requests'].append(row)
            self._save()
            if os.environ.get('DSA_BUDGET_PROBE_ONLY') == '1':
                row['status'] = 'dry_envelope_validated_not_sent'
                self._save()
                raise RuntimeError('RUN028_DRY_ENVELOPE_COMPLETE_NO_SEND')
            return 1

    guard.ResearchBudget.admit = admit
    return {
        'version': VERSION,
        'hard_cap_cny': str(HARD_CAP_CNY),
        'peak_input_cny_per_m': str(PEAK_INPUT_CNY_PER_M),
        'peak_output_cny_per_m': str(PEAK_OUTPUT_CNY_PER_M),
        'input_token_margin': DEFAULT_INPUT_MARGIN_TOKENS,
        'tokenizer_repo_commit': TOKENIZER_REPO_COMMIT,
        'model_requests': 0,
        'runtime_activated': False,
    }
