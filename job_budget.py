"""Per-montage OpenRouter billing. A durable reservation precedes every paid POST."""
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import fcntl
import json
import math
import os
from pathlib import Path

LIMIT = Decimal('2')
MIN_OUTPUT_TOKENS = 1024
# Keep room for quality review while the director chooses and repairs scenes.
REVIEW_ALLOWANCE = Decimal('0.24')


class BudgetExceeded(ValueError):
    pass


class BillingUnknown(ValueError):
    pass


def _known_spend(path):
    used = Decimal(0)
    known = True
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line, parse_float=Decimal)
                cost = row['usage']['cost']
                if 'id' in row and not row['id'] and not (row.get('status')=='payload_rejected' and row.get('http_status')==413 and cost==0):
                    known = False
                if type(cost) not in (int, Decimal) or not Decimal(cost).is_finite() or cost < 0:
                    raise ValueError()
                used += cost
            except (KeyError, ValueError, TypeError, InvalidOperation):
                known = False
    return used, known and not path.with_suffix('.pending').exists()


def budget_snapshot(audit_path):
    used, known = _known_spend(Path(audit_path))
    return {'limit_usd': float(LIMIT), 'used_usd': float(used),
            'remaining_usd': float(max(LIMIT - used, 0)) if known else None}


def input_bound(messages, media_durations):
    # The two text fields are UTF-8 byte bounded. Reserve extra tokens for
    # templating/system overhead. Never tokenize a base64 transport envelope.
    total = 4096
    clips = 0
    for message in messages:
        value = message['content']
        if isinstance(value, str):
            total += len(value.encode())
            continue
        for part in value:
            if part['type'] == 'text':
                total += len(part['text'].encode()) + 64
            elif part['type'] == 'video_url':
                clips += 1
            else:
                raise ValueError('Неизвестная тарификация вложения.')
    if clips != len(media_durations):
        raise ValueError('Для расчёта бюджета нужны длительности всех видео.')
    # Gemini static video defaults to 1 FPS, 258 visual tokens/frame, 32 audio
    # tokens/second plus timestamps. Use 512/sec and two extra boundary frames.
    # https://ai.google.dev/gemini-api/docs/generate-content/video-understanding
    for seconds in media_durations:
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Неизвестна длительность видео для расчёта бюджета.')
        total += (math.ceil(seconds) + 2) * 512
    return total


def _rates(evidence):
    # No tools, cache controls, plugins or additional model calls are enabled.
    prices = evidence['listed_prices']
    input_keys = ('prompt','image','audio','video','input_audio_cache','input_cache_read',
                  'input_cache_write','input_cache_write_1h')
    output_keys = ('completion','internal_reasoning')
    supported = {*input_keys, *output_keys, 'request','web_search','discount'}
    parsed = {k: Decimal(str(v)) for k,v in prices.items()}
    if any(not v.is_finite() or v < 0 for v in parsed.values()):
        raise ValueError('Некорректная цена маршрута.')
    if parsed.get('request', 0) or any(v for k,v in parsed.items() if k not in supported):
        raise ValueError('Цена маршрута содержит неподдерживаемые доплаты.')
    return (max(parsed.get(k, parsed['prompt']) for k in input_keys),
            max(parsed.get(k, parsed['completion']) for k in output_keys))


@dataclass
class Reservation:
    details: dict
    upper: Decimal
    verified: bool = False
    logged: bool = False

    def confirm(self, cost):
        if Decimal(str(cost)) > self.upper:
            raise BillingUnknown('Списание превысило резерв. Требуется сверка тарифа.')
        self.verified = True


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def billable_request(audit, body, evidence, stage, media_durations, weekly_remaining=None):
    audit.parent.mkdir(parents=True, exist_ok=True)
    pending = audit.with_suffix('.pending')
    with audit.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        used, known = _known_spend(audit)
        if not known:
            raise BillingUnknown('Сумма предыдущего списания ещё не подтверждена. Платный запрос остановлен.')
        in_rate, out_rate = _rates(evidence)
        max_input = input_bound(body['messages'], media_durations)
        input_usd = max_input * in_rate
        remaining = LIMIT - used
        if weekly_remaining is not None:
            remaining=min(remaining,weekly_remaining)
        holdback = REVIEW_ALLOWANCE
        proof = audit.with_name('compact-final-reserve.json')
        if proof.is_file():
            from compact_review import reserve_usd
            media = json.loads(proof.read_text())
            holdback = Decimal(str(reserve_usd(media['final_seconds'], media['reference_seconds'])))
        if stage == 'argon-review':
            holdback = Decimal(0)
        after_input = remaining - holdback - input_usd
        if out_rate and after_input > 0:
            body['max_tokens'] = min(body['max_tokens'], int(after_input / out_rate))
        if after_input < 0 or body['max_tokens'] < MIN_OUTPUT_TOKENS:
            if weekly_remaining is not None and weekly_remaining < LIMIT-used:
                raise BudgetExceeded(f'Недельного остатка ключа ${remaining:.4f} недостаточно для этой операции с резервом на проверку. '
                                     f'На ролик потрачено ${used:.4f} из ${LIMIT}.')
            raise BudgetExceeded(f'Лимит монтажа $2. Учтено ${used:.4f}, остаток ${max(0,remaining):.4f}. '
                                 'Для безопасного запроса с учётом проверки средств недостаточно.')
        upper = input_usd + body['max_tokens'] * out_rate
        if upper + holdback > remaining:
            raise BudgetExceeded('Недостаточно остатка бюджета на этот запрос.')
        details = {'limit_usd':float(LIMIT), 'used_before_usd':float(used),
                   'max_request_usd':float(upper), 'max_input_tokens':max_input,
                   'max_output_tokens':body['max_tokens']}
        # If this process dies before writing a settled ledger row, the next
        # worker must reconcile the request, even after a machine restart.
        with pending.open('x') as marker:
            json.dump(details, marker)
            marker.flush()
            os.fsync(marker.fileno())
        sync_directory(audit.parent)
        reservation = Reservation(details, upper)
        synced = False
        try:
            with audit.open('a',encoding='utf-8') as ledger:
                try:
                    yield reservation, ledger
                finally:
                    ledger.flush()
                    os.fsync(ledger.fileno())
                    synced = True
        finally:
            # Incomplete/malformed model output can still have a confirmed
            # charge. Only release after its ledger row is durably present.
            if reservation.verified and reservation.logged and synced:
                pending.unlink()
                sync_directory(audit.parent)
