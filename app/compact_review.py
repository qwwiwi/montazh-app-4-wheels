"""Final review with all four complete videos, an explicit billable bound and timed evidence."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

from job_budget import input_bound
import real_media
import brand_golden
from model_stages import ARGON, CANON, SYSTEM, check_post, model_call, transcript, verdict, video_evidence
from plan_repair import approved_repeat

TEXT_BYTES = 26000
OUTPUT_TOKENS = 5000
LABELS = ('FINAL','A','B','C')
INPUT_CEILING = Decimal('0.000001')
OUTPUT_CEILING = Decimal('0.000005')


def _content(text, videos):
    content = [{'type':'text','text':text}]
    for label, video in zip(LABELS,videos):
        content.extend([{'type':'text','text':label},video])
    return content


def reserve_usd(final_seconds, reference_seconds):
    """Quote the full review with one second of duration headroom per review encode."""
    durations = [final_seconds,*reference_seconds]
    if len(durations) != 4 or any(not math.isfinite(n) or n<=0 for n in durations):
        raise ValueError('Four positive video durations required for review reservation.')
    media = [{'type':'video_url'} for _ in LABELS]
    messages = [{'content':SYSTEM},{'content':_content('x'*TEXT_BYTES,media)}]
    bound = input_bound(messages,[n+1 for n in durations])
    return bound * INPUT_CEILING + OUTPUT_TOKENS * OUTPUT_CEILING


def _short_transcript(src):
    # Preserve every word. Timestamps at two-second buckets retain navigation.
    rows = []
    bucket = None
    for word in src['words']:
        current = int(word['start']) // 2
        if bucket != current:
            rows.append('['+format(word['start'],'.2f')+']')
            bucket = current
        rows.append(word['w'])
    return ' '.join(rows)


def _prompt(rubric, report, raw, cut, brands, approval, media_proof=None):
    extra = []
    instruction = (
        'Judge FINAL independently at normal playback with audio, comparing the three complete A/B/C videos. '
        'Check original facts, hook promise and payoff, story, closing action, names and brand identity. '
        'Assess audible joins, complete takes, caption fidelity, attention, motion, face clearance and phone readability. '
        'For each local style finding judge its actual effect. Record UNVERIFIED if evidence is insufficient. '
        'Return compact Russian JSON {"score":0..10,"checks":[{"id":"required id","verdict":"PASS|REVISE|UNVERIFIED",'
        '"start":seconds,"end":seconds,"evidence":"observed detail","fix":"precise correction if failed",'
        '"reference_time":seconds for reference checks}]}. One check per id. All start/end refer to FINAL. '
        'Every named reference check must include its timestamp in the respective reference.')
    rules = Path(rubric).read_text()
    # Omit only the shell transcript, which is the execution recipe for already-run checks.
    fence = chr(96)*3
    before, marker, after = rules.partition(fence+'sh')
    if marker and fence in after:
        rules = before + after.split(fence,1)[1]
    # The source mix contract is included below in compact procedural form.
    rules=rules.partition('### Real media mix (Argon / real_media_mix)')[0]
    # This preparation guidance and logo section are covered by the evidence and executable logo contract below.
    before, marker, after=rules.partition('## Golden data and limitations')
    if marker and '### Whole-story review' in after:
        rules=before+'### Whole-story review'+after.split('### Whole-story review',1)[1]
    logo_proof=brand_golden.proof(cut,brands)
    cues=logo_proof.pop('cues')
    logo_proof['assets']={c['id']:{k:c[k] for k in ('name','file','source','source_url','sha256')} for c in cues}
    logo_proof['timed_mentions']=[[c['id'],c['spoken'],c['start'],c['end']] for c in cues]
    details = {'task':instruction,'checks':[*CANON,*extra,'reference_A','reference_B','reference_C'],
               'golden_rules':rules,'source':_short_transcript(raw),'cut':_short_transcript(cut),
               'measurements':report['numbers'],'precheck':report.get('precheck','clean'),
               'postcheck_findings':report.get('failures',[]),'renderer_findings':report.get('renderer_findings',[]),
               'brand_manifest':logo_proof,'brand_rules':brand_golden.FINAL_RULE,
               'documented_repeat':approval}
    details.update(real_media_rules=real_media.INSTRUCTION, source_provenance=media_proof or {})
    text = json.dumps(details,ensure_ascii=False,separators=(',',':'))
    if len(text.encode()) > TEXT_BYTES:
        raise ValueError('Материалы превышают размер компактного запроса. Нужно полное ревью с пересчётом бюджета.')
    return text,extra


def _encode(path, out, width, rate):
    subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(path),'-map','0:v:0','-map','0:a:0',
                    '-vf',f'scale=min(iw\\,{width}):-2','-c:v','libx264','-threads','2','-preset','veryfast',
                    '-b:v',f'{rate}k','-maxrate',f'{rate}k','-bufsize',f'{2*rate}k','-pix_fmt','yuv420p',
                    '-c:a','aac','-b:a','64k','-movflags','+faststart',str(out)],check=True,timeout=600)
    return video_evidence(out)


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def review(video, refs, pre, post, rubric, audit, min_score=None, *, raw_words, cut_words, brands=None,
           allow_style_findings=False):
    paths = [Path(video),*map(Path,refs)]
    if len(paths) != len(LABELS):
        raise ValueError('Для ревью нужны три референса.')
    originals = [_digest(p) for p in paths]
    if len(set(originals)) != 4:
        raise ValueError('Для ревью нужны четыре разных видео.')
    report = check_post(pre,post,allow_style_findings=allow_style_findings)
    raw,cut = transcript(raw_words),transcript(cut_words)
    approval = approved_repeat(cut_words,Path(cut_words).parent/'usage.jsonl',cut)
    proof=real_media.final_proof(video,pre)
    prompt,extra = _prompt(rubric,report,raw,cut,brands,approval,proof)
    with tempfile.TemporaryDirectory(prefix='reel-final-review-') as tmp, ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_encode,p,Path(tmp)/f'{label}.mp4',720 if label=='FINAL' else 480,
                               660 if label=='FINAL' else 290) for label,p in zip(LABELS,paths)]
        media = [f.result() for f in futures]
    durations = [m[0] for m in media]
    if abs(durations[0]-report['numbers']['duration']['render']['video']) > .1:
        raise ValueError('Длительность копии для ревью расходится с проверенным рендером.')
    data = model_call('argon-review',ARGON,_content(prompt,[m[2] for m in media]),audit,
                      media_durations=durations,output_token_limit=OUTPUT_TOKENS)
    result = verdict(data,durations,min_score,extra,media_proof=proof,brand_proof=brand_golden.proof(cut,brands))
    result.update(evidence_sha256=dict(zip(('final','A','B','C'),originals)),
                  review_media_sha256=dict(zip(('final','A','B','C'),[m[1] for m in media])),
                  local_findings={'precheck':report.get('precheck','clean'),'postcheck':report.get('failures',[]),
                                  'renderer':report.get('renderer_findings',[])})
    return result
