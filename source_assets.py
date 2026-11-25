"""Import supplied public-source images, bind to speech, and render credited cutaways."""
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
from urllib.parse import urlsplit


MAX_IMAGE = 12 * 1024 * 1024
AMO = ('amocrm','амаcrm','амосрм','амсрм','амо срм','амо crm','амо црм','ама срм')


def terms(text):
    return re.findall(r'[а-яёa-z0-9]+',text.casefold())


def clean_metadata(title, phrase, url, kind):
    u = urlsplit(url)
    if (not u.hostname or u.scheme != 'https' or u.username or u.password
            or len(url) > 2048 or any(c.isspace() for c in url)):
        raise ValueError('Укажите HTTPS-ссылку на страницу источника.')
    if kind not in ('website','news') or not (1 <= len(title.strip()) <= 85) or not (1 <= len(phrase.strip()) <= 100):
        raise ValueError('Укажите название источника и короткую фразу из речи.')
    return {'id':'source-1','kind':kind,'title':title.strip(),'phrase':phrase.strip(),
            'source_url':url,'credit':u.hostname,'rights':'owner-supplied screenshot; reuse license unverified'}


def ingest(folder, data, metadata):
    # Accept a bounded raster, never follow an uploaded URL or run embedded page content.
    if len(data)>MAX_IMAGE or len(data)<32 or data[:8]!=b'\x89PNG\r\n\x1a\n' or data[12:16]!=b'IHDR':
        raise ValueError('Загрузите PNG-скриншот размером до 12 МиБ.')
    w,h=struct.unpack('>II',data[16:24])
    if min(w,h)<80 or max(w,h)>12000 or w*h>22000000:
        raise ValueError('Размер изображения должен быть от 80 пикселей и до 22 мегапикселей.')
    folder.mkdir(parents=True,exist_ok=True)
    png=folder/'source.png'
    # Normalize to a single decoded frame and discard ancillary data and animation.
    result=subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-f','image2pipe','-c:v','png',
                           '-i','pipe:0','-frames:v','1','-map_metadata','-1',str(png)],
                           input=data,capture_output=True,timeout=25)
    if result.returncode or not png.is_file():
        raise ValueError('Не удалось прочитать изображение источника.')
    meta={**metadata,'screenshot_sha256':hashlib.sha256(png.read_bytes()).hexdigest()}
    (folder/'source.json').write_text(json.dumps(meta,ensure_ascii=False))


def _match(words, phrase):
    vocab=[terms(phrase)]
    if any(terms(phrase)==terms(a) for a in AMO):
        vocab.extend(terms(a) for a in AMO)
    stream=[(t,i) for i,w in enumerate(words) for t in terms(w['w'])]
    tokens=[t for t,_ in stream]
    for i,(_,idx) in enumerate(stream):
        for seq in vocab:
            if seq and tokens[i:i+len(seq)]==seq:
                return idx
    return None


def supplied_source(job_folder, transcript):
    folder=job_folder/'source-material'
    provided=(folder/'source.json').is_file()
    if not provided:
        folder=Path(__file__).parent/'official-media/amocrm'
    if not (folder/'source.json').is_file():
        return None
    meta=json.loads((folder/'source.json').read_text())
    filename=meta.get('file','source.png')
    if Path(filename).name!=filename:
        raise ValueError('Invalid source image name.')
    png=folder/filename
    if not png.is_file() or hashlib.sha256(png.read_bytes()).hexdigest()!=meta['screenshot_sha256']:
        raise ValueError('Файл источника не соответствует сохранённому снимку.')
    idx=_match(transcript['words'],meta['phrase'])
    if idx is None and not provided:
        return None
    return folder,meta,idx


def suggested_cues(material, transcript):
    """Match publisher-derived topic phrases against words on the actual, sped-up cut."""
    _,meta,primary_index=material
    words=transcript['words']
    by_time={}
    for asset in [meta,*meta.get('related_sources',[])]:
        phrases=asset.get('cue_phrases',[])
        matches=[]
        for phrase in phrases:
            idx=_match(words,phrase)
            if idx is not None:
                matches.append((idx,len(terms(phrase))))
        if not matches and asset is meta and primary_index is not None:
            matches=[(primary_index,0)]
        if matches:
            # At the same anchor a more specific crop takes precedence over the whole table.
            idx,specificity=min(matches,key=lambda match:(match[0],-match[1]))
            start=words[idx]['start']
            if start not in by_time or specificity>by_time[start][0]:
                by_time[start]=(specificity,asset['id'],idx)
    cues=[]
    starts=sorted(by_time)
    for start,next_start in zip(starts,starts[1:]+[transcript['duration']]):
        duration=min(4.0,next_start-start)
        if duration>=1:
            _,asset_id,idx=by_time[start]
            cues.append({'asset_id':asset_id,'word_index':idx,'duration':duration})
    return cues[:24]


