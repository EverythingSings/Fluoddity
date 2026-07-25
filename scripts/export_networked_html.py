#!/usr/bin/env python3
"""Package a video artwork as a self-contained interactive HTML file.

The generated document makes no network requests. Video bytes are stored as
base64 text and converted to a Blob URL at runtime so seeking works inside a
sandboxed iframe. Pointer/touch dragging scrubs time horizontally and chooses
playback speed vertically; a tap or Space toggles playback.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import mimetypes
import os
from pathlib import Path
from string import Template
from typing import Any


NETWORKED_ART_LIMIT_BYTES = 95_000_000


STANDALONE_TEMPLATE = Template(
    r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="artifact-schema" content="fluoddity.networked-html-artifact.v1">
<title>$TITLE</title>
<style>
*{box-sizing:border-box}
html,body{width:100%;height:100%;margin:0;overflow:hidden;background:$BACKGROUND}
body{font-family:system-ui,sans-serif}
#fluoddity-artifact{position:relative;width:100%;height:100%;display:grid;place-items:center;isolation:isolate;background:$BACKGROUND;touch-action:none;user-select:none}
#fluoddity-artifact video{display:block;width:100%;height:100%;object-fit:cover;background:$BACKGROUND}
#fluoddity-artifact.is-interacting video{filter:saturate(1.08) brightness(1.03)}
#fluoddity-start{position:absolute;inset:50% auto auto 50%;transform:translate(-50%,-50%);border:1px solid rgba(255,255,255,.45);border-radius:999px;background:rgba(8,12,22,.72);color:#fff;padding:.7rem 1rem;font:500 14px/1 system-ui,sans-serif;letter-spacing:.04em;cursor:pointer}
#fluoddity-start[hidden]{display:none}
#fluoddity-status{position:absolute;inline-size:1px;block-size:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
@media (prefers-reduced-motion:reduce){#fluoddity-artifact video{filter:none!important}}
</style>
</head>
<body>
<main id="fluoddity-artifact" aria-label="$ARIA_LABEL">
  <video id="fluoddity-video" muted loop playsinline preload="auto" disablepictureinpicture poster="$POSTER_URI" aria-label="$ARIA_LABEL"></video>
  <button id="fluoddity-start" type="button" hidden>Play</button>
  <span id="fluoddity-status" role="status" aria-live="polite"></span>
</main>
<script id="fluoddity-video-data" type="application/octet-stream">$VIDEO_BASE64</script>
<script id="fluoddity-metadata" type="application/json">$METADATA_JSON</script>
<script>
(()=>{
  "use strict";
  const root=document.getElementById("fluoddity-artifact");
  const video=document.getElementById("fluoddity-video");
  const start=document.getElementById("fluoddity-start");
  const status=document.getElementById("fluoddity-status");
  const encoded=document.getElementById("fluoddity-video-data").textContent.trim();
  const metadata=JSON.parse(document.getElementById("fluoddity-metadata").textContent);
  window.FLUODDITY_ARTIFACT=Object.freeze(metadata);

  const chunks=[];
  const chunkChars=1048576;
  for(let offset=0;offset<encoded.length;offset+=chunkChars){
    const raw=atob(encoded.slice(offset,Math.min(offset+chunkChars,encoded.length)));
    const bytes=new Uint8Array(raw.length);
    for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
    chunks.push(bytes);
  }
  const objectUrl=URL.createObjectURL(new Blob(chunks,{type:metadata.video.mime}));
  video.src=objectUrl;
  document.getElementById("fluoddity-video-data").remove();

  let dragging=false;
  let moved=false;
  let wasPlaying=true;
  let resumeAfterVisibility=false;
  let downX=0;
  let downY=0;

  const clamp=(value,min,max)=>Math.min(max,Math.max(min,value));
  const announce=(message)=>{status.textContent=message};
  const play=()=>{
    start.hidden=true;
    return video.play().catch(()=>{
      start.hidden=false;
      announce("Playback is paused. Activate Play to begin.");
    });
  };
  const toggle=()=>{
    if(video.paused){
      play();
      announce("Playing");
    }else{
      video.pause();
      announce("Paused");
    }
  };
  const pointerValues=(event)=>{
    const rect=root.getBoundingClientRect();
    const x=clamp((event.clientX-rect.left)/Math.max(rect.width,1),0,1);
    const y=clamp((event.clientY-rect.top)/Math.max(rect.height,1),0,1);
    return{x,y};
  };
  const applyPointer=(event)=>{
    const {x,y}=pointerValues(event);
    if(Number.isFinite(video.duration)&&video.duration>0){
      video.currentTime=Math.min(video.duration-.001,x*video.duration);
    }
    video.playbackRate=0.35+(1-y)*1.65;
  };

  root.addEventListener("pointerdown",(event)=>{
    if(event.button!==0&&event.pointerType==="mouse")return;
    dragging=true;
    moved=false;
    wasPlaying=!video.paused;
    downX=event.clientX;
    downY=event.clientY;
    root.classList.add("is-interacting");
    try{root.setPointerCapture(event.pointerId)}catch{}
    video.pause();
    event.preventDefault();
  });
  root.addEventListener("pointermove",(event)=>{
    if(!dragging)return;
    moved=moved||Math.hypot(event.clientX-downX,event.clientY-downY)>5;
    if(moved)applyPointer(event);
    event.preventDefault();
  });
  const endPointer=(event)=>{
    if(!dragging)return;
    moved=moved||Math.hypot(event.clientX-downX,event.clientY-downY)>5;
    if(moved)applyPointer(event);
    dragging=false;
    root.classList.remove("is-interacting");
    try{if(root.hasPointerCapture(event.pointerId))root.releasePointerCapture(event.pointerId)}catch{}
    if(moved){
      if(wasPlaying)play();
      announce(`Position $${Math.round((video.currentTime/video.duration)*100)||0} percent, speed $${video.playbackRate.toFixed(2)} times`);
    }else{
      if(wasPlaying){
        video.pause();
        announce("Paused");
      }else{
        play();
        announce("Playing");
      }
    }
    event.preventDefault();
  };
  root.addEventListener("pointerup",endPointer);
  root.addEventListener("pointercancel",endPointer);
  root.addEventListener("contextmenu",(event)=>event.preventDefault());
  start.addEventListener("click",()=>play());
  window.addEventListener("keydown",(event)=>{
    if(event.code==="Space"){
      event.preventDefault();
      toggle();
    }else if(event.code==="ArrowLeft"||event.code==="ArrowRight"){
      event.preventDefault();
      if(!Number.isFinite(video.duration)||video.duration<=0)return;
      const direction=event.code==="ArrowLeft"?-1:1;
      video.currentTime=clamp(video.currentTime+direction/6,0,Math.max(0,video.duration-.001));
      announce(`Position $${Math.round((video.currentTime/video.duration)*100)||0} percent`);
    }else if(event.key==="0"||event.key.toLowerCase()==="r"){
      video.playbackRate=1;
      video.currentTime=0;
      play();
      announce("Restarted at normal speed");
    }
  });
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){
      resumeAfterVisibility=!video.paused;
      video.pause();
    }else if(resumeAfterVisibility){
      resumeAfterVisibility=false;
      play();
    }
  });
  window.addEventListener("pagehide",()=>URL.revokeObjectURL(objectUrl),{once:true});
  video.addEventListener("canplay",()=>play(),{once:true});
  video.load();
})();
</script>
</body>
</html>
"""
)


