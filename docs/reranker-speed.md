# 재순위화 CPU 지연 개선 — 2026-10-28

후속(10/29): 정확도 우선 요청에 따라 기본 API 연결을 진행했다. 아래 보류 판단은 당시
실험 기록이며 현재 설정·실제 HTTP 검증은 [BGE API 안내](reranker-api.md)를 따른다.

기존 BGE 모델을 유지하고 Linear 계층의 동적INT8 변환과 입력 길이별 배치를 적용했다.
공개30문항 전체에서 **근거 확보22/24를 유지**했고 기존FP32 성공 문항의 회귀는 없었다.
재순위화만의 p50은 **28.272초 → 12.644초**, p95는 **41.428초 → 16.457초**였다.
여전히 요청당 수십 초가 추가될 수 있어 **기본 API 적용은 보류**한다.

## 바꾼 것과 고정한 것

- 같은 `BAAI/bge-reranker-v2-m3` revision과 후보30개를 사용했다. 새 모델·다운로드·유료 호출 없음.
- Linear146개를 `torch.ao.quantization.quantize_dynamic`으로 INT8 변환했다. 모델 전체가 INT8이라는 뜻은 아니다.
- batch4 안의 길이 차이를 줄이도록 후보를 토큰 길이순으로 계산하고, 점수는 원래 후보 인덱스로 되돌렸다. 동점일 때 기존 후보 순서를 유지한다.
- 최종 문맥10청크·원문4,000자, CPU4threads, 입력512토큰을 유지했다. 전체900pair에서 절단0건이었다.
- 정답 주석은 재순위화 입력에서 제외했고, 추론 이후의 근거 채점에만 사용했다.

패딩을 포함한 입력 토큰 수를 같은 tokenizer로 다시 계산해 실제 실행 기록과 대조했다.
기존 검색순서의 배치에서는149,486개, 길이순 배치에서는106,540개로 **약28.7% 감소**했다.
이는 패딩 포함 토큰 수이며, 계산량이나 처리시간이 같은 비율로 줄었다는 뜻은 아니다.

동적 양자화 API의 범위는 [PyTorch 공식 문서](https://docs.pytorch.org/docs/main/generated/torch.ao.quantization.quantize_dynamic.html)를 참고한다.
설치된 버전에서 API가 동작하지만 폐기 예정 경고가 발생했다. 장기 운영 호환성이 검증된 구현으로 표현하지 않는다.

## 파일럿과 전체 실행

파일럿은 q001·q014·q030의 같은 후보에 대해 INT8 → FP32 대조 → INT8+길이순 순서로 각각 실행했다.
각 파일럿의 두 답변 가능 문항(q001/q014)은 필수 근거를 유지했다. q030은 근거 부족 질문이므로
이 재순위화 점수만으로 거절 성공을 판정하지 않았다.

| 파일럿 구성 | q001 | q014 | q030 |
|---|---:|---:|---:|
| INT8, 검색순 배치 | 30.604초 | 24.218초 | 22.863초 |
| FP32, 검색순 배치 재측정 | 54.969초 | 91.698초 | 38.528초 |
| INT8, 길이순 배치 | 19.914초 | 13.730초 | 13.476초 |

FP32 재측정은 이전 실행보다 크게 느렸다. 동일 머신의 순차 실행이지만 사용 중인Windows 환경이며
부하·캐시·실행 시점 차이를 통제하지 않았다. 이 표로 양자화와 배치 각각의 순수한 속도 효과를 단정하지 않는다.

| 전체30문항 | 기존FP32·검색순 | INT8·길이순 |
|---|---:|---:|
| 필수 근거 완전 확보 | 22/24 | 22/24 |
| 기존FP32 성공에서 회귀 | — | 0 |
| 재순위화 p50 | 28.272초 | 12.644초 |
| 재순위화 p95 | 41.428초 | 16.457초 |
| 30문항 시간 합계 | 924.829초 | 380.491초 |
| 모델 로딩 | 11.795초 | 9.916초 |
| 로딩 이후 양자화 준비 | 없음 | 12.752초 |

전체 실행의 관측 p50 비율은 약2.24배, p95 비율은 약2.52배다. 각1회 실행의 비교이며
반복·무작위 순서의 통제된 벤치마크가 아니다. 시간에는 토큰화·추론·정렬이 포함되며
검색·OpenAI 생성·HTTP·로딩·양자화 준비는 제외한다. percentile은 n30 nearest-rank다.

설치 환경은 torch2.14.1+cpu, transformers5.21.0, tokenizers0.23.3, 양자화backend는onednn이다.
Windows에서 확인한 그래픽 어댑터는Intel Graphics이며 이번 추론은CPU만 사용했다.

- [전체 품질·문항별 점수·지연](../data/evaluation/results/reranker-int8-length-v1.json)
- [파일럿·패딩·비교 결과](../data/evaluation/results/reranker-speed-comparison-v1.json)
- [최초 후보 진단과 FP32 결과](retrieval-candidates.md)

## 재현

기존 [재순위화 실험 환경](retrieval-candidates.md)을 사용한다. 출력이 있으면 새 파일명을 지정한다.
모델은 로컬 파일만 읽으며 원본 가중치를 덮어쓰지 않는다. 변환은 프로세스 메모리에서 수행한다.

```powershell
.\artifacts\reranker-venv\Scripts\python.exe -X utf8 scripts/rerank_candidates.py --input artifacts/reranker-input-v1.json --model-dir data/models/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e --output artifacts/reranker-int8-length-v1.jsonl --precision dynamic-int8 --batch-order length
.\.venv\Scripts\python.exe -X utf8 scripts/score_reranker.py --scores artifacts/reranker-int8-length-v1.jsonl --output data/evaluation/results/reranker-int8-length-v1.json
```

파일럿은 `--case q001 --case q014 --case q030`을 추가한다. 전체용 채점 도구는
부분 결과를30문항 평가로 채점하지 않으므로 파일럿에는 사용하지 않는다.
기본CLI 옵션은 기존FP32·검색순을 유지한다.

## 적용 판단과 다음

실제 생성 정확도는 여전히15/24(62.5%)이며 이번 검색 근거22/24(91.7%)와 구분한다.
근거 부족6문항 거절과 q002 인용 검증 문제도 새로 평가하지 않았다.
프로덕션 API·Docker·기존 저장소는 변경하지 않았으며 앱 가상환경에PyTorch를 추가하지 않았다.

CPU 실행 최적화의 효과는 확인했지만 p50만12.6초가 추가되어 기본 대화형 경로 채택은 보류한다.
다음 개선은 더 작은 다국어 재순위화 모델 또는 다른 실행backend/장치의 비용·지연 비교가 적합하다.
모델 변경·추가 다운로드는 범위를 정한 후 진행하며, 실제 생성 품질은 별도 승인 평가가 필요하다.
새로운 공개holdout과 독립 검수 없이 개발셋의22/24를 일반 성능으로 주장하지 않는다.
