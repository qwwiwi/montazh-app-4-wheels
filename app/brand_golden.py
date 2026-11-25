"""Cross-check Argon's observed logo cues against the timed, resolved asset manifest."""
import math
import json
from functools import lru_cache
from repo_paths import OFFICIAL_MEDIA

CHECK = 'brand_identity_timing'
FAMILY = {
    'official:claude': 'Claude', 'official:claude-opus': 'Claude',
    'official:anthropic': 'Anthropic', 'official:gemini': 'Gemini',
}
@lru_cache(maxsize=1)
def pinned_assets():
    catalog = OFFICIAL_MEDIA/'ai-brands'/'catalog.json'
    return {item['id']:item for item in json.loads(catalog.read_text())}

PLAN_RULE = (
    'For a meaningful first introduction or a new comparison, plan a genuine publisher logo on the spoken '
    'phrase. Claude Opus uses the Claude family mark, with Opus as model text if useful. Gemini Neon uses '
    'the Gemini mark. Anthropic is the company: use its mark only when the company itself is discussed. '
    'Avoid decorative parent marks and repetitive flashes. Resolve ambiguous ASR from context. '
    'Keep later duplicate omissions specific and word-anchored. Never invent a product icon.'
)
FINAL_RULE = (
    PLAN_RULE + ' For brand_identity_timing independently listen for names even with an empty cue list; '
    'inspect actual pixels. Check correct entity, authentic silhouette, proportions, recognizable dwell at '
    'delivery speed, contrast, and clearance from face, captions and platform controls. Text, a fake star, '
    'or a tiny logo incidentally present in an article screenshot cannot pass as the intended cue. On PASS '
    'include observed_logos:[{id:exact manifest id,start:visible onset,end:visible exit,evidence:visible '
    'shape and location}] for each distinct resolved brand, at its meaningful mention. Missing, late, wrong '
    'or unreadable mark: REVISE with exact FINAL start/end, observed defect and a concrete edit for Opus. '
    'Use UNVERIFIED when playback or origin cannot establish identity. With no meaningful brand, say so.'
)


def proof(transcript, report):
    report = report or {}
    fields = ('id','name','spoken','start','end','source','source_url','sha256','file')
    cues = [{key: row.get(key) for key in fields} for row in report.get('mentions', [])]
    # Unambiguous spellings are an additional backstop if resolution or model evidence is empty.
    # The reviewer identifies other brands and contextual model names directly from the audio.
    first = {}
    aliases = {alias.casefold(): FAMILY[ident] for ident,item in pinned_assets().items()
               if ident in FAMILY for alias in item.get('aliases', []) if ' ' not in alias}
    for word in transcript['words']:
        token = str(word.get('w','')).casefold().strip('.,!?:;—«»"()')
        entity=aliases.get(token)
        if entity and entity not in first:
            first[entity] = [word['start'],word.get('end',word['start'])]
    return {'cues': cues, 'first_mentions': first, 'unresolved': report.get('unresolved', []),
            'omissions': report.get('editorial_omissions', [])}


def _valid_observation(row, cue, duration):
    if not isinstance(row, dict) or row.get('id') != cue.get('id'):
        return False
    a,b=row.get('start'),row.get('end')
    return (all(type(n) in (float,int) and math.isfinite(n) for n in (a,b))
            and 0<=a<b<=duration+.05 and a<cue['end'] and b>cue['start']
            and isinstance(row.get('evidence'),str) and bool(row['evidence'].strip()))


def apply(row, evidence, duration):
    if row['verdict'] != 'PASS':
        return
    cues=evidence['cues']
    by_id={}
    for cue in cues:
        by_id.setdefault(cue['id'],[]).append(cue)
    def reject(span, fix):
        row.update(verdict='REVISE',start=span[0],end=span[1],evidence=fix,fix=fix)
    for family,span in evidence['first_mentions'].items():
        if not any(FAMILY.get(key)==family for key in by_id):
            reject(span, f'Для упоминания {family} отсутствует подтверждённый знак. Добавьте фирменный логотип на указанную фразу.')
            return
    observations=row.get('observed_logos',[])
    for ident, mentions in by_id.items():
        verified=[]
        for cue in mentions:
            if not (cue['source'] and cue['file'] and cue['name']):
                continue
            pin=pinned_assets().get(ident)
            if ident in FAMILY and (not pin or any(cue[key]!=pin[key] for key in ('source','source_url','sha256'))):
                continue
            verified.append(cue)
        if not verified or not isinstance(observations,list) or not any(
                _valid_observation(obs,cue,duration) for obs in observations for cue in verified):
            cue=mentions[0]
            reject((cue['start'],cue['end']), f'Для {cue["name"]} отсутствует подтверждение происхождения или совпадения видимого знака с речью. Сверьте файл и покажите читаемый знак на этой фразе.')
            return
