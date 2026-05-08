from __future__ import annotations

from typing import Any


def format_inspection_results(results: list[Any], image_count: int) -> str:
    """JSON 결과 N개 → 통일된 마크다운."""
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
        md += f"파일명: {str(r.get('file_name', '')).strip()}\n\n"

        # ✅ 충족 항목
        md += "✅ 충족 항목\n"
        satisfied = r.get("satisfied") or []
        if satisfied:
            for s in satisfied:
                try:
                    md += f"- **{s['item']}**: {s['detail']}\n"
                except Exception:
                    continue
        else:
            md += "- 해당 없음\n"

        # ⚠️ 확인 필요
        md += "\n⚠️ 확인 필요 항목\n"
        checks = r.get("check_needed") or []
        if checks:
            for c in checks:
                try:
                    md += f"- **{c['item']}**: {c['detail']}\n"
                    sug = str(c.get("suggestion", "")).strip()
                    if sug:
                        md += f"  → {sug}\n"
                except Exception:
                    continue
        else:
            md += "- 해당 없음\n"

        # ❌ 명확한 이슈
        issues = r.get("issues") or []
        if issues:
            md += "\n❌ 명확한 이슈\n"
            for iss in issues:
                try:
                    md += f"- **{iss['item']}**: {iss['detail']}\n"
                    sug = str(iss.get("suggestion", "")).strip()
                    if sug:
                        md += f"  → {sug}\n"
                except Exception:
                    continue

        # 🔒 컴플라이언스
        md += "\n🔒 컴플라이언스 (일반식품)\n"
        comps = r.get("compliance") or []
        if comps:
            for c in comps:
                try:
                    sev = c.get("severity")
                    icon = "❌" if sev == "violation" else "⚠️" if sev == "warning" else "✅"
                    md += f"- {icon} **{c['item']}**: {c['detail']}\n"
                    alt = str(c.get("alternative", "")).strip()
                    if alt:
                        md += f"  → 대체 제안: {alt}\n"
                except Exception:
                    continue
        else:
            md += "- 해당 없음\n"

        # 💡 추가 제안
        sugs = r.get("suggestions") or []
        if sugs:
            md += "\n💡 추가 제안\n"
            for s in sugs:
                try:
                    md += f"- {s['detail']}\n"
                except Exception:
                    continue

        parts.append(md.rstrip())

    return greeting + "\n---\n\n".join(parts)

