"""Display recorded public evaluation responses offline; never call a model or API."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", choices=("q001", "q014", "q025", "q002"),
        help="Show one recorded case; default: three representative cases",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report_path = root / "data/evaluation/results/generation-evaluation-v2.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in report["cases"]}
    selected = [args.case] if args.case else ["q001", "q014", "q025"]
    print("[저장된 실제 평가 응답 · 2026-10-27 · 실시간 생성 아님]")
    print("API 호출 0회 | 의미 채점: Codex 1차 검토, 독립 사람 검수 전")
    print(f"원본: {report_path.relative_to(root).as_posix()}")
    for case_id in selected:
        case = cases[case_id]
        response = case["response"]
        print(f"\n--- {case_id} ---")
        print(f"질문: {case['question']}")
        print(f"상태: {response['status']} | 이유: {response['reason'] or '없음'}")
        print(f"답변: {response['answer'] or '(답변 없음)'}")
        for source in response["sources"]:
            print(f"출처: {source['source_path']} | 심볼: {source['symbol']}")
            print(f"청크 ID: {source['chunk_id']}")
        print(f"검토 메모: {case['review']['notes']}")


if __name__ == "__main__":
    main()