FRAGMENT_TEMPLATE = Template(
    r"""<div id="reef-folded-matter-preview" aria-label="$ARIA_LABEL" tabindex="0">
  <video muted loop playsinline preload="auto" poster="$POSTER_URI" aria-label="$ARIA_LABEL"></video>
  <button type="button" class="btn" hidden>Play</button>
  <span class="sr-only" role="status" aria-live="polite"></span>
  <script type="application/octet-stream" data-video>$VIDEO_BASE64</script>
</div>
<style>
#reef-folded-matter-preview{position:relative;inline-size:100%;aspect-ratio:16/9;display:grid;place-items:center;overflow:hidden;background:var(--muted);touch-action:none;user-select:none}
#reef-folded-matter-preview video{display:block;inline-size:100%;block-size:100%;object-fit:cover;background:var(--muted)}
#reef-folded-matter-preview.is-interacting video{filter:saturate(1.08) brightness(1.03)}
#reef-folded-matter-preview .btn{position:absolute;inset:50% auto auto 50%;transform:translate(-50%,-50%)}
</style>
<script>
(()=>{
  "use strict";
  const root=document.getElementById("reef-folded-matter-preview");
  const video=root.querySelector("video");
  const start=root.querySelector("button");
  const status=root.querySelector('[role="status"]');
  const data=root.querySelector("[data-video]");
  const encoded=data.textContent.trim();
  const chunks=[];
  const chunkChars=1048576;
  for(let offset=0;offset<encoded.length;offset+=chunkChars){
    const raw=atob(encoded.slice(offset,Math.min(offset+chunkChars,encoded.length)));
    const bytes=new Uint8Array(raw.length);
    for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
    chunks.push(bytes);
  }
  const objectUrl=URL.createObjectURL(new Blob(chunks,{type:"$VIDEO_MIME"}));
  video.src=objectUrl;
  data.remove();
  let dragging=false,moved=false,wasPlaying=true,downX=0,downY=0;
  const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
  const play=()=>video.play().then(()=>{start.hidden=true}).catch(()=>{start.hidden=false});
  const apply=(event)=>{
    const rect=root.getBoundingClientRect();
    const x=clamp((event.clientX-rect.left)/Math.max(rect.width,1),0,1);
    const y=clamp((event.clientY-rect.top)/Math.max(rect.height,1),0,1);
    if(Number.isFinite(video.duration)&&video.duration>0)video.currentTime=Math.min(video.duration-.001,x*video.duration);
    video.playbackRate=.35+(1-y)*1.65;
  };
  root.addEventListener("pointerdown",(event)=>{
    if(event.button!==0&&event.pointerType==="mouse")return;
    dragging=true;moved=false;wasPlaying=!video.paused;downX=event.clientX;downY=event.clientY;
    root.classList.add("is-interacting");try{root.setPointerCapture(event.pointerId)}catch{}root.focus({preventScroll:true});video.pause();event.preventDefault();
  });
  root.addEventListener("pointermove",(event)=>{
    if(!dragging)return;
    moved=moved||Math.hypot(event.clientX-downX,event.clientY-downY)>5;if(moved)apply(event);event.preventDefault();
  });
  const end=(event)=>{
    if(!dragging)return;
    moved=moved||Math.hypot(event.clientX-downX,event.clientY-downY)>5;if(moved)apply(event);
    dragging=false;root.classList.remove("is-interacting");
    try{if(root.hasPointerCapture(event.pointerId))root.releasePointerCapture(event.pointerId)}catch{}
    if(moved){if(wasPlaying)play();status.textContent=`Position $${Math.round((video.currentTime/video.duration)*100)||0} percent`}
    else if(wasPlaying){video.pause();status.textContent="Paused"}else{play();status.textContent="Playing"}
    event.preventDefault();
  };
  root.addEventListener("pointerup",end);root.addEventListener("pointercancel",end);
  start.addEventListener("click",play);
  root.addEventListener("keydown",(event)=>{
    if(event.code==="Space"){
      event.preventDefault();
      if(video.paused){play();status.textContent="Playing"}else{video.pause();status.textContent="Paused"}
    }else if(event.code==="ArrowLeft"||event.code==="ArrowRight"){
      event.preventDefault();
      if(!Number.isFinite(video.duration)||video.duration<=0)return;
      const direction=event.code==="ArrowLeft"?-1:1;
      video.currentTime=clamp(video.currentTime+direction/6,0,Math.max(0,video.duration-.001));
    }else if(event.key==="0"||event.key.toLowerCase()==="r"){
      event.preventDefault();video.playbackRate=1;video.currentTime=0;play();
    }
  });
  video.addEventListener("canplay",play,{once:true});
  window.addEventListener("pagehide",()=>URL.revokeObjectURL(objectUrl),{once:true});
  video.load();
})();
</script>
"""
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--poster", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Fluoddity")
    parser.add_argument("--description", default="")
    parser.add_argument("--background", default="#151d31")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--fragment", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=NETWORKED_ART_LIMIT_BYTES)
    return parser.parse_args()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def media_type(path: Path, expected_prefix: str) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if not guessed or not guessed.startswith(expected_prefix):
        raise ValueError(f"{path} does not have a recognized {expected_prefix} MIME type")
    return guessed


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    temporary.write_bytes(data)
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    video_path = args.video.resolve(strict=True)
    poster_path = args.poster.resolve(strict=True)
    output_path = args.output.resolve()
    manifest_path = args.manifest.resolve() if args.manifest else None

    resolved_paths = {
        "video": video_path,
        "poster": poster_path,
        "output": output_path,
    }
    if manifest_path is not None:
        resolved_paths["manifest"] = manifest_path
    labels = list(resolved_paths)
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            if resolved_paths[left] == resolved_paths[right]:
                raise ValueError(
                    f"{left} and {right} paths must be distinct: {resolved_paths[left]}"
                )

    video_bytes = video_path.read_bytes()
    poster_bytes = poster_path.read_bytes()
    video_mime = media_type(video_path, "video/")
    poster_mime = media_type(poster_path, "image/")

    metadata: dict[str, Any] = {
        "schema": "fluoddity.networked-html-artifact.v1",
        "title": args.title,
        "description": args.description,
        "self_contained": True,
        "external_requests": 0,
        "interaction": {
            "pointer_x": "scrub time",
            "pointer_y": "set playback speed from 0.35x to 2.0x",
            "tap_or_space": "toggle playback",
            "arrow_keys": "step by one sixth of a second",
            "r_or_0": "restart at 1x",
        },
        "video": {
            "source_name": video_path.name,
            "mime": video_mime,
            "bytes": len(video_bytes),
            "sha256": sha256(video_bytes),
        },
        "poster": {
            "source_name": poster_path.name,
            "mime": poster_mime,
            "bytes": len(poster_bytes),
            "sha256": sha256(poster_bytes),
        },
    }

    video_base64 = base64.b64encode(video_bytes).decode("ascii")
    poster_uri = f"data:{poster_mime};base64,{base64.b64encode(poster_bytes).decode('ascii')}"
    aria_label = html.escape(
        f"{args.title}. Drag horizontally to scrub and vertically to change speed. "
        "Tap or press Space to pause and resume.",
        quote=True,
    )

    if args.fragment:
        document = FRAGMENT_TEMPLATE.substitute(
            ARIA_LABEL=aria_label,
            POSTER_URI=poster_uri,
            VIDEO_BASE64=video_base64,
            VIDEO_MIME=video_mime,
        )
    else:
        metadata_json = json.dumps(metadata, ensure_ascii=True, separators=(",", ":")).replace(
            "</", "<\\/"
        )
        document = STANDALONE_TEMPLATE.substitute(
            TITLE=html.escape(args.title),
            ARIA_LABEL=aria_label,
            BACKGROUND=html.escape(args.background, quote=True),
            POSTER_URI=poster_uri,
            VIDEO_BASE64=video_base64,
            METADATA_JSON=metadata_json,
        )

    output_bytes = document.encode("utf-8")
    if len(output_bytes) > args.max_bytes:
        raise ValueError(
            f"Generated artifact is {len(output_bytes):,} bytes, above the "
            f"{args.max_bytes:,}-byte limit"
        )

    metadata["artifact"] = {
        "path": str(output_path),
        "bytes": len(output_bytes),
        "sha256": sha256(output_bytes),
        "limit_bytes": args.max_bytes,
        "headroom_bytes": args.max_bytes - len(output_bytes),
    }
    atomic_write(output_path, output_bytes)

    if manifest_path is not None:
        manifest_bytes = (
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        atomic_write(manifest_path, manifest_bytes)

    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
