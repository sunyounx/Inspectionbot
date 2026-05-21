#!/usr/bin/env python3
"""Run: .venv/bin/python scripts/test_notion_sample.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

SAMPLE = """2026-05-20 | (풀퍼널 마케팅 전략 및 소재 기획 효율화)

피드백 요약
현재 소재 라이브 리드타임 지연 및 피드백 반영의 한계가 있으며, 이는 에코의 TEST 및 방향성 공유 부족, 그리고 완성된 시안에 대한 단편적인 피드백 구조에서 비롯됩니다. 풀퍼널 마케팅으로의 성장을 위해, DA 소재 기획의 자유도를 높이고 효율적인 업무를 위해 사전 기획 단계에서의 논의(기획안 공유)와 사후 리뷰가 필요하다는 점을 강조합니다. 특히 키 비주얼과 키 카피 등 브랜드 코어 애셋에 대한 명확한 전략적 정의와 TEST를 통해 브랜드 인지와 설득력을 높이는 방향성을 설정하고, 에코 측이 이 고정 값 하에서 유연하게 기획-실행할 수 있도록 퍼널을 분리 운영할 필요가 있다는 점이 핵심입니다.

적용 범위 (영상/이미지DA/카피 등 맥락)
주로 이미지DA, 키 비주얼, 키 카피 등 크리에이티브 소재 기획에 중점을 두지만, CRM/프로모션 전략 및 인플루언서 PPL 콘텐츠 등 풀퍼널 마케팅 전반을 아우르는 전체 범위에 해당합니다.

방향성 vs 규칙 (가이드라인이 '방향성'인지 '강한 규칙'인지 판단 한 줄 + 근거)
기존의 미시적인 피드백에서 벗어나 브랜드 코어 애셋에 대한 명확한 규칙을 설정하되, 그 안에서 기획-실행의 자유도를 높여주는 방향성에 가깝습니다. 근거는 "DA 퍼널에서의 자유도를 높혀가기 위해서는...", "방향 설정에 있어서 고려하실 전략적 요소 정도의 피드백만 남기고...", "고정 값(시각화 및 카피 스타일) 하에서 자유도를 가지고 전환을 만들어낼지" 등의 문구에서 알 수 있습니다.

원문 발췌 요약 (핵심 인용이 아니라 요약해도 됨)
소재 라이브 리드타임 지연 및 반영 한계, 그리고 에코의 AB테스트와 방향성 공유 부족으로 비효율이 발생함. 풀퍼널 마케팅으로의 전환을 위해 DA 퍼널에서의 자유도를 높여야 하며, 이를 위해 [BX 전략: 키비쥬얼/브랜드 커뮤니케이션]에 대한 에코의 문제 정의와 기획-실행 퍼널 분리가 필요함. 특히 키 비쥬얼 컨셉 TEST를 통한 브랜디 인지 및 설득 방안 논의가 시급하며, '스킨 롱제비티'를 올더뮤만의 '머무름', '오후 2시', '더 많이가 아니라 더 오래'와 같은 기억 장치로 바꾸는 방향성을 설정하고, 캠페인 후 소비자가 기억해야 할 단어, 장면, 행동을 고정해야 함.
📎 올더뮤 Brand OS v3.0
📎 올더뮤 Visual OS 3.0 Sprint
📎 https://www.notion.so/Brand-OS-v3-0-365b901b86d780409783d813f274f06b?source=copy_link
📎 https://www.notion.so/Visual-OS-3-0-Sprint-365b901b86d780ca9dc7ccb3fda25686?source=copy_link
"""


def main() -> None:
    from services.notion_service import extract_page_id, read_notion_page
    from services.slack_service import extract_notion_links

    print("=== 1. 링크 추출 ===")
    links = extract_notion_links(SAMPLE)
    print(f"count: {len(links)}")
    for i, link in enumerate(links, 1):
        print(f"  [{i}] {link['url']}")

    print("\n=== 2. page id ===")
    for link in links:
        pid = extract_page_id(link["url"])
        print(f"  {pid} <- {link['url'][:70]}")

    from services.notion_playwright import start_playwright_pool, stop_playwright_pool

    start_playwright_pool()
    print("\n=== 3. Notion 읽기 (API → Playwright 자동) ===")
    for link in links:
        url = link["url"]
        print(f"\n--- {url} ---")
        try:
            text = read_notion_page(url)
            if text is None:
                print("  result: empty page (soft-fail)")
            else:
                preview = text[:500].replace("\n", " ")
                print(f"  chars: {len(text)}")
                print(f"  preview: {preview}...")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")

    stop_playwright_pool()


if __name__ == "__main__":
    main()
