# 검색 후보 확대와 재순위화 실험

## 현재 프로필의 후보 진단 — 2026-10-28

기본 identifier-aware 검색, 공개 합성 5파일·52청크·고정 30문항을 사용했다.
로컬 캐시 ONNX와 별도 ephemeral Chroma로 실행했고 실제 생성 호출은 0회다.
기존 상위10개/4,000자 선택 문맥은 저장 기준선과 30/30 문항에서 ID·순서가 일치했다.

| 검색 후보 수 | 후보 안에 필수 근거를 모두 포함 | 기존 순서로 10개·4,000자 선택 후 |
|---|---:|---:|
| 10 | 16/24 | 16/24 |
| 20 | 19/24 | 16/24 |
| 30 | 22/24 | 16/24 |
| 52 | 24/24 | 16/24 |

후보 52개는 전체 corpus이므로 24/24를 검색 품질이나 확장성 성과로 해석하지 않는다.
후보 확대만으로 최종 문맥의 근거 확보는 개선되지 않았다. 후보 수와 생성 문맥 크기는
별개다. 최종 문맥 제한을 유지하면서 관련 청크를 위로 올리는 실험을 진행한다.

| 실패 문항 | 필요한 문단 | 전체52개 검색에서의 현재 순위 |
|---|---|---:|
| q003 고객 레코드 검사 | VALIDATE-CUSTOMER | 18 |
| q004 오류 파일 기록 | MAIN-PROCESS / WRITE-ERROR-CUSTOMER | 37 / 3 |
| q005 최상위 반복 | MAIN-PROCESS | 13 |
| q006 입출금 분기 | APPLY-TRANSACTION | 38 |
| q010 최대 잔액 | APPLY-DEPOSIT | 23 |
| q011 테이블 적재 | LOAD-TRANSACTIONS | 14 |
| q018 계정 상태 분류 | READ-AND-SUMMARIZE | 21 |
| q022 월 범위 검사 | VALIDATE-DATE | 30 |

q004는 심볼이나 쓰기 구문만 확보해도 호출 조건 근거가 빠질 수 있는 사례다.
q002는 검색 근거 누락이 아닌 실제 생성의 인용 검증 실패이며 별도 개선 대상으로 둔다.

정본은 [후보별 결과와 입력 해시](../data/evaluation/results/retrieval-candidates-v1.json)다.
현재 프로덕션 검색·생성·Docker 설정은 이 진단으로 변경하지 않았다.

## 고정된 재순위화 실험 조건