def source_manifest(material, transcript, plan):
    _,meta,default=material
    words=transcript['words']
    cues=plan.get('source_cues')
    if cues is None:
        if 'source_cue' in plan:
            cues=[plan['source_cue']]
        else:
            cues=suggested_cues(material, transcript) or [{}]
    if not isinstance(cues,list) or not 1<=len(cues)<=24:
        raise ValueError('Choose 1–24 relevant source cues anchored to the speech.')
    assets=[{k:v for k,v in meta.items() if k!='related_sources'},*meta.get('related_sources',[])]
    placements=[]
    for cue in cues:
        if not isinstance(cue,dict):
            raise ValueError('Source cue must name its speech anchor.')
        asset_id=cue.get('asset_id',meta['id'])
        if not any(a['id']==asset_id for a in assets):
            raise ValueError('Source cue references an unprovided image.')
        index=cue.get('word_index',default)
        duration=cue.get('duration',3)
        if type(index) is not int or not 0<=index<len(words):
            raise ValueError('Choose source_cues.word_index for the phrase supporting the supplied source.')
        if type(duration) not in (int,float) or not math.isfinite(duration) or not 1<=duration<=12:
            raise ValueError('Source cue duration must be 1–12 seconds.')
        start=words[index]['start']
        end=min(start+duration,transcript['duration'])
        if end<=start or any(start<r['end'] and end>r['start'] for r in placements):
            raise ValueError('Source cutaways must not overlap.')
        placements.append({'asset_id':asset_id,'start':start,'end':end,'word_index':index})
    return {'assets':assets, 'placements':sorted(placements,key=lambda r:r['start'])}


def attach_source(project, folder, manifest):
    """Attach a physical cutaway and credit below the caption layer, before MP4 render."""
    page=project/'index.html'
    data=page.read_text()
    anchor='window.__timelines["reel"] = tl;'
    if anchor not in data or '</div>\n<script>' not in data:
        raise ValueError('Не найден слой композиции для вставки источника.')
    cards=[]
    timeline=[]
    for i,asset in enumerate(manifest['assets']):
        cues=[cue for cue in manifest['placements'] if cue['asset_id']==asset['id'] and 'native_shot' not in cue]
        if not cues:
            continue
        filename=asset.get('file','source.png')
        if Path(filename).name!=filename:
            raise ValueError('Invalid source image name.')
        source=folder/filename
        if 'screenshot_sha256' in asset and hashlib.sha256(source.read_bytes()).hexdigest()!=asset['screenshot_sha256']:
            raise ValueError('Source screenshot checksum mismatch.')
        local=f'cited-source-{i}.png'
        shutil.copyfile(source,project/'assets'/local)
        host=html.escape(asset['credit']);title=html.escape(asset['title'])
        cards.append(f'<div id="cited-{i}" style="position:absolute;left:38px;top:50px;width:1004px;z-index:21;'
                     'opacity:0;background:#111;color:white;font:600 33px/1.25 sans-serif;border-radius:12px;overflow:hidden">'
                     f'<img src="assets/{local}" alt="" style="display:block;width:100%;height:560px;object-fit:contain;background:#fff">'
                     f'<div style="padding:12px 22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{title} · {host}</div></div>')
        for cue in cues:
            timeline.append(f'tl.set("#cited-{i}",{{opacity:1}},{cue["start"]:.4f});')
            timeline.append(f'tl.set("#cited-{i}",{{opacity:0}},{cue["end"]:.4f});')
    data=data.replace('</div>\n<script>','\n'.join(cards)+'\n</div>\n<script>',1)
    data=data.replace(anchor,'\n'.join(timeline)+'\n'+anchor,1)
    page.write_text(data)
