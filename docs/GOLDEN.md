# Acceptance for a finished talking-head reel

Use this contract for the full HyperFrames montage. A rough cut can demonstrate upload, silence trimming and MP4 playback. Its successful delivery establishes only those three capabilities. Record a separate result for every full-montage stage: PASS, FAIL or MISSING EVIDENCE. An unrun check stays MISSING EVIDENCE.

## Stage-reviewed montage

The reviewer checks source take choices against the original speech, then reviews the storyboard against the frozen transcript, then watches the actual rendered MP4 against references A/B/C. Use the appropriate timeline and evidence for each stage. Style measurements (layout shares, cadence, visual density, negative space and palette) are reference targets. Judge their effect on viewer attention, readability and meaning, and cite a timecoded consequence for a revision. Preserve every measured finding in the evidence. Unsupported files, missing audio, broken timelines, real sync errors and missing required evidence must be resolved before delivery.

## Run the supplied gates

Use a working copy of the supplied skill with its Python and Node dependencies, HyperFrames and Chrome installed. Run from one job directory containing the frozen cut, its corrected word timings, measured head track, configuration and plan. Set REEL_SKILL to the working copy. Run each command only if the preceding command succeeds.

```sh
set -eu
: "${REEL_SKILL:?set the path to the reel-build working copy}"
python -m pytest -q "$REEL_SKILL/tests"
python "$REEL_SKILL/scripts/reel.py" build --cut cut.mp4 --words words.json \
  --plan plan.json --config reel_config.json --head head.json --project build/reel
python "$REEL_SKILL/scripts/reel.py" render --project build/reel -o reel.mp4
python "$REEL_SKILL/scripts/reel.py" check --cut cut.mp4 --project build/reel \
  --render reel.mp4 --out qa
python -c 'import json; from pathlib import Path; assert json.loads(Path("qa/postcheck.json").read_text())["failures"] == []'
ffprobe -v error -show_entries stream=codec_type,width,height,avg_frame_rate,duration -of json reel.mp4
```

If a delivery encode follows rendering, repeat the check and probe on the exact file being delivered. Store the source, frozen cut, plan and delivery-file hashes with the review. Run the build without the skip-check switch.

| Gate | Acceptance | Evidence |
|---|---|---|
| Source and cut | One complete take per thought. Preserve claims, numbers, names and intent. Listen across every join for clipped syllables, repeated starts and missing words. Any deliberate repeat has an explanation in the plan. | Original and frozen-cut time ranges in keep.json, raw and cut transcripts, reviewer timestamps, repeated_takes = 0 after allowed exceptions. |
| Output and sync | 1080 × 1920, 30 fps, audio present. Video duration within 0.05 s of frozen cut and audio duration within 0.04 s. At each tested full-speaker shot, same-time face SSIM exceeds both ±0.5 s controls. | ffprobe output and postcheck numbers.duration and numbers.sync. |
| Framing and pacing | Split seam at y=960. Plan design shares: split 50–60%, visual 25–30%, speaker 10–20%; plan gate allows ±3 percentage points. Same-type runs at most 4.5 s. Full-speaker shots target 1.3–3.0 s with ±0.05 s plan tolerance. At 10 fps, classified-vs-planned layout disagreements outside cut transition windows must total at most 4% of sampled frames. | reel-meta.json, boxes.json, numbers.shot_types, frame_types_10fps. |
| Hook, motion and layout | Frame zero begins with legible spoken content. Hook sharpness at least 55% and caption contrast at least 85% of settled values. Maximum static interval 1.5 s, change threshold 0.4% of visual area. Coverage floors 30% for split and 25% for full visual. Full-visual empty band at most 18% of frame height. Bottom UI zone y=1520–1920 at most 2% ink on full visuals. Light backgrounds at most 25% of visual time. | Shot and ending contact sheets, measured scene boxes, gate-report.txt and postcheck.json. |
| Text and captions | Caption style targets 60 px uppercase, up to 2 lines with 1–3 words per line. Split caption bottom at most y=944. Full-visual caption starts at y=1320. Speaker captions clear the detected face. Missing face detections above 10% of expected caption frames fail. Mockup body text at least 32 px, monospace at least 40 px, measured contrast at least 4.5:1 where the pre-render check applies. | boxes.json, caption contact sheet, numbers.captions and inspection at phone size. Check script/style output for names, prices, branding and spelling. |
| Closing action | When the source and brief contain a CTA, the window targets 5–8 s with ±0.05 s plan tolerance. Final code-word box at least 90 px tall; finish typing at least 2.5 s before the end. Verify exact spelling, visibility and absence of overlap throughout the hold. If the brief requires a CTA absent from the source, seek a supplied CTA or revised brief. | Plan CTA and reminder, numbers.codeword, ending contact sheet and the last 6 s at playback speed. |
| Delivery | Build and post-render commands both exit zero. Inspect the delivered MP4 on playback. A missing required review or failed technical delivery check blocks publication. In stage-reviewed mode, give Argon all measured style deviations and record its judgment on the actual reel. | gate-report.txt, hyperframes-check.txt, render.log, qa/postcheck.json and reviewer verdict. |

