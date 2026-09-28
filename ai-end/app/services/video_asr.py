"""本地 ASR（可选 faster-whisper）→ 带时间轴的字幕段。"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# faster-whisper 可直接解码的容器；HLS(.m3u8)/裸 .ts 先经 ffmpeg 抽音频
_DIRECT_DECODE_SUFFIXES = {
    ".mp4", ".m4a", ".wav", ".mp3", ".aac", ".flac", ".mkv", ".webm", ".mov",
}

# 字幕切句：句末/停顿/长度阈值，避免一条字幕横跨 30 秒导致与画面错位
_CUE_HARD_PUNCT = set("。！？!?")
_CUE_SOFT_PUNCT = set("，,、；;：:")
_CUE_MAX_CHARS = 18
_CUE_MAX_GAP_S = 0.6


def _words_to_cues(seg: Any) -> List[Dict[str, Any]]:
    """把 whisper 的 segment 按词级时间戳切成「一行一条」的字幕。"""
    words = getattr(seg, "words", None)
    if not words:
        text = (seg.text or "").strip()
        if not text:
            return []
        return [{
            "text": text,
            "start_s": round(float(seg.start), 3),
            "end_s": round(float(seg.end), 3),
        }]

    cues: List[Dict[str, Any]] = []
    buf: List[Any] = []

    def flush() -> None:
        if not buf:
            return
        text = "".join((w.word or "") for w in buf).strip()
        if text:
            cues.append({
                "text": text,
                "start_s": round(float(buf[0].start), 3),
                "end_s": round(float(buf[-1].end), 3),
            })
        buf.clear()

    for i, w in enumerate(words):
        buf.append(w)
        token = w.word or ""
        last = token[-1:] if token else ""
        nchars = sum(len(x.word or "") for x in buf)
        gap = 0.0
        if i + 1 < len(words):
            gap = float(words[i + 1].start) - float(w.end)
        if (
            last in _CUE_HARD_PUNCT
            or last in _CUE_SOFT_PUNCT
            or nchars >= _CUE_MAX_CHARS
            or gap >= _CUE_MAX_GAP_S
        ):
            flush()
    flush()
    return cues


def merge_segments_for_index(
    segments: List[Dict[str, Any]],
    *,
    max_gap_s: float = 1.0,
    max_chars: int = 280,
) -> List[Dict[str, Any]]:
    """合并相邻短句，控制向量块数量，保留真实起止时间。"""
    if not segments:
        return []

    merged: List[Dict[str, Any]] = []
    buf_text: List[str] = []
    buf_start: Optional[float] = None
    buf_end: Optional[float] = None

    def flush() -> None:
        nonlocal buf_text, buf_start, buf_end
        if not buf_text or buf_start is None:
            buf_text, buf_start, buf_end = [], None, None
            return
        text = " ".join(buf_text).strip()
        if text:
            merged.append({"text": text, "start_s": buf_start, "end_s": buf_end})
        buf_text, buf_start, buf_end = [], None, None

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        try:
            start_s = float(seg["start_s"])
            end_s = float(seg.get("end_s") or start_s)
        except (TypeError, ValueError):
            continue

        if buf_start is None:
            buf_start, buf_end = start_s, end_s
            buf_text = [text]
            continue

        gap = start_s - (buf_end or start_s)
        candidate = " ".join(buf_text + [text])
        if gap > max_gap_s or len(candidate) > max_chars:
            flush()
            buf_start, buf_end = start_s, end_s
            buf_text = [text]
        else:
            buf_text.append(text)
            buf_end = max(end_s, buf_end or end_s)

    flush()
    return merged


def extract_audio_wav(media_path: Path) -> Optional[Path]:
    """
    用 ffmpeg 把任意容器（含 HLS .m3u8 / 裸 .ts）抽成 16k 单声道 wav。

    返回临时 wav 路径；失败返回 None。调用方负责清理其父目录。
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.error("未找到 ffmpeg，无法抽取音频（镜像需安装 ffmpeg）")
        return None

    tmp_dir = Path(tempfile.mkdtemp(prefix="asr_"))
    wav = tmp_dir / "audio.wav"
    cmd = [
        ffmpeg, "-y", "-nostdin", "-loglevel", "error",
        "-i", str(media_path),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(wav),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=1800)
    except Exception as e:
        logger.error("ffmpeg 抽取音频异常 file=%s: %s", media_path, e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    if proc.returncode != 0 or not wav.is_file() or wav.stat().st_size == 0:
        logger.error(
            "ffmpeg 抽取音频失败 file=%s rc=%s err=%s",
            media_path, proc.returncode, (proc.stderr or b"")[:500],
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None
    return wav


def transcribe_media_file(media_path: Path) -> List[Dict[str, Any]]:
    """
    使用 faster-whisper 转写；未安装或失败时返回空列表。
    """
    if not media_path or not media_path.is_file():
        return []

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster-whisper 未安装，跳过 ASR（pip install faster-whisper）")
        return []

    model_name = (settings.video_asr_model or "tiny").strip()
    device = (settings.video_asr_device or "cpu").strip()
    compute_type = (settings.video_asr_compute_type or "int8").strip()

    decode_path: Path = media_path
    tmp_dir: Optional[Path] = None
    if media_path.suffix.lower() not in _DIRECT_DECODE_SUFFIXES:
        extracted = extract_audio_wav(media_path)
        if extracted is None:
            return []
        decode_path = extracted
        tmp_dir = extracted.parent

    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        transcribe_kw = dict(
            language=settings.video_asr_language or "zh",
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        segments, info = model.transcribe(
            str(decode_path), vad_filter=True, **transcribe_kw
        )
        out: List[Dict[str, Any]] = []
        for s in segments:
            out.extend(_words_to_cues(s))
        if not out:
            logger.info("VAD 滤空，改为无 VAD 重跑 file=%s", media_path.name)
            segments, info = model.transcribe(
                str(decode_path), vad_filter=False, **transcribe_kw
            )
            for s in segments:
                out.extend(_words_to_cues(s))
        logger.info(
            "ASR 完成 file=%s model=%s segments=%d lang=%s",
            media_path.name, model_name, len(out), getattr(info, "language", ""),
        )
        return out
    except Exception as e:
        logger.error("ASR 转写失败 file=%s: %s", media_path, e)
        return []
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
