"""Full editorial pipeline; preserve job evidence, publish only an accepted render."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from decimal import Decimal

from editor import INPUT, metadata
from source_assets import supplied_source, attach_source, suggested_cues
from pace import DEFAULT_SPEED, accelerate, check_speed
from repo_paths import REPO


HERE = Path(__file__).resolve().parent
RUBRIC = REPO / "docs" / "GOLDEN.md"
KEY_FILE = Path(os.environ.get("REEL_KEY_FILE", Path.home() / ".config/montazh-app-4-wheels/openrouter.key")).expanduser()


def libraries():
    return Path(os.environ.get("REEL_LIBRARIES", REPO.parent/"reel-libraries")).expanduser()


def configure_graphics(job,skill,words,head,candidates,omissions=None):
    from brands import prepare_brands
    assets=job/"assets"
    assets.mkdir(exist_ok=True)
    report=prepare_brands(words,libraries()/"catalog.json",assets,candidates=candidates)
    apply_omissions(report, omissions or [])
    write(job/"brand-mentions.json",report)
    kit=job/"html-components"
    for folder in ("components","fonts"):
        shutil.copytree(libraries()/"html-components"/folder,kit/folder, dirs_exist_ok=True)
    cfg=read(skill/"examples/reel_config-efir-26-11.json")
    cfg.update(head=read(head)["worst_case"],assets_dir="assets",brand_mentions="brand-mentions.json")
    write(job/"reel_config.json",cfg)
    return report


def apply_omissions(report, omissions):
    if not isinstance(omissions,list):
        raise ValueError("Invalid editorial brand omissions.")
    matched={(row["word_start"],row["word_end"]):row for row in report["mentions"]}
    hidden={}
    for omission in omissions:
        if not isinstance(omission,dict):
            raise ValueError("Invalid editorial brand omission.")
        span=omission.get("first"),omission.get("last")
        reason=omission.get("reason")
        if (not all(type(v) is int for v in span) or span not in matched or span in hidden
                or not isinstance(reason,str) or not reason.strip() or len(reason)>500):
            raise ValueError("Brand omission needs a verified exact span and a reason.")
        hidden[span]=dict(matched[span],reason=reason.strip())
    report["mentions"]=[r for span,r in matched.items() if span not in hidden]
    report["editorial_omissions"]=list(hidden.values())


class RecutRequested(Exception):
    """The final media reviewer requested changes to the selected source takes."""


class RevisionNeeded(Exception):
    """An actionable creative defect that can be addressed on the frozen cut."""
    def __init__(self, evidence, *, manual=False):
        self.evidence=evidence
        self.manual=manual
        super().__init__(str(evidence.get("stage","editorial")))


def revision_feedback(folder):
    request=folder/"revision-request.json"
    storyboard=folder/"storyboard.json"
    if not request.is_file() and storyboard.is_file() and (folder/"stage-review.json").is_file():
        # Older jobs could stop on a renderer schema error before recording a repair request.
        from scene_contract import ComponentError
        from model_stages import validate_storyboard
        if read(folder/"stage-review.json").get("verdict")=="PASS":
            try:
                validate_storyboard(read(storyboard),read(folder.parent/"words.json"),settings()[0],True,True)
            except ComponentError as exc:
                return {"previous_storyboard":read(storyboard),
                        "corrections":{"stage":"component_schema","local_failures":str(exc).splitlines()}}
    if not request.is_file() or not storyboard.is_file():
        raise ValueError("Для продолжения нужны сохранённый план и конкретные замечания проверки.")
    evidence=read(request)
    # Older versions escalated renderer audio padding as a speech defect.
    # Recover only the legacy postcheck whose full evidence is still on disk.
    remaining = evidence.get("local_failures", [])
    post = folder/"qa/postcheck.json"
    if evidence.get("stage") == "postcheck" and post.is_file() and not (folder/"frozen-audio.json").exists():
        post_failures = read(post).get("failures")
        visual = [v for v in remaining if not str(v).startswith("audio duration ")]
        if len(visual) < len(remaining) and post_failures == remaining:
            evidence = {**evidence, "manual": False, "local_failures": visual, "restore_frozen_audio": True}
    if evidence.get("manual") or any(
        issue.get("id") in ("take_completeness","audio_sync") or issue.get("verdict")=="UNVERIFIED"
        for issue in evidence.get("issues",[])
    ) or any(any(term in str(v).lower() for term in ("out of sync","repeated take","repeat:","audio duration"))
             for v in evidence.get("local_failures",[])):
        raise ValueError("Нужна ручная проверка исходной речи или доказательств.")
    return {"previous_storyboard":read(storyboard),"corrections":evidence}


def resume_point(job):
    prior=sorted((d for d in job.glob("attempt-*") if d.is_dir() and d.name[8:].isdigit()),
                 key=lambda d:int(d.name[8:]))
    if not prior:
        raise ValueError("Для продолжения нужен сохранённый план монтажа.")
    next_number=int(prior[-1].name[8:])+1
    for folder in reversed(prior):
        if (folder/"confirmed-truncation.json").is_file() and not (folder/"storyboard.json").exists():
            continue
        if (folder/"budget-stop.json").is_file():
            continue
        return next_number,revision_feedback(folder)
    if (job/"origin.json").is_file() and all((d/"budget-stop.json").is_file() for d in prior):
        return next_number,None
    raise ValueError("Для продолжения нужен план с замечаниями.")


def latest_run(job):
    runs=sorted((d for d in job.glob("recut-*") if d.is_dir() and d.name[6:].isdigit()),
                key=lambda d:int(d.name[6:]))
    return runs[-1] if runs else job


def reviewed_takes(job):
    run=latest_run(job)
    folders=sorted((d for d in run.glob("attempt-*") if d.is_dir() and d.name[8:].isdigit()),
                   key=lambda d:int(d.name[8:]), reverse=True)
    for folder in folders:
        path=folder/"review.json"
        if path.is_file():
            report=read(path)
            if report.get("verdict")=="REVISE" and any(
                c.get("id")=="take_completeness" and c.get("verdict")=="REVISE"
                for c in report.get("checks",[])
            ) and (folder/"storyboard.json").is_file() and (run/"keep.json").is_file():
                return folder
            break
    return None


def can_recut(job):
    if not all((job/n).is_file() for n in ("raw.mp4","raw-words.json","usage.jsonl")):
        return False
    if (job/"usage.pending").exists():
        return False
    return reviewed_takes(job) is not None


def supervised_takes(run, source, raw_words, selection, original_duration, audit, progress,
                     speed, script, feedback=None):
    from stage_reviews import review_rough_cut, revise_takes, source_ranges
    tried=set()
    number=1
    while True:
        folder=run/f"take-{number}"
        folder.mkdir()
        if feedback is not None:
            write(folder/"feedback-to-opus.json",feedback)
            progress(f"Opus уточняет границы дублей · версия {number}")
            selection=revise_takes(raw_words,selection,feedback,audit)
        spans=source_ranges(selection,original_duration)
        fingerprint=tuple(tuple(pair) for pair in spans)
        if fingerprint in tried:
            raise ValueError("Opus вернул уже проверенную склейку. Нужен ручной разбор замечаний.")
        tried.add(fingerprint)
        keep={"keep":spans,"max_pause":0.30,"keep_pause":0.22,"snap":selection.get("snap",0.04)}
        write(folder/"selection.json",keep)
        candidate=folder/"rough-cut.mp4"
        freeze_paced_cut(source,folder/"selection.json",candidate,speed,script,progress)
        mapping=candidate.with_suffix(".map.json")
        progress(f"Argon смотрит склейку и слушает переходы · версия {number}")
        feedback=review_rough_cut(candidate,raw_words,keep,read(mapping),audit)
        write(folder/"stage-review.json",{**feedback,"stage":"rough_cut","cut_sha256":sha(candidate)})
        if feedback["verdict"]=="PASS":
            os.link(candidate,run/"cut.mp4")
            os.link(mapping,run/"cut.map.json")
            write(run/"keep.json",keep)
            return
        if feedback["verdict"]!="REVISE":
            raise ValueError("Argon не смог подтвердить качество склейки. Нужна проверка исходника.")
        number+=1


def unreviewed_render(run):
    attempts=[p for p in run.glob("attempt-*") if p.is_dir() and p.name[8:].isdigit()]
    if not attempts:
        return None
    folder=max(attempts,key=lambda p:int(p.name[8:]))
    if any((folder/name).exists() for name in ("review.json","revision-request.json","budget-stop.json")):
        return None
    required=("render.mp4","frozen-audio.json","project/gate-report.txt","project/reel-meta.json",
              "project/boxes.json","stage-review.json","plan.json","brand-mentions.json")
    if (all((folder/name).is_file() for name in required)
            and read(folder/"frozen-audio.json").get("mode")=="stream_copy"
            and read(folder/"stage-review.json").get("verdict")=="PASS"):
        return folder
    return None


def can_resume(job):
    required=("raw.mp4","cut.mp4","words.json","raw-words.json","keep.json","head.json",
              "cut.map.json","usage.jsonl")
    run=latest_run(job)
    if not all(((job if name in ("usage.jsonl","raw.mp4","raw-words.json") else run)/name).is_file() for name in required) or (job/"usage.pending").exists():
        return False
    try:
        costs=cost_report(job/"usage.jsonl")
        if not costs["requests_logged"] or costs["requests_without_cost"]:
            return False
        if not unreviewed_render(run):
            resume_point(run)
    except (ValueError,OSError,TypeError,KeyError):
        return False
    return True


def editorial_iterations(job, create_attempt, progress, *, resume=False, finish_render=None):
    from job_budget import BudgetExceeded
    rendered=unreviewed_render(job) if resume and finish_render else None
    number,previous=(int(rendered.name[8:]),None) if rendered else (resume_point(job) if resume else (1,None))
    while True:
        folder=job/f"attempt-{number}"
        if rendered is None:
            folder.mkdir()
        feedback="" if previous is None else json.dumps(previous,ensure_ascii=False)
        if previous is not None:
            write(folder/"feedback-to-opus.json",previous)
            progress(f"Opus дорабатывает монтаж · попытка {number}")
        try:
            if rendered:
                progress("Продолжаем проверку сохранённого MP4")
                rendered=None
                result=finish_render(folder)
            else:
                result=create_attempt(folder,feedback)
        except BudgetExceeded as err:
            write(folder/"budget-stop.json",{"reason":str(err)})
            raise
        except RevisionNeeded as err:
            evidence=dict(err.evidence)
            if err.manual:
                evidence["manual"]=True
            write(folder/"revision-request.json",evidence)
            if err.manual:
                raise ValueError(f"Нужна ручная проверка исходной речи или доказательств. Замечания в full/attempt-{number}/revision-request.json.") from None
            # The shared ledger checks the remaining budget before each paid call.
            previous=revision_feedback(folder)
            number+=1
            continue
        return result,number


def local_defect(folder, stage):
    if stage=="build":
        gate=folder/"project/gate-report.txt"
        if not gate.exists():
            return None
        details=gate.read_text().strip()
        if not details or details=="clean":
            return None
        failures=details.splitlines()
    else:
        report=folder/"qa/postcheck.json"
        if not report.exists():
            return None
        failures=read(report).get("failures")
        if not isinstance(failures,list) or not failures:
            return None
    # Time-alignment or repeated speech requires comparing/re-cutting takes.
    manual=any(any(term in str(v).lower() for term in ("out of sync","repeated take","repeat:","audio duration")) for v in failures)
    return RevisionNeeded({"stage":stage,"local_failures":failures[:100]},manual=manual)


def settings():
    skill = Path(os.environ.get("REEL_SKILL", REPO / "skills/reel-build")).expanduser().resolve()
    venv = skill / ".venv/bin/python"
    python = os.environ.get("REEL_PYTHON") or (str(venv) if venv.is_file() else sys.executable)
    refs = Path(os.environ.get("REEL_REFERENCE_DIR", REPO / "references")).expanduser()
    return skill, python, [refs / f"{name}.mp4" for name in "ABC"]


def project_key(load=False):
    if os.environ.get("REEL_OPENROUTER_API_KEY", "").strip():
        return True
    try:
        attrs = KEY_FILE.lstat()
        if not stat.S_ISREG(attrs.st_mode) or attrs.st_uid != os.getuid() or attrs.st_mode & 0o077:
            return False
        if load:
            key = KEY_FILE.read_text().strip()
            if not key or any(c.isspace() for c in key):
                return False
            os.environ["REEL_OPENROUTER_API_KEY"] = key
        return attrs.st_size > 0
    except OSError:
        return False


def availability():
    skill, python, refs = settings()
    missing = []
    if not (libraries()/"catalog.json").is_file():
        missing.append("Каталог логотипов")
    if not (libraries()/"html-components/components").is_dir():
        missing.append("Библиотека HTML-компонентов")
    for command in ("ffprobe", "ffmpeg", "node", "npm", "hyperframes"):
        if not shutil.which(command):
            missing.append(command)
    if not (skill / "scripts/reel.py").is_file() or not (skill / "SKILL.md").is_file():
        missing.append("Скилл reel-build")
    for rel in ("node_modules/gsap/dist/gsap.min.js",
                "node_modules/@fontsource-variable/golos-text/files/golos-text-cyrillic-wght-normal.woff2",
                "node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-cyrillic-500-normal.woff2"):
        if not (skill / rel).is_file():
            missing.append("Шрифты и GSAP скилла (npm ci)")
            break
    try:
        modules = ("faster_whisper", "numpy", "cv2", "PIL", "pytest")
        probe = subprocess.run([python, "-c",
                "import importlib.util,sys;print(' '.join(n for n in sys.argv[1:] if not importlib.util.find_spec(n)))",
                *modules], capture_output=True, text=True, timeout=5)
        if probe.returncode:
            missing.append("Интерпретатор REEL_PYTHON")
        elif probe.stdout.strip():
            missing.append("Python: " + probe.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        missing.append("Интерпретатор REEL_PYTHON")
    if not Path(os.environ.get("CHROME_PATH","/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")).is_file():
        missing.append("Chrome для измерения композиции")
    missing.extend("Референс " + ref.stem for ref in refs if not ref.is_file())
    if not project_key():
        missing.append("Ключ OpenRouter проекта reel")
    return {"ready": not missing, "missing": missing}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
        return digest.hexdigest()


def cost_report(audit):
    entries = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()] if audit.exists() else []
    amounts = [entry.get("usage", {}).get("cost") if isinstance(entry.get("usage"),dict) else None for entry in entries]
    known = sum((Decimal(str(value)) for value in amounts if value is not None), Decimal(0))
    return {"cost_usd": None if None in amounts else float(known), "known_cost_usd": float(known),
            "requests_logged": len(entries), "requests_without_cost": amounts.count(None)}


def freeze_paced_cut(source, keep, cut, speed, script, progress):
    """Keep source timestamps and map every retained piece onto the faster output."""
    with tempfile.TemporaryDirectory(dir=cut.parent) as temp:
        unpaced = Path(temp)/"unpaced.mp4"
        script("Склеиваем выбранные дубли", "cut_takes.py", source, "--keep", keep, "-o", unpaced)
        progress(f"Ускоряем склейку ×{speed:g} с сохранением высоты голоса")
        accelerate(unpaced, cut, speed)
        mapping = read(unpaced.with_suffix(".map.json"))
    mapping["playback_speed"] = speed
    mapping["cut_duration"] /= speed
    for piece in mapping["pieces"]:
        piece["cut"] = [value / speed for value in piece["cut"]]
    write(cut.with_suffix(".map.json"), mapping)


def full_edit(src, dst, progress, *, resume=False, recut=False, speed=DEFAULT_SPEED):
    config = availability()
    if not config["ready"]:
        raise ValueError("Для полного монтажа нужны: " + ", ".join(config["missing"]))
    if not project_key(load=True):
        raise ValueError("Проверьте отдельный ключ проекта reel.")
    from model_stages import argon_review, opus_keep, opus_plan

    skill, python, refs = settings()
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst or dst.exists():
        raise ValueError("Для нового монтажа нужен отдельный выходной файл.")
    _, audio, original_duration = metadata(src)
    if not audio:
        raise ValueError("Для отбора дублей и титров нужна дорожка с речью.")
    for ref in refs:
        metadata(ref)
    identities = [sha(p) for p in refs]
    if len(set(identities)) != 3:
        raise ValueError("Нужны три разных референса A/B/C.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    job = dst.parent / "full"
    root_job=job
    if resume and not job.is_dir():
        raise ValueError("Сохранённый монтаж не найден.")
    job.mkdir(mode=0o700, exist_ok=resume)
    pace_path = root_job/"pace.json"
    if resume and pace_path.exists():
        speed = read(pace_path)["speed"]
    speed = check_speed(speed)
    if not resume:
        write(pace_path, {"speed":speed})
    audit = root_job / "usage.jsonl"
    reviewed=None
    if recut:
        if not resume or not can_recut(root_job):
            raise ValueError("Нет ревью с замечаниями к дублям для нового монтажа.")
        if not pace_path.exists():
            write(pace_path, {"speed":speed})
        reviewed=reviewed_takes(root_job)
        prior_run=latest_run(root_job)
        number=1 if prior_run==root_job else int(prior_run.name[6:])+1
        job=root_job/f"recut-{number}"
        job.mkdir(mode=0o700)
        write(job/"origin.json",{"review":str((reviewed/"review.json").relative_to(root_job)),
                                "review_sha256":sha(reviewed/"review.json")})
    elif resume:
        job=latest_run(root_job)
        if (job/"origin.json").is_file():
            origin=read(job/"origin.json")
            original_review=(root_job/origin["review"]).resolve()
            if not original_review.is_relative_to(root_job) or sha(original_review)!=origin["review_sha256"]:
                raise ValueError("Не удалось проверить исходное ревью для пересборки.")
            reviewed=original_review.parent
    rubric = RUBRIC
    env = dict(os.environ, DO_NOT_TRACK="1", PYTHONDONTWRITEBYTECODE="1")
    env["HF_HOME"] = os.environ.get("REEL_HF_HOME", str(REPO/"jobs/.hf-cache"))
    # The renderer, FFmpeg, browser and Whisper never need provider credentials.
    env.pop("REEL_OPENROUTER_API_KEY", None)
    env.pop("OPENROUTER_API_KEY", None)

    def run(label, args, timeout=3600):
        progress(label)
        with (job/"pipeline.log").open("ab") as log:
            try:
                subprocess.run([str(val) for val in args], cwd=job, env=env, check=True,
                               stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout)
            except (OSError, subprocess.SubprocessError):
                raise ValueError(label + ": проверка не пройдена. Подробности в full/pipeline.log.") from None

    def script(label, name, *args):
        if name == "reel.py" and args[0] == "build":
            run(label, [python, HERE/"source_scene.py", skill/"scripts", *args])
        else:
            run(label, [python, skill/"scripts"/name, *args])

    source, cut = root_job/"raw.mp4", job/"cut.mp4"
    words, raw_words = job/"words.json", root_job/"raw-words.json"
    head=job/"head.json"
    whisper = os.environ.get("REEL_WHISPER_MODEL", "large-v3-turbo")
    try:
        run("Проверяем тесты монтажного скилла",
            [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", skill/"tests"])
        if resume and not recut:
            if not can_resume(root_job):
                raise ValueError("Для продолжения нужны склейка, разметка и журнал расходов исходного задания.")
            progress("Продолжаем по сохранённой склейке и журналу расходов")
        else:
            feedback=None
            if reviewed:
                feedback=read(reviewed/"review.json")
                feedback={**feedback,"checks":[c for c in feedback["checks"] if c.get("id") in
                          ("take_completeness","transitions","body_progression","hook","information_fidelity")],
                          "cut_map":read(reviewed.parent/"cut.map.json")}
                selection=read(reviewed.parent/"keep.json")
            else:
                run("Подготавливаем видеодорожку 1080 × 1920", ["ffmpeg","-nostdin","-v","error",
                    *INPUT,"-i",src,"-map","0:V:0","-map","0:a:0","-vf",
                    "fps=30,scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1",
                    "-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",
                    "-t",f"{original_duration:.6f}","-map_metadata","-1",source])
                run("Распознаём речь и перепроверяем спорные слова", [python,HERE/"local_transcript.py",source,"-o",raw_words,"--model",whisper])
                if not read(raw_words).get("words"):
                    raise ValueError("В исходнике не распознана речь.")
                from stage_reviews import inspect_source
                progress("Argon смотрит исходник и отмечает монтажные решения по времени")
                source_review=inspect_source(source,raw_words,audit)
                write(root_job/"source-review.json",{**source_review,"source_sha256":sha(source)})
                if source_review["status"]!="OK":
                    raise ValueError("Argon не смог проверить видео и звук исходника.")
                progress("Opus выбирает дубли по разбору Argon")
                selection=opus_keep(raw_words,skill,rubric,audit,
                                    json.dumps(source_review["notes"],ensure_ascii=False))
            supervised_takes(job,source,raw_words,selection,original_duration,audit,progress,speed,script,feedback)
            previews=dst.parent/"previews"
            previews.mkdir(exist_ok=True)
            staged_preview=job/"cut-preview.mp4"
            os.link(cut,staged_preview)
            staged_preview.replace(previews/f"{speed:g}.mp4")
            run("Перепроверяем слова на ускоренной склейке", [python,HERE/"local_transcript.py",cut,"-o",words,"--model",whisper])
            script("Измеряем положение лица","measure_head.py",cut,"-o",head)
        from brands import prepare_brands
        from creative_context import creative_context
        initial=prepare_brands(words,libraries()/"catalog.json",job/"available-assets")
        write(job/"initial-brand-mentions.json",initial)

        if reviewed:
            write(audit.with_name("compact-final-reserve.json"),
                  {"final_seconds":metadata(cut)[2],"reference_seconds":[metadata(ref)[2] for ref in refs]})

        def create_attempt(folder,feedback):
            if not feedback:
                progress("Opus строит сцены по словам")
            context=creative_context(words,libraries(),skill,initial,feedback=feedback)
            source_review_path=root_job/"source-review.json"
            if source_review_path.is_file():
                reviewed_source=read(source_review_path)
                context["source_playback_notes"]={"timeline":"original_source_seconds",
                    "instruction":"Match the quoted speech to frozen-cut words before timing any scene.",
                    "notes":reviewed_source["notes"]}
            if material:
                context['source_asset']={**material[1],'suggested_word_index':material[2],
                    'suggested_source_cues':suggested_cues(material,read(words)),
                    'instruction':'Identify the matching spoken phrase and choose source_cues=[{asset_id,word_index,duration}, ...], each duration in [1,12] seconds. Plan genuine evidence at relevant moments, minimum 30%, target 50% of illustrated time. Use the related_sources with matching subject matter when present. Avoid repetition for padding. Its screenshot and publisher credit appear above the speaker. Preserve legibility and avoid conflicting UI in that interval.'}
            write(folder/"creative-context.json",context)
            revision=json.loads(feedback) if feedback else None
            audio_only=bool(revision and revision["corrections"].get("restore_frozen_audio")
                            and not revision["corrections"]["local_failures"])
            try:
                if reviewed and (not feedback or revision["corrections"].get("stage") in ("storyboard","argon","build","postcheck")):
                    from timeline_transfer import transfer_storyboard
                    from compact_editor import direct_mapped
                    if not feedback:
                        old=reviewed.parent
                        mapped=None
                        versions=sorted((d for d in old.glob("attempt-*") if d.name[8:].isdigit() and (d/"storyboard.json").is_file()),
                                        key=lambda d:int(d.name[8:]),reverse=True)
                        for version in versions:
                            try:
                                mapped,notes=transfer_storyboard(read(version/"storyboard.json"),
                                    read(old/"words.json"),read(words),read(old/"cut.map.json"),read(cut.with_suffix(".map.json")),skill)
                                break
                            except (ValueError,KeyError,IndexError):
                                continue
                        if mapped is None:
                            raise ValueError("Не удалось перенести план Opus на новую склейку.")
                        findings=read(reviewed/"review.json").get("checks",[])
                    else:
                        mapped=revision["previous_storyboard"]
                        notes={}
                        findings=revision["corrections"].get("issues",[])
                    if material:
                        notes={**notes,'available_source':context['source_asset']}
                    write(folder/"mapped-plan.json",mapped)
                    storyboard,corrected=direct_mapped(mapped,notes,words,skill,audit,findings)
                    write(folder/"transcript-before.json",read(words))
                    write(words,corrected)
                elif audio_only:
                    storyboard=revision["previous_storyboard"]
                else:
                    storyboard=opus_plan(words,skill,rubric,audit,feedback=feedback,use_kit=True,creative_context=context,allow_style_findings=True)
            except ValueError as e:
                # Only renderer validation of a received model draft qualifies.
                # Transport, provider, credentials and billing failures escape.
                if not isinstance(getattr(e,"storyboard",None),dict):
                    raise
                write(folder/"storyboard.json",e.storyboard)
                raise RevisionNeeded({"stage":"plan","local_failures":[str(e)]}) from None
            if material:
                try:
                    import source_scene
                    native_source, manifest = source_scene.renderer_plan(storyboard, read(words), skill)
                except ValueError as exc:
                    write(folder/"storyboard.json",storyboard)
                    raise RevisionNeeded({"stage":"plan","local_failures":[str(exc)]}) from None
                storyboard['real_media']=manifest
                write(folder/"real-media.json",manifest)
            write(folder/"storyboard.json",storyboard)
            if revision and not audio_only and storyboard==revision["previous_storyboard"]:
                raise RevisionNeeded({"stage":"plan","local_failures":["Opus returned the unchanged rejected storyboard."]})
            from stage_reviews import review_storyboard
            progress("Argon проверяет смысл, последовательность сцен и призыв по плану")
            stage=review_storyboard(words,storyboard,audit)
            write(folder/"stage-review.json",{**stage,"stage":"storyboard"})
            if stage["verdict"]!="PASS":
                issues=[c for c in stage["checks"] if c["verdict"]!="PASS"]
                raise RevisionNeeded({"stage":"storyboard","issues":issues},manual=stage["verdict"]=="UNVERIFIED")
            plan=folder/"plan.json"
            project=folder/"project"
            rendered=folder/"render.mp4"
            qa=folder/"qa"
            progress("Подбираем логотипы к словам и готовим компоненты")
            candidates=storyboard.get("brand_candidates",[])
            omissions=storyboard.get("brand_omissions",[])
            brands=configure_graphics(folder,skill,words,head,candidates,omissions)
            if material:
                brands['real_media']=manifest
                write(folder/'brand-mentions.json',brands)
            native={k:v for k,v in storyboard.items() if k not in ("brand_candidates","brand_omissions")}
            if material:
                native["scenes"] = native_source["scenes"]
                source_scene.prepare_images(material[0], folder/"assets", manifest)
            write(plan,native)
            try:
                script("Проверяем сцены, титры и тайминг","reel.py","build","--cut",cut,"--words",words,
                       "--plan",plan,"--config",folder/"reel_config.json","--head",head,"--review-style","--project",project)
            except ValueError:
                defect=local_defect(folder,"build")
                if defect: raise defect from None
                raise
            if material:
                attach_source(project,material[0],manifest)
            script("Рендерим видео в HyperFrames","reel.py","render","--project",project,"-o",rendered)
            # This composition has exactly one narration track: the approved cut.
            # Copy its original AAC packets and edit list before measuring delivery.
            corrected=folder/"frozen-audio.mp4"
            run("Возвращаем оригинальную озвучку склейки", ["ffmpeg","-nostdin","-n","-v","error",
                "-i",rendered,"-i",cut,"-map","0:v:0","-map","1:a:0","-map_metadata","-1",
                "-c","copy","-movflags","+faststart",corrected])
            corrected.replace(rendered)
            write(folder/"frozen-audio.json",{"audio_source":"cut.mp4","mode":"stream_copy"})
            return finish_render(folder,brands)

        def finish_render(folder,brands=None):
            plan,project,qa=folder/"plan.json",folder/"project",folder/"qa"
            rendered=folder/"render.mp4"
            if brands is None:
                brands=read(folder/"brand-mentions.json")
            pre,post=project/"gate-report.txt",qa/"postcheck.json"
            try:
                run("Проверяем готовые кадры и звук",[python,HERE/"render_qa.py",skill/"scripts",rendered,
                       "--project",project,"--cut",cut,"--out",qa])
            except ValueError:
                from model_stages import check_post
                if not post.is_file():
                    raise
                check_post(pre,post,allow_style_findings=True)
            progress("Gemini Argon сравнивает видео с референсами A/B/C")
            final_reviewer=argon_review
            if reviewed or sum(Path(p).stat().st_size for p in (rendered,*refs))>12*1024*1024:
                from compact_review import review as final_reviewer
            review=final_reviewer(rendered,refs,pre,post,rubric,audit,raw_words=raw_words,cut_words=words,brands=brands,allow_style_findings=True)
            write(folder/"review.json",review)
            if review.get("verdict")!="PASS":
                problems=[r for r in review["checks"] if r.get("verdict")!="PASS"]
                if not problems: raise ValueError("Не получены конкретные замечания рецензента.")
                if any(r["id"]=="take_completeness" and r["verdict"]=="REVISE" for r in problems):
                    raise RecutRequested()
                manual=any(r["id"]=="audio_sync" or r.get("verdict")=="UNVERIFIED" for r in problems)
                numbers=read(post)["numbers"]
                raise RevisionNeeded({"stage":"argon","score":review.get("score"),"issues":problems,
                    "precheck":pre.read_text().strip(),"postcheck_failures":read(post).get("failures",[]),"render_sha256":sha(rendered),
                    "local_numbers":{k:numbers[k] for k in ("duration","palette","shot_types","repeated_takes") if k in numbers}},
                    manual=manual)
            return rendered,plan,review

        from source_scene import using_material
        material = supplied_source(root_job.parent,read(words))
        with using_material(material):
            (rendered,plan,review),attempt_count=editorial_iterations(job,create_attempt,progress,resume=resume and not recut,finish_render=finish_render)
        final_video, final_audio, duration = metadata(rendered)
        if final_video["width"] != 1080 or final_video["height"] != 1920 or not final_audio:
            raise ValueError("Проверка выходных дорожек не пройдена.")
        mapping=read(cut.with_suffix(".map.json"))
        result={"mode":"Полный монтаж reel-build", "original_seconds":original_duration, "output_seconds":duration,
                "removed_seconds":round(max(0,original_duration-duration),2),"cuts":len(mapping["removed"]),
                "playback_speed":mapping.get("playback_speed",1.0),
                "score":review.get("score"),"editorial_attempts":attempt_count,**cost_report(audit)}
        write(job/"delivery.json", {**result,"source_sha256":sha(src),"cut_sha256":sha(cut),
                                   "plan_sha256":sha(plan),"output_sha256":sha(rendered),"reference_sha256":identities})
        os.link(rendered,dst)
        return result
    except RecutRequested:
        return full_edit(src,dst,progress,resume=True,recut=True,speed=speed)
    finally:
        write(root_job/"cost.json",cost_report(audit))
