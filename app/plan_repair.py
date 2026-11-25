"""Keep accepted parts of a storyboard when repairing a specific finding."""
from copy import deepcopy
import json
import re


def apply_edits(plan, response):
    edits = response.get('edits') if isinstance(response, dict) else None
    if not isinstance(edits, list) or not 1 <= len(edits) <= 80:
        raise ValueError('Expected 1–80 targeted storyboard edits.')
    result = deepcopy(plan)
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'path', 'value'}:
            raise ValueError('Invalid storyboard edit.')
        path = edit['path']
        if not isinstance(path, list) or not 1 <= len(path) <= 12 or not isinstance(path[0], str):
            raise ValueError('Invalid storyboard edit path.')
        if path[0] not in result:
            if len(path) != 1 or path[0] not in ('source_cues', 'brand_omissions') or not isinstance(edit['value'], list):
                raise ValueError('Invalid storyboard edit path.')
        parent = result
        for key in path[:-1]:
            parent = parent[_key(parent, key)]
        key = _key(parent, path[-1], insert=True)
        parent[key] = edit['value']
    return result


def _key(parent, key, insert=False):
    if isinstance(parent, list) and type(key) is int and 0 <= key < len(parent):
        return key
    if isinstance(parent, dict) and isinstance(key, str) and (insert or key in parent):
        return key
    raise ValueError('Storyboard edit references a missing or invalid path.')


def revision_prompt(plan, findings, transcript, context, rubric):
    failures = findings.get('local_failures') or []
    shot_ranges = [re.match(r'^shot (\d+) \w+ ([\d.]+)-([\d.]+):?', message) for message in failures]
    indexed = [(int(m[1]), float(m[2]), float(m[3])) for m in shot_ranges if m]
    if indexed and all(m or message.startswith('c') and 'caption' in message
                       for m, message in zip(shot_ranges, failures)):
        first, last = min(t[1] for t in indexed)-1, max(t[2] for t in indexed)+1
        shot_ids = {t[0] for t in indexed}
        if all(0 <= i < len(plan['shots']) for i in shot_ids):
            scope = {'shots_by_original_index': {i:plan['shots'][i] for i in sorted(shot_ids)},
                     'scenes_by_original_index': {i:s for i,s in enumerate(plan['scenes']) if s['shot'] in shot_ids},
                     'nearby_words':[w for w in transcript['words'] if first <= w['start'] <= last],
                     'cta':plan.get('cta'), 'duration':transcript['duration'],
                     'failures':failures, 'other_scene_kinds':(context or {}).get('other_native_kinds',[])}
            return ('Return only {"edits":[{"path":["scenes",9,"field"],"value":"..."}]}. '
                    'Use ORIGINAL integer array indices shown, edit only supplied scenes and shots. '
                    'Resolve each measured issue; preserve the speech, truthful captions and CTA hold >=2.5s. '
                    'Use word anchors. Coverage and motion must be visible on rendered frames. '
                    'A component designed for split can be placed in a split shot if full visual leaves a large empty band. '
                    'Keep the answer compact. No full storyboard.\n'
                    + json.dumps(scope,ensure_ascii=False,separators=(',',':')))
    # Keep one complete base plan; large example storyboards are needed only for creation.
    return ('Repair the supplied storyboard. Return only {"edits":[{"path":["scenes",0,"field"],"value":...}]}. '
            'Use keys and zero-based indices. Replace arrays to insert or delete elements. '
            'Preserve all unaffected scenes and factual content. Match exact native component schemas and word anchors. '
            'Fix all findings. For a missing closing reminder, use a component that actually renders it.\n'
            + json.dumps({'previous': plan, 'findings': findings, 'transcript': transcript,
                          'available_tools': context, 'rules': rubric}, ensure_ascii=False, separators=(',', ':')))


def approved_repeat(words_path, audit, transcript):
    """Allow a documented exception only for this frozen transcript and exact occurrences."""
    import hashlib
    from pathlib import Path
    spec = Path(audit).parent / 'approved-repeat.json'
    if not spec.is_file():
        return None
    data = json.loads(spec.read_text())
    if hashlib.sha256(Path(words_path).read_bytes()).hexdigest() != data['words_sha256']:
        raise ValueError('Documented repetition refers to a different frozen transcript.')
    phrase = data['phrase'].casefold().split()
    words = transcript['words']
    tokens = [w['w'].casefold() for w in words]
    starts = [w['start'] for i, w in enumerate(words) if tokens[i:i + len(phrase)] == phrase]
    if len(phrase) < 3 or len(starts) != 2 or starts != data['starts'] or not data.get('reason'):
        raise ValueError('Documented repetition does not match the frozen transcript.')
    return data


def record_approved_repeat(plan, approval):
    if approval and approval['phrase'] not in plan.get('repeats_ok', []):
        plan.setdefault('repeats_ok', []).append(approval['phrase'])
    return plan
