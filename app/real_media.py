"""Measure distinct, source-backed screen time within the reel's illustration track."""
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

CHECK = 'real_media_mix'
KINDS = {'website','news','website_screenshot','news_screenshot','screenshot','photo','footage','model3d','3d_model'}
INSTRUCTION = (
    'real_media_mix: minimum 30%, target about 50%, of split/full-visual screen time as recognizable relevant '
    'sourced screenshots, news extracts, photography, footage or rendered sourced 3D. Count only intervals where '
    'the material is a readable focal illustration of the spoken point. Presenter, badges, logo alone, decorative '
    'backgrounds, simulated screenshots and HTML-only cards earn zero. HTML framing is allowed. '
    'For final playback add observed_intervals:[{asset_id,start,end}] to that check (empty if none). '
    'Use the supplied source IDs and only intervals actually recognizable in FINAL. Report a timecoded mismatch '
    'and specific replacement for an irrelevant source, mismatched brand, synthetic lookalike, or unreadable image.'
)


def union(spans):
    joined = []
    for start,end in sorted(spans):
        if end <= start:
            continue
        if joined and start <= joined[-1][1]:
            joined[-1][1] = max(joined[-1][1],end)
        else:
            joined.append([start,end])
    return joined


def intersect(first,second):
    return union((max(a,c),min(b,d)) for a,b in first for c,d in second)


def _span(row):
    a,b=row['start'],row['end']
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (a,b)) or not 0<=a<b:
        raise ValueError('Invalid source media time interval.')
    return a,b


def evidence(manifest, shots):
    manifest=manifest or {}
    assets={}
    for a in manifest.get('assets',[]):
        url=a.get('source_url','')
        if (a.get('id') and a.get('kind') in KINDS and
                (urlsplit(url).scheme in ('http','https') and urlsplit(url).hostname)
                and str(a.get('rights') or '').strip()):
            assets[a['id']]={k:a[k] for k in ('id','kind','source_url','rights','title') if k in a}
    if any(s.get('type') not in ('split','visual','speaker') for s in shots):
        raise ValueError('Unknown shot layout for source media review.')
    graphic=union(_span(s) for s in shots if s['type'] in ('split','visual'))
    placements=[]
    for row in manifest.get('placements',[]):
        if row.get('asset_id') in assets:
            a,b=_span(row)
            placements.extend({'asset_id':row['asset_id'],'start':c,'end':d}
                              for c,d in intersect([(a,b)],graphic))
    return {'assets':list(assets.values()),'placements':placements,'illustration_ranges':graphic}


def review_metrics(proof, observed=None):
    planned=proof['placements']
    if observed is None:
        counted=union(_span(p) for p in planned)
    else:
        spans=[]
        for item in observed:
            span=_span(item)
            same=[_span(p) for p in planned if p['asset_id']==item.get('asset_id')]
            spans.extend(intersect([span],same))
        counted=union(spans)
    total=sum(b-a for a,b in proof['illustration_ranges'])
    actual=sum(b-a for a,b in counted)
    return {'illustration_seconds':round(total,4),'qualified_seconds':round(actual,4),
            'qualified_intervals':counted,'share':actual / total if total else 0.0}


def early_proof(storyboard, src):
    from full_edit import settings
    import sys
    if not storyboard.get('shots'):
        return evidence(storyboard.get('real_media'),[])
    skill,_,_=settings()
    sys.path.insert(0,str(Path(skill)/'scripts'))
    try:
        import reel_plan as rp
        words=[rp.Word(w['w'],w['start'],w['end']) for w in src['words']]
        shots=rp.build_plan(storyboard,words,src['duration']).shots
        rows=[{'start':s.start,'end':s.end,'type':s.type} for s in shots]
    finally:
        sys.path.pop(0)
    return evidence(storyboard.get('real_media'),rows)


def final_proof(video,pre):
    folder=Path(video).parent
    manifest=folder/'real-media.json'
    meta=json.loads((Path(pre).parent/'reel-meta.json').read_text())
    return evidence(json.loads(manifest.read_text()) if manifest.is_file() else {},meta['shots'])


def apply_mix(row,proof,*,final):
    observed=row.get('observed_intervals') if final else None
    if final and not isinstance(observed,list):
        observed=[]
        row.update(verdict='UNVERIFIED', fix='Укажите видимые интервалы материалов с ID источников.')
    metrics=review_metrics(proof,observed)
    row['measurement']=metrics
    if (not metrics['illustration_seconds'] or metrics['share']+1e-12 < .30) and row['verdict']!='UNVERIFIED':
        row['verdict']='REVISE' if proof['assets'] else 'UNVERIFIED'
        row['fix']=(row.get('fix') if row.get('fix') and row.get('fix')!='Не требуется.' else '') or (
            'Подберите и подтвердите источники. Покажите их крупно и по смыслу минимум 30% времени иллюстраций.')
    row['evidence']+=f" Источники: {metrics['qualified_seconds']:g} из {metrics['illustration_seconds']:g} с ({metrics['share']:.1%})."