사용자 승인 후 공개 [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)를
revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`로 고정했다.
공식 모델은 질문과 문서를 함께 받아 관련성 점수를 출력하는 다국어 재순위화 모델이다.
한국어 질문과 COBOL 코드에서의 효과는 본 실험으로 확인해야 한다.

- 후보30개, 최종 최대10개·원문4,000자. 후보30개 기준 근거 포함 상한은22/24다.
- passage는 기존과 같은 경로·심볼·원문이며 정답 주석이나 기대 심볼을 추가하지 않는다.
- CPU FP32, 4threads, batch4, 입력512토큰. 잘린 pair수와 질문별 소요시간을 기록한다.
- 모델과 라이브러리는 평가용 환경/캐시에만 설치하고 앱 가상환경·Docker 의존성은 유지한다.
- 원래16개 성공의 회귀와 전체 근거 포함 수를 함께 확인한다. 지연과 회귀가 크면 채택하지 않는다.
- 30문항에는 근거 부족6개도 포함하지만 이 실험으로 생성 거절 품질을 평가하지 않는다.
- 파라미터 탐색·LLM judge·OpenAI 요청·실제 API 적용은 이 실행에 포함하지 않는다.

## 재현 명령

### 실제 실행 결과와 적용 판단

2026-10-28, 위 조건으로 30문항·900개 query/passage pair를 1회 평가했다.
기존 검색과 같은 최종10청크·4,000자 제한에서 필수 근거 확보가
**16/24(66.7%) → 22/24(91.7%)**, +25.0%p로 개선됐다.

| 항목 | 관측 |
|---|---|
| 개선 문항 | q003, q005, q010, q011, q018, q022 |
| 기존 성공의 회귀 | 0건, 기존16문항 모두 유지 |
| 남은 근거 부족 | q004의 MAIN-PROCESS(37위), q006의 APPLY-TRANSACTION(38위): 후보30개 밖 |
| 재순위화 지연 p50 / p95 | 28.272초 / 41.428초 |
| 최대 문항 지연 | 53.091초 |
| 30문항 순차 처리시간 합계 | 924.829초, 약15.4분 |
| 모델 로딩 | 별도11.795초 |
| 512토큰에서 잘린 pair | 0/900 |
| 환경 | Windows CPU FP32·4threads, torch2.14.1+cpu / transformers5.21.0 / tokenizers0.23.3 |

지연은 토큰화와 재순위화의 wall time이며 검색·모델 로딩·OpenAI 생성·HTTP를 제외한다.
같은 로컬 작업 환경의 단일 실행이며 운영 SLA나 독립 부하 시험이 아니다.
자료: [문항별 결과·점수·근거·해시](../data/evaluation/results/reranker-evaluation-v1.json).

**현재 CPU 설정의 기본 API 적용은 보류한다.** 품질 개선은 확인됐지만 재순위화만으로
수십 초가 추가된다. 기존 프로덕션 검색·Docker와 실제 생성 평가15/24는 그대로 유지한다.
91.7%는 검색 근거 확보율이지 실제 답변 정확도가 아니다. q002 인용 오류 해결이나
근거 부족6문항의 거절 정확도 개선도 이번 실험으로 확인하지 않았다.

다음은 후보 회수와 재정렬 방식을 유지하면서 경량화 또는 다른 실행 장치의 비용/지연을
별도 비교하는 것이다. 또 다른 모델·가중치 탐색을 자동으로 수행하지 않는다.
실제 서비스 적용 전에는 미사용 공개 평가셋과 사용자 검수, 실제 생성 전후 평가가 필요하다.

### 실행 절차

저장소 루트 PowerShell에서 실행한다. 분석/출력 파일이 이미 있으면 새 파일명을 사용한다.
후보 진단의 기본 공개 결과는 보존한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/analyze_retrieval_candidates.py --output artifacts/candidates-recheck.json
.\.venv\Scripts\python.exe -X utf8 scripts/prepare_reranker_input.py --output artifacts/reranker-input-v1.json
```

별도 평가 환경의 최초 설치와 공개 모델 다운로드가 필요하다. 모델 파일 약2.3GB 외에
PyTorch/Transformers 패키지 용량이 추가된다. 외부 추론 서비스를 호출하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m venv artifacts/reranker-venv
.\artifacts\reranker-venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\artifacts\reranker-venv\Scripts\python.exe -m pip install transformers sentencepiece
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; print(snapshot_download('BAAI/bge-reranker-v2-m3',revision='953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e',allow_patterns=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentencepiece.bpe.model'],cache_dir='data/models',token=False,max_workers=2))"
```

준비 후 추론은 로컬 파일만 읽는다. 각 질문의 결과를 즉시 저장하며 중간 실패 시
부분 결과를 완전한 평가로 채점하지 않는다. 모델은 정답을 보지 않고 후보 순위만 계산한다.

```powershell
.\artifacts\reranker-venv\Scripts\python.exe -X utf8 scripts/rerank_candidates.py --input artifacts/reranker-input-v1.json --model-dir data/models/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e --output artifacts/reranker-scores-v1.jsonl
.\.venv\Scripts\python.exe -X utf8 scripts/score_reranker.py --scores artifacts/reranker-scores-v1.jsonl --output data/evaluation/results/reranker-evaluation-v1.json
```

채점에서만 기존 근거 주석을 사용한다. 결과는 개발셋에서의 검색 근거 확보율이며
실제 답변 정확도나 holdout 성능이 아니다. 실제 생성 재평가는 별도 호출 승인 후 진행한다.
