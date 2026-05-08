from __future__ import annotations

import re
from typing import Any

_LEADING_BULLET_RE = re.compile(r"^\s*[-*•]+\s*")
_MAX_PROPOSALS = 2


def _strip(v: Any) -> str:
    return str(v or "").strip()


def _strip_bullet(text: Any) -> str:
    """모델이 넣은 선행 '- ', '* ', '• ' 등을 제거."""
    s = _strip(text)
    while True:
        new_s = _LEADING_BULLET_RE.sub("", s, count=1)
        if new_s == s:
            return s
        s = new_s


def _short(text: Any, limit: int = 120) -> str:
    """긴 detail/suggestion을 한 줄 길이로 클램프."""
    s = " ".join(_strip_bullet(text).split())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def format_inspection_results(results: list[Any], image_count: int) -> str:
    """JSON 결과 N개 → 3섹션(✅ 충족 / ❌ 미충족 / 💡 제안) 마크다운.
    💡 제안은 우선순위(issues > check_needed > suggestions > 컴플)로 정렬한 뒤 최대 2개."""
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
                miss_kw.append(f'"{item}"' if not item.startswith('"') else item)
        if miss_kw:
            md += "\n❌ 미충족\n" + " / ".join(miss_kw) + "\n"

        # 💡 제안 — 우선순위별로 모은 뒤 최대 2개
        compliance_props: list[str] = []
        for c in r.get("compliance") or []:
            if not isinstance(c, dict):
                continue
            if c.get("severity") not in ("violation", "warning"):
                continue
            item = _strip(c.get("item"))
            alt = _short(c.get("alternative"))
            if not alt:
                continue
            compliance_props.append(f'- "{item}" → {alt}' if item else f"- {alt}")

        issue_props: list[str] = []
        for iss in r.get("issues") or []:
            if not isinstance(iss, dict):
                continue
            item = _strip(iss.get("item"))
            sug = _short(iss.get("suggestion"))
            if not sug:
                continue
            issue_props.append(f"- {item}: {sug}" if item else f"- {sug}")

        check_props: list[str] = []
        for c in r.get("check_needed") or []:
            if not isinstance(c, dict):
                continue
            item = _strip(c.get("item"))
            sug = _short(c.get("suggestion"))
            if not sug:
                continue
            line = f"- {item}: {sug}" if item else f"- {sug}"
            line += " (테스트 의도면 패스)"
            check_props.append(line)

        free_props: list[str] = []
        for s in r.get("suggestions") or []:
            if not isinstance(s, dict):
                continue
            detail = _short(s.get("detail"))
            if detail:
                free_props.append(f"- {detail}")

        proposals = (issue_props + check_props + free_props + compliance_props)[:_MAX_PROPOSALS]
        if proposals:
            md += "\n💡 제안\n" + "\n".join(proposals) + "\n"

        parts.append(md.rstrip())

    return greeting + "\n---\n\n".join(parts)
