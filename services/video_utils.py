from __future__ import annotations

import io
from typing import Any, Final

import av


def extract_frames_and_audio(
    data: bytes,
    mime_type: str,
    interval_sec: int = 5,
    max_height: int = 720,
    max_frames: int = 20,
) -> dict[str, Any]:
    """
    영상 → JPEG 프레임(시간 간격 샘플) + MP3 오디오(가능 시).

    반환: {
        "frames": [(bytes, "image/jpeg"), ...],
        "audio": (bytes, "audio/mp3") | None,
    }
    긴 영상은 interval을 넓혀 최대 max_frames장까지.
    """
    empty: dict[str, Any] = {"frames": [], "audio": None}
    if not data:
        return empty

    try:
        frames: list[tuple[bytes, str]] = []

        # 프레임 추출 (time-based sampling; avoids relying on fps metadata)
        with av.open(io.BytesIO(data)) as container:
            if not container.streams.video:
                return empty
            video = container.streams.video[0]

            next_t = 0.0
            for frame in container.decode(video):
                if frame.pts is None or frame.time_base is None:
                    continue
                t = float(frame.pts * frame.time_base)
                if t + 1e-6 < next_t:
                    continue

                img = frame.to_image()  # PIL.Image (requires Pillow)
                if img.height > max_height:
                    ratio = max_height / float(img.height)
                    w = max(1, int(img.width * ratio))
                    img = img.resize((w, int(max_height)))

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80, optimize=True)
                frames.append((buf.getvalue(), "image/jpeg"))

                if len(frames) >= max_frames:
                    break
                next_t = t + float(interval_sec)

        # 오디오 추출 (optional)
        audio_pair: tuple[bytes, str] | None = None
        try:
            with av.open(io.BytesIO(data)) as container:
                if not container.streams.audio:
                    audio_pair = None
                else:
                    out_buf = io.BytesIO()
                    out = av.open(out_buf, mode="w", format="mp3")
                    out_stream = out.add_stream("mp3", rate=44100)
                    out_stream.bit_rate = 64_000

                    for packet in container.demux(container.streams.audio[0]):
                        for afr in packet.decode():
                            afr.pts = None  # let encoder handle timestamps
                            for p in out_stream.encode(afr):
                                out.mux(p)
                    for p in out_stream.encode():
                        out.mux(p)
                    out.close()

                    audio_bytes = out_buf.getvalue()
                    if audio_bytes and len(audio_bytes) >= 512:
                        audio_pair = (audio_bytes, "audio/mp3")
        except Exception:
            audio_pair = None

        return {"frames": frames, "audio": audio_pair}
    except Exception as e:
        print(f"[extract_frames_and_audio] 실패: {e}", flush=True)
        return empty
