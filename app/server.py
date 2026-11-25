"""Local single-user automatic rough-cut editor."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
from threading import Lock
from urllib.parse import parse_qs, urlsplit
import uuid

from article_source import article_url, prepare_article
from source_assets import clean_metadata, ingest, MAX_IMAGE
from pace import DEFAULT_SPEED, check_speed
from editor import edit
from full_edit import availability, can_recut, can_resume, full_edit
from model_stages import budget_snapshot
from repo_paths import REPO as ROOT

JOBS = ROOT / 'jobs'
POOL = ThreadPoolExecutor(max_workers=1)
RESUME_LOCK = Lock()
EXTENSIONS = {'.mov', '.mp4', '.m4v', '.webm', '.mkv'}
MAX_UPLOAD = 1024 ** 3


def save(folder, status, progress, **extra):
    temp = folder / 'state.tmp'
    temp.write_text(json.dumps(dict(id=folder.name,status=status,progress=progress,**extra),ensure_ascii=False))
    temp.replace(folder/'state.json')


def process(folder, src, mode, resume=False, recut=False, speed=DEFAULT_SPEED):
    try:
        update=lambda message: save(folder,'processing',str(message))
        update('Анализ видео')
        if mode == 'full':
            article_request=folder/'article-url.txt'
            if article_request.is_file():
                update('Программа снимает статью и собирает иллюстрации Хабра')
                prepare_article(folder,article_request.read_text())
            result = full_edit(src, folder/'edit.mp4', update, resume=resume, recut=recut, **({} if resume else {'speed':speed}))
        else:
            result = edit(src, folder/'edit.mp4', update, speed=speed)
        save(folder,'ready','Монтаж завершён',result=result)
    except Exception as exc:
        message=str(exc)[:300] if isinstance(exc,ValueError) else 'Не удалось обработать видео. Проверьте формат и повторите загрузку.'
        save(folder,'error','Монтаж остановлен',error=message)


def stage_reports(job):
    reports = []
    files = [*job.glob('**/stage-review.json'), *job.glob('**/attempt-*/review.json')]
    for file in files:
        try:
            data = json.loads(file.read_text())
            stage = data.get('stage','final')
            rows = data.get('checks',data.get('issues',[]))
            reports.append((file.stat().st_mtime_ns,{'stage':stage,'version':file.parent.name.rsplit('-',1)[-1],
                        'verdict':data['verdict'],'checks':rows,'evidence_mode':data.get('evidence_mode')}))
        except (FileNotFoundError,json.JSONDecodeError):
            continue
    return [report for _,report in sorted(reports,key=lambda pair:pair[0])]


def latest_render(job):
    versions=sorted(job.glob('**/attempt-*/frozen-audio.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)
    for marker in versions:
        video=marker.parent/'render.mp4'
        if video.is_file():return video
    return None

def failure_detail(job):
    """Explain a generator/build mismatch using only the latest failed attempt."""
    run=job
    recuts=[d for d in job.glob('recut-*') if d.name[6:].isdigit()]
    if recuts:run=max(recuts,key=lambda p:int(p.name[6:]))
    tries=[d for d in run.glob('attempt-*') if d.name[8:].isdigit()]
    if not tries:return ''
    last=max(tries,key=lambda p:int(p.name[8:]))
    log=run/'pipeline.log'
    if not log.is_file():return ''
    with log.open('rb') as f:
        f.seek(max(0,log.stat().st_size-3000))
        lines=f.read().decode(errors='replace').splitlines()
    if lines and lines[-1]=="KeyError: 'result'" and any('in hc_steps' in line for line in lines[-6:]):
        return f'Попытка {last.name[8:]}. При сборке анимации шагов не найдено поле «result». Склейка и приложенные изображения сохранены.'
    return ''

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def local(self):
        hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        return self.headers.get('Host') in hosts and self.headers.get('Origin') in {None,*('http://'+h for h in hosts)}

    def reply(self, data, code=200, mime='application/json'):
        if mime=='application/json': data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(data)

    def video(self,path,download=False):
        size=path.stat().st_size
        start,end=0,size-1
        byte_range=self.headers.get('Range')
        if byte_range:
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',byte_range)
            if not m or not any(m.groups()): return self.reply({'error':'Некорректный диапазон'},416)
            a,b=m.groups()
            start=int(a) if a else max(0,size-int(b))
            end=min(int(b),size-1) if a and b else size-1
            if start>end: return self.reply({'error':'Диапазон вне файла'},416)
        self.send_response(206 if byte_range else 200)
        self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'video/mp4')
        self.send_header('Accept-Ranges','bytes')
        if byte_range: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length',str(end-start+1))
        if download:self.send_header('Content-Disposition','attachment; filename="reel.mp4"')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start)
            left=end-start+1
            while left:
                data=f.read(min(left,1024*1024))
                if not data:break
                try:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):break
                left-=len(data)

    def do_GET(self):
        if not self.local():return self.reply({'error':'Только на Mac mini'},403)
        path=urlsplit(self.path).path
        if path=='/':return self.reply((ROOT/'index.html').read_bytes(),mime='text/html; charset=utf-8')
        if path=='/pipeline':return self.reply((ROOT/'pipeline.html').read_bytes(),mime='text/html; charset=utf-8')
        if path=='/api/modes':return self.reply(availability())
        if path=='/demo.mp4':return self.video(ROOT/'assets'/'demo.mp4')
        preview=re.fullmatch(r'/api/jobs/([a-f0-9]{32})/preview/(1\.[34])',path)
        if preview:
            file=JOBS/preview[1]/'previews'/(preview[2]+'.mp4')
            if file.is_file():return self.video(file)
        m=re.fullmatch(r'/api/jobs/([a-f0-9]{32})(?:/(video|download|source|render-preview))?',path)
        if m:
            folder=JOBS/m[1]
            if (folder/'state.json').exists():
                state=json.loads((folder/'state.json').read_text())
                if m[2]=='render-preview':
                    draft=latest_render(folder/'full')
                    if draft:return self.video(draft)
                if m[2]=='source':
                    original=next((p for p in folder.glob('source.*') if p.suffix in EXTENSIONS),None)
                    if original:return self.video(original)
                if not m[2]:
                    state['preview_speeds']=[s for s in ('1.3','1.4') if (folder/'previews'/(s+'.mp4')).is_file()]
                    job = folder/'full'
                    if (folder/'article-url.txt').is_file() and not job.exists():
                        state['mode']='full'
                        state['resumable']=state['status']=='error'
                    if job.is_dir():
                        state['mode'] = 'full'
                        state['has_render_preview']=latest_render(job) is not None
                        budget = budget_snapshot(job/'usage.jsonl')
                        state['budget'] = budget
                        state['resumable'] = (state['status'] == 'error'
                            and bool(budget['remaining_usd'] and budget['remaining_usd'] > 0)
                            and can_resume(job))
                        state['recut_available'] = (state['status']=='error'
                            and bool(budget['remaining_usd'] and budget['remaining_usd']>0)
                            and can_recut(job))
                        if state['status']=='error' and 'pipeline.log' in state.get('error',''):
                            state['failure_detail']=failure_detail(job)
                        state['reviews'] = stage_reports(job)
                        sources={}
                        for manifest in job.glob('**/attempt-*/real-media.json'):
                            try:
                                evidence=json.loads(manifest.read_text())
                                used={cue['asset_id'] for cue in evidence.get('placements',[])}
                                entries=[a for a in evidence.get('assets',[]) if a.get('id') in used]
                            except (OSError,json.JSONDecodeError):
                                continue
                            for asset in entries:
                                url=asset.get('source_url','')
                                if urlsplit(url).scheme=='https':
                                    sources[url]=asset.get('title') or urlsplit(url).hostname
                        state['sources']=[{'url':url,'title':title} for url,title in sources.items()]
                    return self.reply(state)
                if m[2] in ('video','download') and state['status']=='ready':return self.video(folder/'edit.mp4',m[2]=='download')
        return self.reply({'error':'Файл не найден'},404)

    def do_POST(self):
        if not self.local():return self.reply({'error':'Только на Mac mini'},403)
        parts=urlsplit(self.path)
        resume = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(resume|recut)', parts.path)
        if resume:
            folder = JOBS/resume[1]
            job = folder/'full'
            with RESUME_LOCK:
                statefile = folder/'state.json'
                if not statefile.exists():
                    return self.reply({'error':'Задача не найдена.'},404)
                state = json.loads(statefile.read_text())
                recut = resume[2]=='recut'
                if (not recut and state['status']=='error' and not job.exists()
                        and (folder/'article-url.txt').is_file()):
                    src=next((f for f in folder.glob('source.*') if f.suffix in EXTENSIONS),None)
                    if src is None:
                        return self.reply({'error':'Исходник задания не найден.'},409)
                    options=folder/'upload-options.json'
                    speed=check_speed(json.loads(options.read_text())['speed'] if options.exists() else DEFAULT_SPEED)
                    save(folder,'queued','Повторяем сбор источников')
                    POOL.submit(process,folder,src,'full',speed=speed)
                    return self.reply({'id':folder.name},202)
                eligible = can_recut if recut else can_resume
                if state['status'] != 'error' or not eligible(job):
                    return self.reply({'error':'Эту задачу сейчас нельзя продолжить.'},409)
                remaining = budget_snapshot(job/'usage.jsonl')['remaining_usd']
                if remaining is None or remaining <= 0:
                    return self.reply({'error':'Нет подтверждённого остатка бюджета.'},409)
                src = next((f for f in folder.glob('source.*') if f.suffix in EXTENSIONS), None)
                if src is None:
                    return self.reply({'error':'Исходный файл задачи не найден.'},409)
                save(folder,'queued','Продолжаем с сохранённого монтажа')
                if recut:
                    POOL.submit(process,folder,src,'full',True,True)
                else:
                    POOL.submit(process,folder,src,'full',True)
            return self.reply({'id':folder.name},202)
        if parts.path!='/api/jobs':return self.reply({'error':'Страница не найдена'},404)
        try:
            speed=check_speed(parse_qs(parts.query).get('speed',[DEFAULT_SPEED])[0])
        except ValueError as exc:
            return self.reply({'error':str(exc)},400)
        mode=parse_qs(parts.query).get('mode',['local'])[0]
        if mode not in ('local','full'):return self.reply({'error':'Неизвестный режим'},400)
        if mode=='full':
            state=availability()
            if not state['ready']:return self.reply({'error':'Требуется: '+', '.join(state['missing'])},409)
        ext=Path(parse_qs(parts.query).get('filename',[''])[0]).suffix.lower()
        if ext not in EXTENSIONS:return self.reply({'error':'Выберите видео MP4, MOV, M4V, MKV или WebM'},400)
        try:size=int(self.headers.get('Content-Length','0'))
        except ValueError:size=0
        query=parse_qs(parts.query)
        try:
            image_size=int(self.headers.get('X-Source-Bytes','0'))
            if not 0<=image_size<=MAX_IMAGE or size<=image_size or size-image_size>MAX_UPLOAD:
                raise ValueError('Допустимый размер видео — до 1 ГиБ, PNG — до 12 МиБ.')
            source=None
            article=query.get('article_url',[''])[0]
            if article:
                if mode!='full' or image_size:
                    raise ValueError('Выберите полный монтаж и один способ добавления источника.')
                article=article_url(article)
            if image_size:
                if mode!='full':
                    raise ValueError('Графические источники доступны в полном монтаже.')
                source=clean_metadata(*(query.get(k,[''])[0] for k in ('source_title','source_phrase','source_url','source_kind')))
        except ValueError as exc:
            return self.reply({'error':str(exc)},400)

        folder=JOBS/uuid.uuid4().hex
        folder.mkdir()
        if article:
            (folder/'article-url.txt').write_text(article)
            (folder/'upload-options.json').write_text(json.dumps({'speed':speed}))
        if source:
            try:
                image=self.rfile.read(image_size)
                if len(image)!=image_size:
                    raise ValueError('Загрузка изображения прервана.')
                ingest(folder/'source-material',image,source)
            except (ValueError,TimeoutError,subprocess.TimeoutExpired) as exc:
                save(folder,'error','Не удалось загрузить источник',error=str(exc))
                return self.reply({'error':str(exc)},400)
        src=folder/('source'+ext)
        with src.open('wb') as f:
            left=size-image_size
            while left:
                block=self.rfile.read(min(1024*1024,left))
                if not block:
                    save(folder,'error','Загрузка прервана',error='Неполный файл')
                    return
                f.write(block)
                left-=len(block)
        save(folder,'queued','В очереди')
        POOL.submit(process,folder,src,mode,speed=speed)
        self.reply({'id':folder.name},202)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8774)
    args=parser.parse_args()
    os.umask(0o077)
    JOBS.mkdir(exist_ok=True)
    for statefile in JOBS.glob('*/state.json'):
        if json.loads(statefile.read_text())['status'] in ('queued','processing'):
            save(statefile.parent,'error','Обработка прервана',error='Загрузите исходник повторно.')
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