## Independent visual review

Opus owns the editorial choices and repair plan. Gemini independently watches the resulting render, listens to the cut and inspects the source or references available for that job. Record which media, frames and audio the reviewer actually received. A reviewer supplied only stills can assess typography and composition; speech continuity, word timing and audible cuts require playback evidence. These are roles for the full process; this document does not invoke a model or authorize a charge.

Review the hook, one middle split, one full visual, every speaker transition and the ending. For each issue record the render timestamp, matching source or reference timestamp if available, visible or audible defect, and proposed correction. Cover take completeness, correspondence between speech and graphics, phone-size readability, face/hand framing, caption timing, shot rhythm and CTA legibility. A technical pass still goes back for correction when the reviewer finds a lost phrase, unsupported claim, wrong CTA or obstructed face. Preserve the new render and re-run the failed checks after repair.

## Golden data and limitations

The attachment includes plans, keep ranges, configurations and one word-timing fixture. These provide regression inputs for the supplied tests. A new recording needs its own transcript and keep ranges. A reference CTA, number or identity never supplies missing content for the new recording.

The A/B/C reference videos and their original frames are absent from the attachment. Record reference similarity as MISSING EVIDENCE until the approved reference media are attached. The documented geometry, timing and type rules can be checked independently. For an owner-approved golden recording, freeze its source hash, annotated takes, critical spoken facts, expected word corrections, required scenes and expected QA failures for defective variants. Record the provenance of each annotation before evaluating a new pipeline revision.

### Brand identity and timing

At the first meaningful brand introduction and at comparisons where identity changes, anchor the authentic mark to the spoken name on the frozen timeline. Use the Claude family mark for Claude Opus, the Gemini mark for Gemini Neon, and the Anthropic corporate mark when the speaker discusses Anthropic itself. Opus and Neon are model names. Avoid invented model icons, decorative parent marks and a new flash on every repetition.

Argon reviews the intended identity at storyboard time and the visible logo against the audio in the final **brand_identity_timing** check, including videos whose resolver found zero cues. At phone size the silhouette, aspect ratio, contrast, dwell and clearance must make the mark recognizable at the spoken mention. Captions or an incidental tiny logo in a screenshot do not substitute for a cue. Verify the catalog source and file; for the pinned AI brands retain the publisher URL and SHA-256. Return the asset ID, visible start/end and observed placement. Missing or wrong identity, late entry, occlusion or unreadable marks require a timecoded fix for Opus; uncertain evidence requires independent review. Document warranted repeat omissions. Keep brand-mentions.json with the job.

### Whole-story review (Argon)
Check opening promise and payoff, logical progression through the body, fidelity of on-screen information to the source, focal attention and the explicit closing action. Use a timestamped observation for every check. A mark that steals focus, a label that contradicts the speaker, or an illegible CTA can block delivery even if every technical assertion passes. Preserve the original spoken message. Estimated audience retention is a qualitative editorial judgment, not a measured viewer metric.

### Real media mix (Argon / real_media_mix)

Use a real screenshot of the product or story, a relevant photograph, original B-roll or a rendered, sourced 3D model as a focal illustration. Retain the source URL, asset ID, rights or permission statement, credits where required, and time ranges. A 3D character may illustrate a generic role. Identifiable people and real events require accurately attributed material.

The minimum is 30% of supplemental illustration time. Aim for about 50% where sources help explain the speech. Measure at delivery speed. The denominator is the union of split and full-visual intervals. The numerator is their intersection with qualifying source placements. Overlapping assets count once. Presenter video, captions, standalone logos, a decorative thumbnail, generated mockups and a recognizable brand name drawn in HTML contribute zero. HTML may frame or animate a real source.

Opus proposes material and timing. Argon checks the planned mix at storyboard review and the actual visible intervals at final MP4 review. A final PASS requires a traceable source, a matching asset ID, recognizable and readable material, alignment with the spoken point, and at least 30% measured coverage. State seconds, percentage, exact intervals and a correction for a weak insert. Unverifiable attribution or missing evidence requires additional source material. In a 20-second illustration track, 5.9 seconds requires revision; 6 meaningful seconds meets the floor; 10 seconds meets the target.
