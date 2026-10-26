# COBOL 구조 기반 청킹 기준선

## 설정

- 데이터: `data/samples/*.cbl` 합성 COBOL 5개
- 평가셋: `data/evaluation/questions-v1.jsonl`의 answerable 질문 24개
- 임베딩: Chroma 기본 ONNX `all-MiniLM-L6-v2`, 384차원
- 거리: cosine
- 구조 경계: `DIVISION`, `SECTION`, `PROCEDURE DIVISION` 내부 paragraph
- 비교 단위: 최고 점수 청크를 기준으로 중복 제거한 `source_path` 순위

## 결과

| 청킹 | 청크 수 | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---:|---:|---:|---:|---:|
| 파일 단위 | 5 | 0.2500 | 0.6667 | 1.0000 | 0.4979 |
| 구조 기반 | 52 | 0.2917 | 0.7083 | 1.0000 | 0.5299 |
| 변화량 | +47 | +0.0417 | +0.0417 | 0.0000 | +0.0319 |

문서가 5개뿐이므로 Hit@5는 분별력이 없다. 구조 기반 청킹은 Hit@1·Hit@3·MRR을 개선했지만 로드맵의 잠정 MRR 기준 0.60에는 도달하지 못했다.

## 질문별 변화

- 개선: `q001`, `q002`, `q003`, `q005`, `q006`, `q021`
- 회귀: `q011`, `q012`, `q015`, `q017`
- 동일: 나머지 14개

개선 사례는 파일 전체보다 관련 paragraph·section이 직접 검색된 효과가 있다. 회귀 사례는 한국어 질문과 영어 COBOL 식별자 사이의 임베딩 정렬 한계가 크며, 짧고 일반적인 구조 청크가 구체적인 거래·집계 paragraph보다 먼저 검색되는 현상도 확인됐다.

헤더 전용 청크를 다음 section·paragraph와 병합하는 39청크 변형도 측정했지만 MRR이 0.5208로 하락해 채택하지 않았다.

## 필터와 재현성

`language=cobol` 메타데이터 필터는 무필터 결과와 Hit@1·3·5·MRR이 모두 동일했다. 현재 코퍼스가 전부 COBOL이므로 품질 개선 효과는 없지만 혼합 언어 코퍼스에서 검색 범위를 제한하는 계약으로 유지한다.

동일 설정으로 두 번 실행한 결과 JSON SHA-256은 다음과 같이 일치했다.

```text
7e7da1cfcadb1b0ef5a24a6f290ce5c5bea8f1351ce4ae4a11e95d51e19e44a0
```

결과 파일은 `data/evaluation/results/structured-baseline-v1.json`이다.

## 재실행

```powershell
.\.venv\Scripts\python.exe -m legacy_rag.evaluation.run_structured_baseline
```

다음 품질 실험은 청크 규칙을 더 복잡하게 만들기보다 동일 구조 청크에서 다국어 임베딩 또는 식별자·경로 문맥을 포함한 임베딩 입력을 비교하는 것이다.
