"""Fetch pinned reel assets and produce an offline catalog. Uses only Python stdlib and git.

python3 app/prepare_libraries.py --root ../reel-libraries
Use --offline to validate existing checkouts and rebuild the index without fetching.
A dated snapshot of Kaelthas' optional local SVG cache is imported read-only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from repo_paths import OFFICIAL_MEDIA, REPO

SOURCES = {
    'html-components': ('qwwiwi/html-components','f469383e2037521d83c9f7fd653fa79fc87813aa'),
    'russian-brand-logos': ('arturablyazov5-glitch/russian-brand-logos','139ac281ab243fbe7ea412e855e53b3b85c52ab3'),
    'thesvg': ('glincker/thesvg','926287a24607a7e814514e2b99dc6742551a3cf1'),
    'simple-icons': ('simple-icons/simple-icons','801eaab5b70f4933137069397ebbd2ce5f9ad56e'),
}
KAEL_CACHE = None
# Only these exact phrases may trigger automatic insertion. Homonyms require context.
# Keep Russian inflections explicit so similar but unrelated words do not match.
PHRASES = {
    'russian:crm/1c':'1С|1C|один эс|один с',
    'russian:crm/bitrix24':'Битрикс24|Битрикс 24|Bitrix24',
    'russian:crm/moysklad':'МойСклад|Мой склад сервис',
    'russian:bank/sber':'Сбер|Сбера|Сберу|Сбере|Сбербанк|Сбербанка|Сбербанке|Sber|Sberbank',
    'russian:bank/alfa':'Альфа Банк|Альфа-Банк|Альфа Банка|Альфа-Банка|Alfa Bank',
    'russian:bank/tbank':'Т-Банк|Т Банк|Т-Банка|Т-Банке|T-Bank',
    'russian:bank/vtb':'ВТБ|VTB',
    'russian:bank/tochka':'Точка Банк|Банк Точка',
    'russian:pay/mir':'карта Мир|карты Мир|платёжная система Мир',
    'russian:ai/alice':'Яндекс Алиса|Алиса AI|Yandex Alice',
    'russian:ai/gigachat':'Гигачат|GigaChat|Гигачата',
    'russian:pay/yukassa':'ЮKassa|Юкасса|Юкассы|Юкассе|YooKassa',
    'russian:pay/yumoney':'ЮMoney|Юмани|YooMoney',
    'russian:market/ozon':'Ozon|Озон Маркетплейс|на Озоне',
    'russian:market/wildberries':'Wildberries|Вайлдберриз|Вайлдберрис',
    'russian:market/avito':'Avito|Авито',
    'russian:search/yandex':'Яндекс|Яндекса|Яндексе|Yandex',
    'russian:market/yandexmarket':'Яндекс Маркет|Яндекс.Маркет|Yandex Market',
    'russian:cloud/yandexcloud':'Яндекс Облако|Яндекс Облаке|Yandex Cloud',
    'russian:social/vk':'ВКонтакте|VKontakte|VK|ВК',
    'russian:travel/rzd':'РЖД|RZD',
    'russian:docs/gosuslugi':'Госуслуги|Госуслугах',
    'russian:video/rutube':'Rutube|Рутуб|Рутубе',
    'russian:store/rustore':'RuStore|Рустор',
    'russian:map/2gis':'2ГИС|2GIS|ДубльГИС',
    'russian:education/skillbox':'Skillbox|Скиллбокс',
    'russian:pay/sbp':'СБП|система быстрых платежей',
    'thesvg:claude-code':'Claude Code|Клод Код|Клод Коуд',
    'thesvg:codex':'OpenAI Codex|Кодекс OpenAI|Кодекс от OpenAI|OpenAI Кодекс',
    'thesvg:openai':'OpenAI|Open AI|Опен Эй Ай|Опенаи',
    'thesvg:openai-chatgpt':'ChatGPT|Chat GPT|Чат GPT|Чат джи пи ти',
    'thesvg:cursor':'редактор Cursor|Cursor IDE|редактор Курсор',
    'thesvg:github':'GitHub|Гитхаб|Гитхабе|Гитхаба',
    'thesvg:github-copilot':'GitHub Copilot|Гитхаб Копайлот',
    'thesvg:telegram':'Telegram|Телеграм|Телеграме|Телеграма|Телеграмом',
    'thesvg:openrouter':'OpenRouter|Open Router|Опенроутер|Опенроутера',
    'thesvg:perplexity':'Perplexity|Перплексити',
    'thesvg:notion':'Notion|Ноушен|Ноушене|Ноушн',
    'thesvg:midjourney':'Midjourney|Миджорни',
    'thesvg:vercel':'Vercel|Версель',
    'thesvg:supabase':'Supabase|Супабейс',
    'thesvg:firebase':'Firebase|Файрбейс',
    'thesvg:figma':'Figma|Фигма|Фигме|Фигмы',
    'thesvg:adobe':'Adobe|Адоби',
    'thesvg:spotify':'Spotify|Спотифай',
    'thesvg:tiktok':'TikTok|Тикток|Тиктоке',
    'thesvg:instagram':'Instagram|Инстаграм|Инстаграме',
    'thesvg:youtube':'YouTube|Ютуб|Ютубе|Ютуба',
    'thesvg:whatsapp':'WhatsApp|Ватсап|Вотсап',
    'thesvg:mistral-ai':'Mistral AI|Мистраль AI',
    'thesvg:xai-grok':'Grok|Грок|Грока|xAI Grok',
    'thesvg:deepseek':'DeepSeek|Дипсик|Дипсика',
    'thesvg:google':'Google|Гугл|Гугла|Гугле',
    'thesvg:microsoft':'Microsoft|Майкрософт',
    'thesvg:nvidia':'NVIDIA|Нвидиа|Энвидиа',
    'thesvg:ollama':'Ollama|Оллама',
    'thesvg:langchain':'LangChain|Лангчейн',
    'thesvg:elevenlabs':'ElevenLabs|Eleven Labs|Элевенлабс',
    'thesvg:firecrawl':'Firecrawl|Файркроул',
    'thesvg:n8n':'n8n|эн эйт эн',
}
# Context-specific bare terms are recognized only when an editor explicitly identifies a span.
CONTEXT_ALIASES = {'russian:ai/alice':['Алиса'], 'russian:pay/mir':['Мир'], 'russian:bank/tochka':['Точка'],
                   'thesvg:codex':['Codex','Кодекс'],'thesvg:cursor':['Cursor','Курсор']}


def git(path,*args):
    return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()


def checkout(root, name, offline):
    owner, commit=SOURCES[name]
    url='https://github.com/'+owner+'.git'
    path=root/name
    if not path.exists():
        if offline:
            raise ValueError(f'Missing checkout: {name}')
        path.mkdir()
        git(path,'init','-q')
        git(path,'remote','add','origin',url)
        git(path,'fetch','-q','--depth','1','origin',commit)
        git(path,'checkout','-q','--detach',commit)
    if git(path,'rev-parse','HEAD')!=commit or git(path,'status','--porcelain','--untracked-files=no'):
        raise ValueError(f'Unexpected revision or tracked changes in {name}. Use a fresh --root directory.')
    return {'repository':url,'commit':commit}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def record(root,id,name,file,source,alternative_names=()):
    if not file.is_file() or file.suffix!='.svg':
        raise ValueError(f'Missing actual SVG for {id}')
    file.resolve().relative_to(root.resolve())
    auto=PHRASES.get(id,'')
    aliases=auto.split('|') if auto else [name,*alternative_names]
    return {'id':id,'name':name,'aliases':list(dict.fromkeys(a for a in aliases if isinstance(a,str) and a)),
            'file':file.relative_to(root).as_posix(),'source':source,'auto_match':bool(auto),
            'context_aliases':CONTEXT_ALIASES.get(id,[])}


def write_json(path,obj):
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False,encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,separators=(',',':'))
        temp=Path(f.name)
    temp.replace(path)


def install_official_ai_marks(root):
    bundle = OFFICIAL_MEDIA / "ai-brands"
    entries = read_json(bundle / "catalog.json")
    dest = root / "official-media/ai-brands"
    dest.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry["id"] == "official:claude-opus":
            # A full "Claude Opus 5.5" mention must cover both the product
            # prefix and the version. Avoid two crossing partial matches.
            versioned = [phrase for phrase in entry["aliases"] if phrase[-1].isdigit()]
            claude = next(mark for mark in entries if mark["id"] == "official:claude")
            entry["aliases"].extend(f"{name} {phrase}" for name in claude["aliases"] for phrase in versioned)
        source = bundle / entry["file"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Pinned publisher logo checksum mismatch: " + entry["id"])
        target = dest / source.name
        shutil.copyfile(source, target)
        entry["file"] = target.relative_to(root).as_posix()
    return entries


def prepare(root,cache,offline=False):
    root.mkdir(parents=True,exist_ok=True)
    repos={name:checkout(root,name,offline) for name in SOURCES}
    kit=root/'html-components'
    ui=read_json(kit/'CATALOG.json')['components']
    if not all((kit/x['file']).is_file() for x in ui):
        raise ValueError('A component listed by its publisher is missing.')
    repos['html-components'].update(components=len(ui),html_files=len(list(kit.rglob('*.html'))))
    brands=[]
    r=root/'russian-brand-logos'
    ru_meta={x['id']:x for x in read_json(r/'data/catalog.json')['logos']}
    ids=read_json(r/'brands.json')['brands']
    for k in sorted(ids):
        item=ru_meta[k]
        brands.append(record(root,'russian:'+k,item['name'],r/'logos'/(k+'.svg'),'russian-brand-logos',[item.get('name_en')]))
    t=root/'thesvg'
    icons=read_json(t/'src/data/icons.json')
    for item in icons:
        slug=item['slug']
        # Provider badges, country flags and other assets stay available in the checkout.
        if item.get('collection') not in ('brands','community'):
            continue
        path=t/'public'/item['variants']['default'].lstrip('/')
        brands.append(record(root,'thesvg:'+slug,item['title'],path,'thesvg',item.get('aliases',[])))
    simple=root/'simple-icons'
    slugs=dict(re.findall(r'^\| `([^`]+)` \| `([^`]+)` \|$',(simple/'slugs.md').read_text(),re.M))
    titles={slug:name for name,slug in slugs.items()}
    for f in sorted((simple/'icons').glob('*.svg')):
        brands.append(record(root,'simple:'+f.stem,titles.get(f.stem,f.stem),f,'simple-icons'))
    # The pinned catalogs lack amoCRM. Keep the publisher-supplied raster and
    # its provenance in the same audited catalog consumed by logo-company.
    bundle=OFFICIAL_MEDIA/'amocrm'
    if (bundle/'logo.png').is_file():
        dst=root/'official-media/amocrm/logo.png'
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(bundle/'logo.png',dst)
        from source_assets import AMO
        brands.append({'id':'official:amocrm','name':'amoCRM','aliases':list(AMO),
                       'auto_match':True,'file':dst.relative_to(root).as_posix(),
                       'source':'official-brand-site','source_url':'https://www.amocrm.ru/',
                       'sha256':hashlib.sha256(dst.read_bytes()).hexdigest()})
    brands.extend(install_official_ai_marks(root))
    known={b['id'] for b in brands}
    if not set(PHRASES)<=known:
        raise ValueError('Unresolved curated aliases: '+str(sorted(set(PHRASES)-known)))
    dest=root/'kaelthas-cache'
    cached_files=sorted(dest.glob('*.svg'))
    if cache and cache.is_dir():
        cached_files=[]
        dest.mkdir(exist_ok=True)
        for src in sorted(cache.glob('*.svg')):
            if src.is_file() and not src.is_symlink():
                shutil.copyfile(src,dest/src.name)
                cached_files.append(dest/src.name)
    cached=[]
    for src in cached_files:
        slug=re.sub(r'-(default|mono|color|dark|light)$','',src.stem)
        cached.append({'slug':slug,'file':src.relative_to(root).as_posix(),'sha256':hashlib.sha256(src.read_bytes()).hexdigest()})
    by_slug={}
    for c in cached: by_slug.setdefault(c['slug'],[]).append(c)
    indexed={b['id']:b for b in brands}
    for slug,variants in by_slug.items():
        entry=indexed.get('thesvg:'+slug)
        if entry is None:
            first=min(variants,key=lambda v:not v['file'].endswith('-default.svg'))
            entry=record(root,'kaelthas:'+slug,slug,root/first['file'],'kaelthas-cache')
            brands.append(entry)
        entry['kaelthas_variants']=variants
    from brands import safe_svg
    for entry in brands:
        default=root/entry['file']
        if entry['source']=='official-brand-site':
            entry['render_eligible']=True
            continue
        alternatives=[default]
        if entry['source']=='thesvg':
            for stem in ('color','mono','mono-lobe','light','dark','wordmark'):
                candidate=default.parent/(stem+'.svg')
                if candidate.is_file():alternatives.append(candidate)
        for c in entry.get('kaelthas_variants',[]):
            alternatives.append(root/c['file'])
        entry['render_eligible']=False
        for candidate in dict.fromkeys(alternatives):
            try:
                safe_svg(candidate.read_bytes())
            except (ValueError,UnicodeError):
                continue
            entry['render_eligible']=True
            entry['file']=candidate.relative_to(root).as_posix()
            break
    counts={source:sum(b['source']==source for b in brands) for source in ('russian-brand-logos','thesvg','simple-icons','kaelthas-cache')}
    repo_stats={'russian-brand-logos':{'svg_files':len(list((r/'logos').rglob('*.svg')))},
                'thesvg':{'registry_entries':len(icons),'svg_files':len(list((t/'public/icons').rglob('*.svg')))},
                'simple-icons':{'svg_files':len(list((simple/'icons').glob('*.svg')))}}
    for name,stats in repo_stats.items(): repos[name].update(stats)
    result={'schema_version':1,'sources':repos,'counts':counts,'kaelthas_cache_files':len(cached),
            'curated_auto_matches':len(PHRASES),'render_eligible':sum(b['render_eligible'] for b in brands),
            'components':ui,'brands':brands}
    write_json(root/'catalog.json',result)
    return {k:v for k,v in result.items() if k not in ('components','brands')}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root',type=Path,default=REPO.parent/'reel-libraries')
    cli.add_argument('--kaelthas-cache',type=Path,default=KAEL_CACHE)
    cli.add_argument('--offline',action='store_true')
    a=cli.parse_args()
    print(json.dumps(prepare(a.root,a.kaelthas_cache,a.offline),ensure_ascii=False,indent=2))
