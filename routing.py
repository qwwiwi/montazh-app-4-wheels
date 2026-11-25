"""Price-only guard for the two interactive Chat Completions models."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from urllib.request import urlopen

# USD per million tokens. Do not follow a tariff increase silently.
CEILINGS = {'anthropic/claude-opus-5.5': (4,20), 'google/gemini-4-argon': (1,5)}
MILLION = Decimal(10**6)


def select(model, endpoints):
    cap_in,cap_out = CEILINGS[model]
    quoted=[]
    for endpoint in endpoints:
        price=endpoint['pricing']
        rates=tuple(Decimal(price[k])*MILLION for k in ('prompt','completion'))
        if any(not v.is_finite() or v<0 for v in rates): raise ValueError('Неизвестная цена OpenRouter.')
        if not endpoint.get('tag'):raise ValueError('OpenRouter не указал маршрут.')
        quoted.append((rates,endpoint))
    if not quoted:raise ValueError('Каталог провайдеров пуст.')
    minimum=tuple(min(r[i] for r,e in quoted) for i in (0,1))
    if minimum[0]>cap_in or minimum[1]>cap_out:
        raise ValueError('Минимальный тариф выше зафиксированного потолка.')
    for rates,e in sorted(quoted,key=lambda pair:pair[1]['tag']):
        if rates!=minimum or e.get('status')!=0:continue
        price=e['pricing']
        if Decimal(price.get('request','0'))!=0:continue
        if model.startswith('google/') and any(Decimal(price.get(k,price['prompt']))*MILLION>minimum[0] for k in ('audio','image','video')):continue
        if Decimal(price.get('internal_reasoning',price['completion']))*MILLION>minimum[1]:continue
        if 'response_format' not in e.get('supported_parameters',[]):continue
        if model.startswith('anthropic/') and 'reasoning' not in e.get('supported_parameters',[]):continue
        tier=e.get('service_tier')
        if tier not in (None,'default','flex'):continue
        p={'only':[e['tag']],'order':[e['tag']],'allow_fallbacks':False,'require_parameters':True,
           'max_price':{'prompt':float(minimum[0]),'completion':float(minimum[1]),'request':0}}
        options={'provider':p}
        if tier=='flex':options['service_tier']='flex'
        return {'body_overrides':options,'evidence':{'model':model,'endpoint':e['tag'],'tier':tier or 'default',
                'checked_at':datetime.now(timezone.utc).isoformat(),'usd_per_million':[float(v) for v in rates],
                'listed_prices':price}}
    raise ValueError('Нет доступного маршрута одновременно с минимальной ценой входа и выхода.')


def cheapest_route(model):
    if model not in CEILINGS:raise ValueError('Модель не разрешена для рилсов.')
    try:
        with urlopen('https://openrouter.ai/api/v1/models/'+model+'/endpoints',timeout=15) as response:
            endpoints=json.load(response)['data']['endpoints']
        return select(model,endpoints)
    except (OSError,KeyError,ArithmeticError,TypeError) as e:
        raise ValueError('Стоимость маршрута не подтверждена. Платный запрос остановлен.') from e
