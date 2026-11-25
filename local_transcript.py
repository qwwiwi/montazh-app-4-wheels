"""Locally revisit uncertain words while preserving caption and edit anchors."""
import argparse
import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

LOW_CONFIDENCE = 0.78

def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text).casefold() if c.isalnum())

def recognize(model, audio, offset=0, beam=5):
    segments,_=model.transcribe(audio,language='ru',word_timestamps=True,beam_size=beam,
                                condition_on_previous_text=False,vad_filter=False)
    return [dict(w=w.word.strip(),start=round(w.start+offset,3),end=round(w.end+offset,3),
                 probability=round(float(w.probability),4)) for s in segments for w in s.words or [] if w.word.strip()]

def closest(word, candidates):
    def overlap(c):
        inter=max(0,min(word['end'],c['end'])-max(word['start'],c['start']))
        return inter/max(.001,max(word['end'],c['end'])-min(word['start'],c['start']))
    best=max(candidates,key=overlap,default=None)
    return best if best and overlap(best)>=.55 else None

def evaluate(word, alternatives):
    if not all(alternatives): return 'unresolved'
    names=[normalized(a['w']) for a in alternatives]
    if not names[0] or len(set(names))!=1:return 'unresolved'
    if min(a['probability'] for a in alternatives)<.88:return 'unresolved'
    if names[0]==normalized(word['w']):return 'confirmed'
    # A change in a number, proper name or mixed-script term requires review.
    if any(not re.fullmatch('[а-яё]+',a['w'].strip('.,!?;:«»—-')) for a in [word,*alternatives]):
        return 'unresolved'
    return 'corrected'

def recheck(model,audio,words):
    suspects=[i for i,w in enumerate(words) if w['probability']<LOW_CONFIDENCE or
              (len(normalized(w['w']))>3 and w['end']-w['start']<.09)]
    groups=[]
    for idx in suspects:
        if groups and words[idx]['start']-words[groups[-1][-1]]['end']<1 and words[idx]['end']-words[groups[-1][0]]['start']<6:
            groups[-1].append(idx)
        else: groups.append([idx])
    report=[]
    for group in groups:
        runs=[]
        for pad in (1.2,2.4):
            start=max(0,int((words[group[0]]['start']-pad)*16000))
            end=min(len(audio),int((words[group[-1]]['end']+pad)*16000))
            runs.append(recognize(model,audio[start:end],start/16000,beam=7))
        for idx in group:
            word=words[idx]; candidates=[closest(word,r) for r in runs]
            verdict=evaluate(word,candidates)
            report.append(dict(index=idx,start=word['start'],end=word['end'],original=word['w'],
                               alternatives=[a['w'] if a else None for a in candidates],status=verdict))
            if verdict=='corrected': word['w']=candidates[0]['w']
    return report

def main():
    import numpy as np
    from faster_whisper import WhisperModel
    parser=argparse.ArgumentParser()
    parser.add_argument('media',type=Path);parser.add_argument('-o',type=Path,required=True);parser.add_argument('--model',required=True)
    a=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        raw=Path(tmp)/'audio.f32'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',a.media,'-map','0:a:0','-ac','1','-ar','16000','-f','f32le',raw],check=True)
        audio=np.fromfile(raw,dtype='<f4')
    duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',a.media]))
    model=WhisperModel(a.model,device='cpu',compute_type='int8')
    words=[w for w in recognize(model,audio) if w['start']<duration]
    for w in words: w['end']=min(duration,max(w['start'],w['end']))
    report=recheck(model,audio,words)
    a.o.with_suffix('.word-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=1))
    a.o.write_text(json.dumps(dict(recogniser='local faster-whisper '+a.model,duration=duration,words=words,
                uncertain_words=[r for r in report if r['status']=='unresolved']),ensure_ascii=False,indent=1))
if __name__=='__main__':
    main()
