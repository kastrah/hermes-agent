#!/usr/bin/env python3
"""
Modal video intelligence worker for short-form content analysis.

Pipeline:
1. Ingest video (ffprobe, scene cuts, frame motion/light, audio silence/volume, transcript).
2. SAM3 pass (mask-generation when available; fallback proxy when unavailable).
3. Gemma reasoning pass (text report from extracted metrics).
4. TRIBEv2 saliency proxy (model-driven when available; fallback proxy otherwise).
5. Score combiner => hook, pacing, overload, clarity, drop-off risk.

Usage:
  modal serve scripts/modal_video_intel_app.py
  modal deploy scripts/modal_video_intel_app.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import modal


APP_NAME = "hermes-video-intel"
HF_SECRET_NAME = "video-intel-secrets"

DEFAULT_TRIBE_REPO = "facebook/tribev2"
DEFAULT_SAM_REPO = "facebook/sam3"
# User-requested default; may be too large for A10G, fallback handled at runtime.
DEFAULT_GEMMA_MODEL = "google/gemma-4-31B-it"
FALLBACK_GEMMA_MODEL = "Qwen/Qwen2.5-3B-Instruct"


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git")
    .pip_install(
        "numpy==2.2.6",
        "pandas>=2.0.0",
        "opencv-python-headless==4.12.0.88",
        "scenedetect[opencv]==0.6.7.1",
        "torch>=2.3.0",
        "torchvision>=0.18.0",
        "accelerate>=0.34.0",
        "transformers>=4.56.0",
        "huggingface_hub>=0.34.0",
        "requests>=2.32.0",
        "Pillow>=10.0.0",
        "git+https://github.com/facebookresearch/tribev2.git",
    )
)

app = modal.App(APP_NAME)


@dataclass
class ModelState:
    tribe_ready: bool = False
    sam_ready: bool = False
    gemma_ready: bool = False
    asr_ready: bool = False
    tribe_repo: str = DEFAULT_TRIBE_REPO
    sam_repo: str = DEFAULT_SAM_REPO
    gemma_model: str = DEFAULT_GEMMA_MODEL
    notes: list[str] = field(default_factory=list)


def _run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout, p.stderr


def _ffprobe_json(video_path: Path) -> dict[str, Any]:
    code, out, err = _run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
    )
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err.strip()[:500]}")
    return json.loads(out)


def _basic_video_features(video_path: Path) -> dict[str, Any]:
    import cv2
    import numpy as np
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    cap = cv2.VideoCapture(str(video_path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = (frame_count / fps) if fps > 0 else 0.0

    sample_luma: list[float] = []
    sample_motion: list[float] = []
    prev_gray = None
    sampled = 0
    stride = max(1, int(fps // 2) if fps > 0 else 12)
    idx = 0
    while sampled < 120:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % stride != 0:
            idx += 1
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sample_luma.append(float(np.mean(gray)))
        if prev_gray is not None:
            flow = cv2.absdiff(gray, prev_gray)
            sample_motion.append(float(np.mean(flow)))
        prev_gray = gray
        sampled += 1
        idx += 1
    cap.release()

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video)
    scenes = scene_manager.get_scene_list()
    scene_seconds: list[float] = []
    for s, _ in scenes:
        # SceneDetect FrameTimecode API exposes get_seconds()
        scene_seconds.append(float(s.get_seconds()))

    return {
        "duration_sec": round(duration, 3),
        "fps": round(fps, 3),
        "frame_count": frame_count,
        "scene_count": len(scenes),
        "scene_boundaries_sec": [round(x, 3) for x in scene_seconds[:80]],
        "avg_luma": round(float(np.mean(sample_luma)) if sample_luma else 0.0, 4),
        "avg_motion": round(float(np.mean(sample_motion)) if sample_motion else 0.0, 4),
        "motion_p95": round(float(np.percentile(sample_motion, 95)) if sample_motion else 0.0, 4),
        "motion_std": round(float(np.std(sample_motion)) if sample_motion else 0.0, 4),
    }


def _audio_features(video_path: Path) -> dict[str, Any]:
    # Silence profile
    _, _, sil_err = _run_cmd(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-af",
            "silencedetect=noise=-30dB:d=0.35",
            "-f",
            "null",
            "-",
        ]
    )
    silence_events = len(re.findall(r"silence_start:", sil_err))
    silence_total = 0.0
    sil_pairs = re.findall(r"silence_start:\s*([0-9.]+).*?silence_end:\s*([0-9.]+)", sil_err, re.S)
    for start, end in sil_pairs:
        try:
            silence_total += max(0.0, float(end) - float(start))
        except ValueError:
            pass

    # Loudness profile
    _, _, vol_err = _run_cmd(
        ["ffmpeg", "-i", str(video_path), "-af", "volumedetect", "-f", "null", "-"]
    )
    mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", vol_err)
    max_match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", vol_err)

    return {
        "silence_events": silence_events,
        "silence_total_sec": round(silence_total, 3),
        "mean_volume_db": float(mean_match.group(1)) if mean_match else None,
        "max_volume_db": float(max_match.group(1)) if max_match else None,
    }


def _extract_frames(video_path: Path, max_frames: int = 12) -> list[Any]:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return []
    indices = sorted(set(int(i * (total - 1) / max(1, max_frames - 1)) for i in range(max_frames)))
    frames = []
    for i in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = cap.read()
        if not ok:
            continue
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(frame_rgb)
    cap.release()
    return frames


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _score_value(v: Any) -> float:
    try:
        val = float(v)
    except (TypeError, ValueError):
        return 50.0
    return round(max(0.0, min(100.0, val)), 2)


def _normalize_scores(scores: dict[str, Any] | None) -> dict[str, float]:
    scores = scores or {}
    return {
        "hook_strength": _score_value(scores.get("hook_strength")),
        "pacing_quality": _score_value(scores.get("pacing_quality")),
        "visual_overload_risk": _score_value(scores.get("visual_overload_risk")),
        "clarity_score": _score_value(scores.get("clarity_score")),
        "dropoff_risk": _score_value(scores.get("dropoff_risk")),
    }


def _normalize_recommendations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text[:280])
    return out[:8]


def _fallback_orchestrator(
    features: dict[str, Any], audio: dict[str, Any], sam: dict[str, Any], tribe: dict[str, Any]
) -> dict[str, Any]:
    # Emergency fallback used only when Gemma is unavailable or returns invalid JSON.
    duration = float(features.get("duration_sec") or 0.0)
    scene_count = float(features.get("scene_count") or 0.0)
    avg_motion = float(features.get("avg_motion") or 0.0)
    motion_std = float(features.get("motion_std") or 0.0)
    silence_ratio = (float(audio.get("silence_total_sec") or 0.0) / duration) if duration > 0 else 0.0

    hook = _clip01(0.45 * min(scene_count / 8.0, 1.0) + 0.35 * min(avg_motion / 8.0, 1.0) + 0.20 * (1 - silence_ratio))
    pacing = _clip01(0.5 * min(scene_count / max(duration / 4.0, 1.0), 1.0) + 0.3 * min(avg_motion / 7.0, 1.0) + 0.2 * min(motion_std / 4.5, 1.0))
    overload = _clip01(0.55 * min(avg_motion / 14.0, 1.0) + 0.45 * min(scene_count / max(duration / 1.7, 1.0), 1.0))
    clarity = _clip01(0.5 * (1 - silence_ratio) + 0.25 * (1 - overload) + 0.25 * float(sam.get("focus_stability", 0.5)))
    dropoff = _clip01(0.35 * (1 - hook) + 0.30 * (1 - clarity) + 0.20 * overload + 0.15 * (1 - float(tribe.get("saliency_signal", 0.5))))

    return {
        "scores": {
            "hook_strength": round(hook * 100, 2),
            "pacing_quality": round(pacing * 100, 2),
            "visual_overload_risk": round(overload * 100, 2),
            "clarity_score": round(clarity * 100, 2),
            "dropoff_risk": round(dropoff * 100, 2),
        },
        "recommendations": [
            "Improve opening 2 seconds with a sharper hook statement and faster first visual shift.",
            "Reduce low-information pauses and tighten cuts around key spoken moments.",
            "Increase caption legibility and keep CTA on screen longer with cleaner composition.",
        ],
        "verdicts": {
            "hook": "Moderate",
            "pacing": "Moderate",
            "clarity": "Moderate",
            "cta": "Needs stronger explicit action phrase and visual reinforcement.",
        },
        "likely_dropoff_moments": [],
        "confidence": 0.45,
    }


@app.cls(
    image=image,
    timeout=60 * 30,
    gpu="A10G",
    scaledown_window=600,
    secrets=[modal.Secret.from_name(HF_SECRET_NAME, required_keys=["HUGGINGFACE_HUB_TOKEN"])],
)
class VideoIntelWorker:
    @modal.enter()
    def startup(self):
        import torch
        from huggingface_hub import login
        from transformers import pipeline

        self.state = ModelState()
        token = os.getenv("HUGGINGFACE_HUB_TOKEN")
        if token:
            os.environ["HF_TOKEN"] = token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = token
            login(token=token, add_to_git_credential=False)

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device_id = 0 if self.device == "cuda" else -1

        # ASR (for transcript)
        self.asr_pipe = None
        try:
            self.asr_pipe = pipeline(
                "automatic-speech-recognition",
                model="openai/whisper-tiny",
                device=self.device_id,
            )
            self.state.asr_ready = True
        except Exception as exc:
            self.state.notes.append(f"ASR init failed: {exc}")

        # SAM3 mask-generation pipeline (transformers task compatibility varies by release).
        self.sam_pipe = None
        try:
            self.sam_pipe = pipeline(
                "mask-generation",
                model=DEFAULT_SAM_REPO,
                trust_remote_code=True,
                device=self.device_id,
            )
            self.state.sam_ready = True
        except Exception as exc:
            self.state.notes.append(f"SAM3 init failed (fallback proxy active): {exc}")

        # TRIBEv2 native loader (official package installed from GitHub).
        self.tribe_model = None
        try:
            from tribev2 import TribeModel

            self.tribe_model = TribeModel.from_pretrained(
                DEFAULT_TRIBE_REPO,
                device="cuda" if self.device == "cuda" else "cpu",
            )
            self.state.tribe_ready = True
        except Exception as exc:
            self.state.notes.append(f"TRIBEv2 init failed (fallback proxy active): {exc}")

        # Gemma reasoning (31B requested; fallback to 4B when capacity is insufficient).
        requested = os.getenv("GEMMA_MODEL_ID", DEFAULT_GEMMA_MODEL).strip() or DEFAULT_GEMMA_MODEL
        self.gemma_pipe = None
        for model_id in (requested, FALLBACK_GEMMA_MODEL):
            try:
                self.gemma_pipe = pipeline(
                    "text-generation",
                    model=model_id,
                    device_map="auto",
                    torch_dtype="auto",
                    trust_remote_code=True,
                )
                self.state.gemma_model = model_id
                self.state.gemma_ready = True
                if model_id != requested:
                    self.state.notes.append(
                        f"Requested {requested} could not be loaded; using fallback {model_id}."
                    )
                break
            except Exception as exc:
                self.state.notes.append(f"Gemma init failed for {model_id}: {exc}")

    def _transcript(self, video_path: Path) -> str:
        if not self.asr_pipe:
            return ""
        try:
            out = self.asr_pipe(str(video_path), generate_kwargs={"task": "transcribe"})
            text = (out.get("text") or "").strip() if isinstance(out, dict) else ""
            return text[:7000]
        except Exception as exc:
            self.state.notes.append(f"ASR failed: {exc}")
            return ""

    def _sam_metrics(self, frames: list[Any]) -> dict[str, Any]:
        import numpy as np

        if not frames:
            return {"mask_density": 0.0, "focus_stability": 0.5, "method": "none"}

        # Preferred: SAM3 mask-generation.
        if self.sam_pipe:
            try:
                mask_densities: list[float] = []
                for f in frames[:8]:
                    out = self.sam_pipe(f)
                    # Pipeline output schema differs across versions; handle broadly.
                    if isinstance(out, list):
                        areas = []
                        for item in out:
                            if isinstance(item, dict) and "mask" in item:
                                m = item["mask"]
                                arr = np.array(m, dtype=np.float32)
                                if arr.size > 0:
                                    areas.append(float(arr.mean()))
                        if areas:
                            mask_densities.append(float(np.clip(np.sum(areas), 0.0, 1.0)))
                if mask_densities:
                    return {
                        "mask_density": round(float(np.mean(mask_densities)), 4),
                        "focus_stability": round(float(1.0 - np.std(mask_densities)), 4),
                        "method": "sam3",
                    }
            except Exception as exc:
                self.state.notes.append(f"SAM3 inference failed; fallback proxy used: {exc}")

        # Fallback proxy: gradient saliency density.
        dens = []
        for f in frames[:8]:
            gx = np.gradient(f.astype(np.float32), axis=1)
            gy = np.gradient(f.astype(np.float32), axis=0)
            mag = np.sqrt(np.mean(gx[0] ** 2 + gy[0] ** 2, axis=2))
            th = np.percentile(mag, 80)
            dens.append(float((mag > th).mean()))
        return {
            "mask_density": round(float(np.mean(dens)), 4),
            "focus_stability": round(float(1.0 - np.std(dens)), 4),
            "method": "proxy-gradient",
        }

    def _tribe_saliency(self, video_path: Path, frames: list[Any]) -> dict[str, Any]:
        import numpy as np

        if not frames:
            return {"saliency_signal": 0.5, "method": "none"}

        if self.tribe_model:
            try:
                events = self.tribe_model.get_events_dataframe(video_path=str(video_path))
                try:
                    pred_out = self.tribe_model.predict(events=events, verbose=False)
                except TypeError:
                    pred_out = self.tribe_model.predict(events)

                pred_array = pred_out[0] if isinstance(pred_out, tuple) else pred_out
                if hasattr(pred_array, "detach"):
                    pred_array = pred_array.detach().cpu().numpy()
                pred_array = np.asarray(pred_array)
                if pred_array.ndim == 1:
                    pred_array = pred_array.reshape(1, -1)
                if pred_array.size > 0:
                    temporal_delta = (
                        float(np.mean(np.abs(np.diff(pred_array, axis=0))))
                        if pred_array.shape[0] > 1
                        else float(np.mean(np.abs(pred_array)))
                    )
                    signal = 1.0 - float(np.exp(-min(temporal_delta, 10.0)))
                    return {"saliency_signal": round(signal, 4), "method": "tribev2-native"}
            except Exception as exc:
                self.state.notes.append(f"TRIBE inference failed; fallback proxy used: {exc}")

        # Fallback proxy from frame variance.
        vars_ = [float(np.var(f.astype(np.float32))) for f in frames[:8]]
        if not vars_:
            return {"saliency_signal": 0.5, "method": "proxy-variance"}
        v = float(np.mean(vars_))
        signal = 1.0 - float(np.exp(-v / 6000.0))
        return {"saliency_signal": round(max(0.0, min(signal, 1.0)), 4), "method": "proxy-variance"}

    def _gemma_orchestrate(
        self,
        *,
        platform: str,
        features: dict[str, Any],
        audio: dict[str, Any],
        sam: dict[str, Any],
        tribe: dict[str, Any],
        transcript: str,
    ) -> dict[str, Any]:
        if not self.gemma_pipe:
            self.state.notes.append("Gemma orchestrator unavailable; using fallback scorer.")
            return _fallback_orchestrator(features, audio, sam, tribe)

        schema = {
            "scores": {
                "hook_strength": "0-100",
                "pacing_quality": "0-100",
                "visual_overload_risk": "0-100",
                "clarity_score": "0-100",
                "dropoff_risk": "0-100",
            },
            "recommendations": ["max 8 concise edits"],
            "verdicts": {
                "hook": "short verdict",
                "pacing": "short verdict",
                "clarity": "short verdict",
                "cta": "short verdict",
            },
            "likely_dropoff_moments": [
                {"timestamp_sec": "number", "reason": "short reason"}
            ],
            "confidence": "0-1",
        }

        prompt = (
            "You are the orchestration layer for short-form video analysis.\n"
            "Treat SAM3 and TRIBEv2 outputs as tool signals, then synthesize a final assessment.\n"
            "Return STRICT JSON only. Do not include markdown or prose outside JSON.\n"
            f"JSON schema: {json.dumps(schema)}\n\n"
            f"Platform: {platform}\n"
            f"Features: {json.dumps(features)}\n"
            f"Audio: {json.dumps(audio)}\n"
            f"SAM: {json.dumps(sam)}\n"
            f"TRIBE: {json.dumps(tribe)}\n"
            f"Transcript (truncated): {transcript[:2000]}\n"
        )
        try:
            out = self.gemma_pipe(prompt, max_new_tokens=420, do_sample=False, temperature=0.1)
            if isinstance(out, list) and out:
                text = out[0].get("generated_text", "")
                candidate = text[-5000:].strip()
                start = candidate.find("{")
                end = candidate.rfind("}")
                if start >= 0 and end > start:
                    candidate = candidate[start : end + 1]
                parsed = json.loads(candidate)
                scores = _normalize_scores(parsed.get("scores"))
                recommendations = _normalize_recommendations(parsed.get("recommendations"))
                verdicts = parsed.get("verdicts") if isinstance(parsed.get("verdicts"), dict) else {}
                dropoff = parsed.get("likely_dropoff_moments")
                if not isinstance(dropoff, list):
                    dropoff = []
                confidence = parsed.get("confidence", 0.6)
                try:
                    confidence = max(0.0, min(1.0, float(confidence)))
                except (TypeError, ValueError):
                    confidence = 0.6
                return {
                    "scores": scores,
                    "recommendations": recommendations[:8]
                    if recommendations
                    else ["No strong issues detected; run A/B tests on hook and CTA phrasing."],
                    "verdicts": {
                        "hook": str(verdicts.get("hook", "")).strip()[:180],
                        "pacing": str(verdicts.get("pacing", "")).strip()[:180],
                        "clarity": str(verdicts.get("clarity", "")).strip()[:180],
                        "cta": str(verdicts.get("cta", "")).strip()[:180],
                    },
                    "likely_dropoff_moments": dropoff[:10],
                    "confidence": round(confidence, 4),
                }
            self.state.notes.append("Gemma returned empty output; using fallback scorer.")
            return _fallback_orchestrator(features, audio, sam, tribe)
        except Exception as exc:
            self.state.notes.append(f"Gemma orchestration failed; using fallback scorer: {exc}")
            return _fallback_orchestrator(features, audio, sam, tribe)

    @modal.method()
    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "app": APP_NAME,
            "models": {
                "tribe_repo": self.state.tribe_repo,
                "sam_repo": self.state.sam_repo,
                "gemma_model": self.state.gemma_model,
                "tribe_ready": self.state.tribe_ready,
                "sam_ready": self.state.sam_ready,
                "gemma_ready": self.state.gemma_ready,
                "asr_ready": self.state.asr_ready,
            },
            "notes": self.state.notes,
        }

    @modal.method()
    def analyze_video_bytes(self, video_bytes: bytes, platform: str = "tiktok_instagram") -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="video-intel-") as td:
            video_path = Path(td) / "input.mp4"
            video_path.write_bytes(video_bytes)

            media_meta = _ffprobe_json(video_path)
            features = _basic_video_features(video_path)
            audio = _audio_features(video_path)
            frames = _extract_frames(video_path, max_frames=12)
            transcript = self._transcript(video_path)
            sam = self._sam_metrics(frames)
            tribe = self._tribe_saliency(video_path, frames)
            orchestration = self._gemma_orchestrate(
                platform=platform,
                features=features,
                audio=audio,
                sam=sam,
                tribe=tribe,
                transcript=transcript,
            )
            scores = _normalize_scores(orchestration.get("scores"))
            recommendations = _normalize_recommendations(orchestration.get("recommendations"))

            return {
                "platform": platform,
                "ingest": {
                    "ffprobe": media_meta,
                    "features": features,
                    "audio": audio,
                    "transcript_preview": transcript[:1200],
                },
                "sam3": sam,
                "tribev2": tribe,
                "scores": scores,
                "recommendations": recommendations,
                "verdicts": orchestration.get("verdicts", {}),
                "likely_dropoff_moments": orchestration.get("likely_dropoff_moments", []),
                "analysis_confidence": orchestration.get("confidence", 0.6),
                "model_flags": {
                    "tribe_ready": self.state.tribe_ready,
                    "sam_ready": self.state.sam_ready,
                    "gemma_ready": self.state.gemma_ready,
                    "asr_ready": self.state.asr_ready,
                    "gemma_model": self.state.gemma_model,
                },
                "notes": self.state.notes,
            }

    @modal.method()
    def analyze_video_url(self, video_url: str, platform: str = "tiktok_instagram") -> dict[str, Any]:
        import requests

        resp = requests.get(video_url, timeout=120)
        resp.raise_for_status()
        return self.analyze_video_bytes.local(resp.content, platform=platform)


@app.function(image=image)
def ping() -> str:
    return json.dumps({"ok": True, "app": APP_NAME})
