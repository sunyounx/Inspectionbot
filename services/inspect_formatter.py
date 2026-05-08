from __future__ import annotations

from typing import Any


def _strip(v: Any) -> str:
    return str(v or "").strip()


def _short(text: str, limit: int = 100) -> str:
    """긴 detail/suggestion을 한 줄 길이로 클램프."""
    s = " ".join(_strip(text).split())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def format_inspection_results(results: list[Any], image_count: int) -> str:
    """JSON 결과 N개 → 3섹션(✅ 충족 / ❌ 미충족 / 💡 제안) 마크다운."""
    greeting = (
        "안녕하세요! 올더뮤 광고 소재 1차 검수 어시스턴트입니다.\n"
        f"요청하신 {image_count}건의 소재에 대한 검수 결과를 전달합니다.\n\n---\n\n"
    )

    parts: list[str] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            parts.append(f"### 이미지 {i + 1}\n⚠️ 검수 실패: {r}")
            continue

        if not isinstance(r, dict):
            parts.append(f"### 이미지 {i + 1}\n⚠️ 검수 실패: invalid result type={type(r)}")
            continue

        md = f"### 이미지 {i + 1}\n"
        fname = _strip(r.get("file_name"))
        if fname:
            md += f"파일명: {fname}\n"

        # ✅ 충족 — 키워드만 한 줄
        sat_kw: list[str] = []
        for s in r.get("satisfied") or []:
            if not isinstance(s, dict):
                continue
            item = _strip(s.get("item"))
            if item:
                sat_kw.append(item)
        if sat_kw:
            md += "\n✅ 충족\n" + " / ".join(sat_kw) + "\n"

        # ❌ 미충족 — check_needed + issues + compliance(violation/warning) 키워드
        miss_kw: list[str] = []
        for c in r.get("check_needed") or []:
            if isinstance(c, dict):
                item = _strip(c.get("item"))
                if item:
                    miss_kw.append(item)
        for iss in r.get("issues") or []:
            if isinstance(iss, dict):
                item = _strip(iss.get("item"))
                if item:
                    miss_kw.append(item)
        for c in r.get("compliance") or []:
            if not isinstance(c, dict):
                continue
            if c.get("severity") not in ("violation", "warning"):
                continue
            item = _strip(c.get("item"))
            if item:
                # 컴플 항목은 인용 형태로 표기해 시각적으로 구분
                miss_kw.append(f'"{item}"' if not item.startswith('"') else item)
        if miss_kw:
            md += "\n❌ 미충족\n" + " / ".join(miss_kw) + "\n"

        # 💡 제안 — 항목별 한 줄 (현재→제안 화살표는 모델이 suggestion에 담아준다)
        proposals: list[str] = []
        for c in r.get("check_needed") or []:
            if not isinstance(c, dict):
                continue
            item = _strip(c.get("item"))
            sug = _short(c.get("suggestion"))
            if not (item or sug):
                continue
            line = f"- {item}: {sug}" if (item and sug) else f"- {item or sug}"
            line += " (테스트 의도면 패스)"
            proposals.append(line)
        for iss in r.get("issues") or []:
            if not isinstance(iss, dict):
                continue
            item = _strip(iss.get("item"))
            sug = _short(iss.get("suggestion"))
            if not (item or sug):
                continue
            proposals.append(f"- {item}: {sug}" if (item and sug) else f"- {item or sug}")
        for c in r.get("compliance") or []:
            if not isinstance(c, dict):
                continue
            if c.get("severity") not in ("violation", "warning"):
                continue
            item = _strip(c.get("item"))
            alt = _short(c.get("alternative"))
            if not (item or alt):
                continue
            if item and alt:
                proposals.append(f'- "{item}" → {alt}')
            else:
                proposals.append(f"- {item or alt}")
        for s in r.get("suggestions") or []:
            if not isinstance(s, dict):
                continue
            detail = _short(s.get("detail"))
            if detail:
                proposals.append(f"- {detail}")
        if proposals:
            md += "\n💡 제안\n" + "\n".join(proposals) + "\n"

        parts.append(md.rstrip())

    return greeting + "\n---\n\n".join(parts)
