"""Transfer an editor's existing composition through two source-to-cut maps."""
from copy import deepcopy
from pathlib import Path
import sys


def _project(t, pieces, axis, target):
    # Removed gaps contract to the next surviving boundary; head/tail padding
    # belongs to the nearest original endpoint.
    for piece in pieces:
        left, right = piece[axis]
        a, b = piece[target]
        if t < left:
            return a
        if t <= right:
            return a + (b-a) * (t-left)/(right-left)
    return pieces[-1][target][1]


def transfer_storyboard(plan, old_words, new_words, old_cut_map, new_cut_map, skill):
    """Return (validated plan, provenance). All inputs except skill are dictionaries."""
    from model_stages import validate_storyboard
    sys.path.insert(0,str((Path(skill)/'scripts').resolve()))
    try:
        import reel_plan as rp
    finally:
        sys.path.pop(0)
    old = [rp.Word(w['w'], w['start'], w['end']) for w in old_words['words']]
    new = [rp.Word(w['w'], w['start'], w['end']) for w in new_words['words']]
    if not old or not new:
        raise ValueError('Cannot transfer a storyboard without the two transcripts.')
    src_end, dst_end = old_words['duration'], new_words['duration']
    def transfer(t):
        if t <= 0:
            return 0.
        if t >= rp.snap(src_end):
            return rp.snap(dst_end)
        original = _project(t, old_cut_map['pieces'], 'cut', 'src')
        return min(rp.snap(dst_end), rp.snap(_project(original,new_cut_map['pieces'],'src','cut')))

    def anchor(t, lead=0, match=None):
        candidates = new if match is None else [w for w in new if w.norm == rp.normalise(match)]
        if not candidates:
            raise ValueError(f'Code word {match!r} is absent from the new cut.')
        word = min(candidates,key=lambda w:abs(w.start-t-lead))
        return {'word':word.w,'after':word.start,'before':word.start+.001,
                'plus':round(t - word.start + lead, 5)}

    def nested(node):
        if isinstance(node,dict):
            return {k: anchor(transfer(rp.resolve(v,old,src_end))) if rp._is_anchor_key(k)
                    else nested(v) for k,v in node.items()}
        if isinstance(node,list):
            return [nested(v) for v in node]
        return node

    old_plan = rp.build_plan(plan,old,src_end)
    result = {'shots':[],'scenes':[],'accent_words':deepcopy(plan.get('accent_words',[])),
              'repeats_ok':[],'brand_candidates':[],'brand_omissions':[]}
    survivors = {}
    compressed = []
    for idx, shot in enumerate(old_plan.shots):
        start, end = transfer(shot.start), transfer(shot.end)
        if end <= start:
            continue
        if end-start < 1.0 and shot.end-shot.start >= 1.0:
            compressed.append({'old_shot':idx,'start':start,'end':end})
        survivors[idx] = len(result['shots'])
        new_shot = deepcopy(plan['shots'][idx])
        new_shot['from'] = 0 if not result['shots'] else anchor(start,rp.LEAD)
        result['shots'].append(new_shot)
    for scene in plan['scenes']:
        if scene['shot'] in survivors:
            copy = nested(scene)
            copy['shot'] = survivors[scene['shot']]
            result['scenes'].append(copy)
    if old_plan.cta:
        c = plan['cta']
        result['cta'] = {'from':anchor(transfer(old_plan.cta.start),rp.LEAD),
                         'to':anchor(transfer(old_plan.cta.end),rp.LEAD),'word':c['word'],
                         'word_anchor':anchor(transfer(rp.resolve(c['word_anchor'],old,src_end)),
                                              match=c['word_anchor']['word'])}
    for field in ('brand_candidates','brand_omissions'):
        for item in plan.get(field,[]):
            old_span=old[item['first']:item['last']+1]
            if not old_span:
                continue
            n=len(old_span)
            matches=[i for i in range(len(new)-n+1)
                     if [w.norm for w in new[i:i+n]] == [w.norm for w in old_span]]
            if matches:
                target=transfer(old_span[0].start)
                i=min(matches,key=lambda i:abs(new[i].start-target))
                if abs(new[i].start-target)<.65:
                    result[field].append({**item,'first':i,'last':i+n-1})
    if plan.get('punch'):
        raise ValueError('This transfer requires Opus to adapt the punch list.')
    result=validate_storyboard(result,new_words,skill,True,allow_style_findings=True)
    return result, {'surviving_shots':survivors,'compressed_shots':compressed,
                    'removed_shots':[i for i in range(len(old_plan.shots)) if i not in survivors],
                    'method':'original_source_interval_projection'}
