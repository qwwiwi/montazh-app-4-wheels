"""Timecoded early editorial reviews on the same OpenRouter ledger as final QA."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import real_media
import brand_golden

from model_stages import ARGON, OPUS, body_text, model_call, number, transcript, video_evidence


TAKE_CHECKS = ('complete_takes', 'join_boundaries', 'source_fidelity', 'story_continuity')
PLAN_CHECKS = ('hook_payoff', 'phrase_visuals', 'attention_rhythm', 'brand_text', 'closing_action', real_media.CHECK)


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def source_ranges(selection, duration):
    spans = selection.get('keep')
    if not isinstance(spans, list) or not spans:
        raise ValueError('Отсутствуют интервалы исходной речи.')
    last = 0
    for span in spans:
        if (not isinstance(span, list) or len(span) != 2 or not all(map(number, span))
                or not last <= span[0] < span[1] <= duration + .05):
            raise ValueError('Недопустимые границы дубля на шкале исходника.')
        last = span[1]
    return spans


def review_spec(checks):
    return {'required_ids': checks, 'response': {'checks': [
        {'id': 'one required ID', 'verdict': 'PASS|REVISE|UNVERIFIED',
         'start': 'number, seconds', 'end': 'number, seconds',
         'evidence': 'specific observation in Russian', 'fix': 'specific correction if failed'}]}}


def verified_review(result, required, duration, mode):
    checks = result.get('checks') if isinstance(result, dict) else None
    if (not isinstance(checks, list) or not all(isinstance(c, dict) for c in checks)
            or len(checks) != len(required) or {c.get('id') for c in checks} != set(required)):
        raise ValueError('Argon вернул неполный список проверок.')
    for check in checks:
        a, b = check.get('start'), check.get('end')
        if not (number(a) and number(b) and 0 <= a <= b <= duration + .05):
            raise ValueError('Argon вернул тайм-код вне проверяемого фрагмента.')
        if check.get('verdict') not in ('PASS', 'REVISE', 'UNVERIFIED'):
            raise ValueError('Argon вернул неизвестный результат проверки.')
        body_text(check.get('evidence'))
        if check['verdict'] != 'PASS':
            body_text(check.get('fix'))
    statuses = {c['verdict'] for c in checks}
    verdict = 'UNVERIFIED' if 'UNVERIFIED' in statuses else 'REVISE' if 'REVISE' in statuses else 'PASS'
    return {'verdict': verdict, 'checks': checks, 'evidence_mode': mode}


def word_rows(src):
    return [[w['start'], w['end'], w['w']] for w in src['words']]


def video_review(stage, video_path, prompt, audit):
    """Transmit the complete timeline and audio in a bandwidth-bounded MP4."""
    with tempfile.TemporaryDirectory(prefix='reel-video-review-') as temp:
        proxy = Path(temp)/'review.mp4'
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-i',str(Path(video_path).resolve()),
                        '-map','0:v:0','-map','0:a:0','-vf','scale=480:-2','-c:v','libx264',
                        '-threads','2','-preset','veryfast','-b:v','350k','-maxrate','350k',
                        '-bufsize','700k','-pix_fmt','yuv420p','-c:a','aac','-b:a','96k',
                        '-movflags','+faststart',str(proxy)], check=True, timeout=600)
        duration, digest, video = video_evidence(proxy)
        if abs(duration - prompt['duration']) > .25:
            raise ValueError('Тайм-коды видео и шкалы монтажа расходятся.')
        result = model_call(stage, ARGON, [{'type':'text','text':compact(prompt)},video],
                            audit, media_durations=[duration])
    return result, {'model': ARGON,'review_video_sha256': digest, 'duration':duration}


def inspect_source(source, words, audit):
    src=transcript(words)
    actions=('retain','trim','choose_take','visual','brand','cta')
    prompt={'instruction':(
        'Watch and listen to this complete ORIGINAL before the editor selects takes. Give concise timestamped '
        'editorial directions for this specific recording. Identify the actual hook, substantive claims, meaningful '
        'brand introductions and closing action if spoken. Mark repetitions, retakes or hesitations only when heard. '
        'Distinguish the stronger complete take from rejected false starts. Refer to originating spoken words '
        'or a concrete visible event, with an actionable edit decision. Do not invent absent facts or CTA. '
        'Return JSON {status:"OK|UNVERIFIED", notes:[{start,end,action,evidence,direction}]}. '
        'Use 1–20 short notes, Russian evidence and directions, and only the supplied allowed action names. '
        'If the recording cannot be seen or heard, use UNVERIFIED and an empty notes array.'),
        'allowed_actions':actions,'duration':src['duration'],'word_rows_start_end_text':word_rows(src)}
    result,receipt=video_review('argon-source',source,prompt,audit)
    if result.get('status')=='UNVERIFIED':
        return {**receipt,'status':'UNVERIFIED','timeline':'source','notes':[]}
    notes=result.get('notes')
    if result.get('status')!='OK' or not isinstance(notes,list) or not 1<=len(notes)<=20:
        raise ValueError('Argon не вернул подтверждённый разбор исходника.')
    checked=[]
    for row in notes:
        if not isinstance(row,dict):
            raise ValueError('Некорректная заметка в разборе исходника.')
        a,b=row.get('start'),row.get('end')
        if (not number(a) or not number(b) or not 0<=a<b<=src['duration']+.05 or
                row.get('action') not in actions):
            raise ValueError('Недопустимый тайм-код или тип замечания к исходнику.')
        checked.append({'start':a,'end':b,'action':row['action'],
                        'evidence':body_text(row.get('evidence'))[:420],
                        'direction':body_text(row.get('direction'))[:420]})
    return {**receipt,'status':'OK','timeline':'source','notes':checked}


def review_rough_cut(cut, words, selection, mapping, audit):
    src=transcript(words)
    spans=source_ranges(selection,src['duration'])
    prompt={'instruction':(
        'Watch and listen to this actual joined rough-cut video at delivery speed. Listen across all joins, '
        'and check that each thought is complete, no false starts repeat, and the story and original meaning '
        'are intact. The transcript is on the ORIGINAL source timeline, and the mapping gives source and cut '
        'intervals. Report evidence and fixes in Russian, with start/end exclusively on the supplied CUT '
        'timeline. Cite concrete words and a proposed change for each material defect. Ignore missing '
        'graphics, captions and logos at this rough-cut stage. If audio or video cannot be inspected, use UNVERIFIED.'),
        'duration':mapping['cut_duration'], 'source_seconds':src['duration'], 'keep_source_seconds':spans,
        'source_to_cut':mapping['pieces'], 'word_rows_start_end_text':word_rows(src),
        **review_spec(TAKE_CHECKS)}
    result,receipt=video_review('argon-rough-cut',cut,prompt,audit)
    report=verified_review(result, TAKE_CHECKS, mapping['cut_duration'], 'joined_rough_cut_video_audio')
    # Preserve only intersecting source intervals; cut-time joins may be discontinuous.
    for row in report['checks']:
        if row['verdict']=='PASS':
            continue
        row['source_intervals']=[]
        for piece in mapping['pieces']:
            c,d=piece['cut']; s,t=piece['src']
            left=max(c,row['start']); right=min(d,row['end'])
            if right<left or d<=c:
                continue
            row['source_intervals'].append([round(s+(left-c)*(t-s)/(d-c),4),
                                            round(s+(right-c)*(t-s)/(d-c),4)])
        row['fix']=row['fix'][:500]
        row['evidence']=row['evidence'][:500]
    return {**report,**receipt,'timeline':'rough_cut'}


def review_storyboard(words, storyboard, audit):
    src = transcript(words)
    plan_fields = ('shots', 'scenes', 'cta', 'brand_candidates', 'brand_omissions')
    plan = {k:storyboard[k] for k in plan_fields if k in storyboard}
    proof=real_media.early_proof(storyboard,src)
    prompt = {'instruction': (
        'Review editorial intent before render using the frozen transcript and word-anchored storyboard only. '
        'Assess hook promise and payoff, mapping of speech to each visual, planned focus and rhythm, '
        'accuracy of brand names and text, and CTA when supported by the speaker. Use frozen cut seconds. '
        'Words may be mistranscribed: mark uncertain brand interpretation, never introduce an unsupported brand. '
        'Judge material problems and give Opus an actionable correction with the scene or shot number where possible. '
        'Actual pixel placement, measured contrast, audible cuts and resemblance to video references are checked later; '
        'do not mark them as observed or fail this stage solely because pixels and audio are unavailable. '
        'JSON with concise evidence and fixes in Russian.'),
        'brand_planning_rules':brand_golden.PLAN_RULE,'plan':plan,'source_provenance':proof,'planned_mix':real_media.review_metrics(proof),
        'source_rules':real_media.INSTRUCTION.split('For final playback')[0]+' Evaluate planned placements on the cut timeline.',
        'duration':src['duration'], 'word_rows_start_end_text':word_rows(src),
        **review_spec(PLAN_CHECKS)}
    response = model_call('argon-storyboard', ARGON, compact(prompt), audit)
    result = verified_review(response, PLAN_CHECKS, src['duration'], 'storyboard_and_transcript_only')
    row=next(c for c in result['checks'] if c['id']==real_media.CHECK)
    real_media.apply_mix(row,proof,final=False)
    if row['verdict']=='UNVERIFIED' or (row['verdict']=='REVISE' and result['verdict']=='PASS'):
        result['verdict']=row['verdict']
    result['plan_sha256'] = hashlib.sha256(compact(plan).encode()).hexdigest()
    result['timeline'] = 'frozen_cut'
    return result


def revise_takes(words, selection, feedback, audit):
    src = transcript(words)
    previous = source_ranges(selection, src['duration'])
    issues = [c for c in feedback['checks'] if c.get('verdict') != 'PASS']
    prompt = {'instruction': (
        'You own take selection. Return {"keep":[[start,end],...]} with ALL retained source intervals. '
        'Revise the selection using Argon’s evidence and the source transcript; keep unaffected complete thoughts, '
        'hook and spoken CTA, fix repeated starts, clipped syllables and omissions only where supported. '
        'All returned ranges must refer to the ORIGINAL source, chronological nonoverlapping, between words. '
        'Earlier final-review timestamps may refer to a draft; map the quoted speech to the supplied source before acting. '
        'An unchanged selection cannot correct a reported take defect.'),
        'previous_keep':previous, 'review_timeline':feedback.get('timeline','draft'),
        'issues':issues, 'source_seconds':src['duration'], 'word_rows_start_end_text':word_rows(src)}
    result = model_call('opus-take-revise', OPUS, compact(prompt), audit)
    updated = source_ranges(result, src['duration'])
    if updated == previous:
        raise ValueError('Opus вернул прежние интервалы после замечаний к склейкам.')
    return {'keep':updated, 'max_pause':.30, 'keep_pause':.22, 'snap':.04}


def opus_retime(previous_storyboard_dict, words_path, skill_path, audit_path, feedback_checks=None):
    """Ask the editor to adapt the previous visual decisions to a newly frozen cut."""
    from copy import deepcopy
    from model_stages import LocalPlanError, validate_storyboard
    from plan_repair import apply_edits
    src = transcript(words_path)
    keys = ('shots','scenes','cta','accent_words','brand_candidates','brand_omissions','repeats_ok')
    plan = {k:deepcopy(previous_storyboard_dict[k]) for k in keys if k in previous_storyboard_dict}
    # Numeric brand indices and repeat exceptions are coupled to the old word stream.
    plan.update(brand_candidates=[], brand_omissions=[], repeats_ok=[])
    prompt = {'instruction': (
        'Adapt your previous storyboard to this NEW frozen speech cut. Return only '
        '{"edits":[{"path":["scenes",0,"field"],"value":...}]}. Indices are zero-based. '
        'Keep the narrative, change stale anchors and word windows to the exact available words. '
        'Review each absolute timestamp and word index, including nested animation/caption cue anchors. '
        'Drop scenes tied to removed false starts; combine or reassign shots when needed. '
        'Use arrays as replacement values to remove/insert entries. '
        'Identify explicit brand mentions anew using inclusive new word indices. '
        'Keep a clear opening, full final codeword and faithful factual meaning. '
        'Where relevant correct concrete visual problems from prior feedback without copying its old timestamps.'),
        'previous_visuals':plan,'new_duration':src['duration'],
        'new_words_start_end_text':word_rows(src),'prior_findings':feedback_checks or []}
    response = model_call('opus-retime', OPUS, compact(prompt), audit_path)
    updated = plan
    try:
        updated = apply_edits(plan, response)
        return validate_storyboard(updated, src, skill_path, True, allow_style_findings=True)
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise LocalPlanError(str(error), updated) from error
