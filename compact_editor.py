"""Request narrow editorial decisions on a mechanically transferred Opus plan."""
from copy import deepcopy
import json
from pathlib import Path
import re

from model_stages import OPUS, model_call, transcript, validate_storyboard

# Existing scene copy and geometric parameters the native renderer understands.
EDITABLE = {'text','what','label','title','eyebrow','center','mark','detail_label','tag','h','p','x','y','cps'}
ANCHOR_KEYS = {'word','after','before','nth','plus','edge'}


def _fields(value, path=()):
    if isinstance(value, dict):
        if 'word' in value and set(value) <= ANCHOR_KEYS:
            return
        for key, child in value.items():
            if key in EDITABLE and type(child) in (float, int, str):
                yield path + (key,), child
            else:
                yield from _fields(child, path+(key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _fields(child, path+(index,))


def _norm(text):
    return ''.join(re.findall('[0-9a-zа-яё]+',text.lower()))


def _rebind(node, old, new):
    if isinstance(node, list):
        for item in node:
            _rebind(item,old,new)
    elif isinstance(node, dict):
        if 'word' in node and set(node) <= ANCHOR_KEYS:
            hits=[i for i,w in enumerate(old) if _norm(w['w'])==_norm(node['word'])
                  and node.get('after',0)-1e-6 <= w['start'] < node.get('before',float('inf'))]
            index=hits[node.get('nth',0)]
            node.update(word=new[index]['w'], after=old[index]['start'], before=old[index]['start']+0.0001)
            node.pop('nth',None)
        else:
            for item in node.values():
                _rebind(item,old,new)


def _affected_shots(notes, words_path, issues, plan):
    # Review timestamps come from the previous render. Project through its original shot IDs.
    origin=Path(words_path).parent/'origin.json'
    mapped={int(k):int(v) for k,v in notes.get('surviving_shots',{}).items()}
    ids=set()
    if origin.is_file():
        review=Path(words_path).parent.parent/json.loads(origin.read_text())['review']
        meta=review.parent/'project/reel-meta.json'
        if meta.is_file():
            for i,shot in enumerate(json.loads(meta.read_text())['shots']):
                if i in mapped and any(shot['start']<=point<shot['end'] for row in issues
                                       for point in (row.get('start',-1),row.get('end',-1)-.05)):
                    ids.add(mapped[i])
    # A review may additionally mention the exact obstructing label in its observation.
    observations=' '.join(str(r.get('evidence','')) for r in issues).casefold()
    for scene in plan['scenes']:
        if any(isinstance(v,str) and len(v)>2 and ('«'+v.casefold()+'»') in observations
               for _,v in _fields(scene)):
            ids.add(scene['shot'])
    return ids


def direct_mapped(plan, notes, words_path, skill, audit, findings):
    """Return the revised native plan and transcript, without mutating inputs or writing files."""
    src=transcript(words_path)
    rows=findings.get('checks',[]) if isinstance(findings,dict) else findings or []
    issues=[r for r in rows if r.get('verdict')!='PASS' and r.get('id') in
            {'brand_text','spelling','captions','readability','attention_focus','phrase_visuals','coverage','motion_density','closing_action','attention_rhythm','real_media_mix'}]
    affected=_affected_shots(notes,words_path,issues,plan)
    slots=[]
    choices=[]
    for index,scene in enumerate(plan['scenes']):
        if scene['shot'] not in affected:
            continue
        for path,value in _fields(scene):
            slots.append((index,path,value))
            choices.append([len(slots)-1,scene['shot'],'.'.join(map(str,path)),value])
    evidence=[(r.get('id'),r.get('fix','')[:260]) for r in issues]
    survivors={int(k):v for k,v in notes.get('surviving_shots',{}).items()}
    short=[{'shot':survivors[row['old_shot']],'start':row['start'],'end':row['end']}
           for row in notes.get('compressed_shots',[]) if row.get('old_shot') in survivors]
    brief={
        'instruction':('You are the editor. Your earlier storyboard is mechanically synchronized to the new approved speech cut. '
                       'Approve unchanged choices or revise only relevant copy / positions in slots. Address actionable old review findings that still apply. '
                       'Use short labels to fit narrow tabs, visible legible phone copy. Fix misleading ASR spellings in captions only if grounded in reviewer evidence '
                       'and spoken words. Each correction is one indexed subtitle token. Keep meaning and all timings. Do not invent facts. '
                       'When adjacent ASR tokens are misheard preserve their count. Return compact JSON with fields '
                       '{"slots":[[slot_id,new_value]],"captions":[[word_index,corrected_token]]}; either array can be empty. For subsecond shots listed in compressed_shots you may add "merge_into_previous":[shot_id,...] if removing these flashes improves continuity. No commentary.'),
        'findings':evidence,'scenes':[[s['shot'],s['kind']] for s in plan['scenes']],
        'compressed_shots':short,'slots':choices,'spoken_words_in_order':[w['w'] for w in src['words']]}
    if notes.get('available_source'):
        brief['available_source']=notes['available_source']
        brief['instruction']+=' Also return source_cues with the word_index and duration (seconds) of relevant source cutaways.'
    reply=model_call('opus-compact',OPUS,json.dumps(brief,ensure_ascii=False,separators=(',',':')),audit,output_token_limit=2500)
    updated=deepcopy(plan)
    if notes.get('available_source') and 'source_cues' in reply:
        updated['source_cues']=reply['source_cues']
    src=deepcopy(src)
    old=deepcopy(src['words'])
    if not isinstance(reply,dict) or not all(isinstance(reply.get(k),list) for k in ('slots','captions')):
        raise ValueError('Opus returned an invalid compact editorial decision.')
    for key,values in [('slots',slots),('captions',old)]:
        seen=set()
        for pair in reply[key]:
            if not isinstance(pair,list) or len(pair)!=2:
                raise ValueError('Invalid editorial edit.')
            i,value=pair
            if type(i) is not int or not 0<=i<len(values) or i in seen:
                raise ValueError('Unknown or repeated editorial index.')
            seen.add(i)
            if key=='captions':
                if not isinstance(value,str) or len(value.split())!=1 or not _norm(value) or len(value)>64:
                    raise ValueError('Caption correction must preserve token alignment.')
                src['words'][i]['w']=value
                continue
            index,path,prior=slots[i]
            if isinstance(prior,str):
                if not isinstance(value,str) or not value.strip() or len(value)>160:
                    raise ValueError('Invalid scene copy.')
            elif type(value) not in (int,float) or not 0<value<=1920:
                raise ValueError('Invalid numeric scene parameter.')
            field=updated['scenes'][index]
            for part in path[:-1]:
                field=field[part]
            field[path[-1]]=value
    merged=reply.get('merge_into_previous',[])
    compressed={row['shot'] for row in short}
    if (not isinstance(merged,list) or any(type(i) is not int or i not in compressed or not 0<i<len(updated['shots'])-1 for i in merged)
            or len(set(merged))!=len(merged)):
        raise ValueError('Only listed compressed interior shots can be merged.')
    if merged:
        ids={old:new for new,old in enumerate(i for i in range(len(updated['shots'])) if i not in merged)}
        updated['shots']=[s for i,s in enumerate(updated['shots']) if i in ids]
        updated['scenes']=[dict(s,shot=ids[s['shot']]) for s in updated['scenes'] if s['shot'] in ids]
    if reply['captions']:
        _rebind(updated,old,src['words'])
    validate_storyboard(updated,src,skill,True,allow_style_findings=True)
    return updated, src
