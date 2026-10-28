# 고정30문항 생성 평가 v1

2026-10-27, 공개 합성 COBOL5개를 대상으로 실제 API 질문30건을 순차 실행했다.
모델 설정은 gpt-6-luna, reasoning none, 출력 상한1000토큰, 자동 재시도0이다.
전체 원본 응답을 보존했고 추가 호출이나 모델 judge를 사용하지 않았다.

의미적 채점자는 **Codex Orchestrator**다. 같은 개발 에이전트의 코드 대조를 통한1차 검토이며
독립 사람 검수는 완료하지 않았다. 아래 의미 지표를 독립적으로 검증된 정확도로 표현하지 않는다.

## 결과와 분모

| 항목 | 결과 | 의미 |
|---|---:|---|
| 수집 | 30/30 | 답변 가능24·근거 부족6 모두 포함 |
| 응답 상태 | answered14·refused16 | unavailable/error0 |
| 답변 제공률 | 14/24,58.3% | 답이 있는 질문 중 답변을 반환한 비율 |
| 내용 정답 | 14/24,58.3% | 전체 원본과 대조한1차 판정, 거절10건은 성공이 아님 |
| 정답·완전성·인용 모두 충족 | 13/24,54.2% | q013의 인용 불충분을 별도 실패로 처리 |
| 올바른 근거 부족 거절 | 6/6,100% | q025~q030, 작은6건 표본이며 일반 성능을 보장하지 않음 |
| 인용 ID 연결 | 18/18,100% | ID가 반환 출처 목록과 연결됨, 의미적 근거성과 다름 |
| 인용된 사실의 의미적 근거성 | 22/23,95.7% | 생성 주장14개를 사실23개로 분리해 대조, 미판정0 |
| 인용의 충분성 | 22/23,95.7% | 같은23개 사실을 해당 인용이 충분히 뒷받침하는지 판정 |
| 질의 HTTP 지연 | p50 1.735초·p95 5.688초 | n30, nearest-rank, 순차 실행 |

같은 사실의 **전체 원본 기준 정답 여부**와 **실제로 인용한 청크 기준 근거 충분성**을 구분했다.
답변을 제공한14건만 분모로 삼아 서비스 전체 정확도가100%라고 보고하지 않는다.
미채점 요약의 의미 점수는0% 대신 null/pending으로 남긴다. 반환하지 못한10건은 전체24건
답변 성공률의 실패에 포함한다. 거절 대상의 unavailable/실행 오류/invalid_citations는
올바른 근거 부족 거절로 계산하지 않는다.

## 확인된 실패

원본에는 답이 있지만 거절한 질문은 다음10개다.

| 질문 | 필요한 원본 근거 |
|---|---|
| q003 | VALIDATE-CUSTOMER |
| q004 | MAIN-PROCESS의 오류 분기와 WRITE-ERROR-CUSTOMER |
| q005 | CUSTOMER-IMPORT의 MAIN-PROCESS 반복 |
| q006 | APPLY-TRANSACTION의 EVALUATE |
| q010 | APPLY-DEPOSIT의 최대 잔액 검사 |
| q011 | LOAD-TRANSACTIONS |
| q012 | WS-TRANSACTION-ENTRY OCCURS20 |
| q014 | POST-TRANSACTIONS의 CALL ACCOUNT-BALANCE |
| q018 | READ-AND-SUMMARIZE의 AR-STATUS 분기 |
| q022 | VALIDATE-DATE의 월 범위 검사 |

각 질문 전에 별도로 수집한 검색 결과의 재구성 문맥에서 위 필수 근거가 누락됐다.
이는 검색/문맥 누락을 우선 조사할 근거지만 실제 모델 입력을 직접 관측한 결과는 아니다.
정답 주석을 검색 정책이나 모델 요청에 넣어 이 결과를 보정하지 않았다.

q013은 `WS-INDEX`라는 정답을 반환했으나 인용은 `HANDLE-POST-RESULT`뿐이었다.
그 문단은 `WS-ACCOUNT-ID(WS-INDEX)` 조회를 보여주지만 반복 제어는 보여주지 않는다.
전체 원본 `MAIN-PROCESS`의 `PERFORM ... VARYING WS-INDEX`로 정답을 확인할 수 있으므로
내용 정답은 인정하되, 인용의 충분성은 보수적으로 실패 판정했다. 사용자 재검수 대상이다.

## 실행과 측정 방법

기존 질문·근거 v1을 변경하지 않았다. 새 [채점 기준](../data/evaluation/answer-rubric-v1.jsonl)은
질문별 정답 확인 사항과 오답 방지 조건이다. 질문이 문단 이름만 요구하면 정확한 이름과
충분한 인용으로 충족할 수 있으며, 보충 설명을 답변에 전부 나열하도록 강제하지 않는다.
한 생성 주장에 여러 사실이 있으면 채점 파일에서 분리한다.

`scripts/evaluate_generation.py`가 HTTP API와 평가 모듈을 조합한다. 평가 패키지 자체는
API 계층을 import하지 않는다. 모델 요청에는 query/limit만 전달하고 정답·기대 심볼·rubric은
응답 후 결과/채점에만 결합한다. 실행 전에 데이터 해시와 공개52청크를 확인한다.
검색 결과의 ID·원문·출처가 공개 corpus와 다르면 해당 질문의 생성 요청을 보내지 않는다.

사전 검사와 각 질문의 별도 `/search`로 로컬 검색 모델이 예열된 상태다. 지연시간은
`/query` 요청부터 응답까지이며 그 안의 검색·외부 생성·직렬화를 포함한다. 별도 진단 검색과
채점 시간은 제외한다. n30의 p95를 동시성 부하 시험이나 운영 SLA로 해석하지 않는다.

현재 응답은 실제 프롬프트·공급자 model ID·usage·청구 비용을 반환하지 않는다.
`reconstructed_context`는 별도 검색 결과를 같은4000자/10청크 정책으로 재구성한 자료다.
`actual_model_prompt_observed=false`이며 실제 모델 입력을 캡처했다고 주장하지 않는다.

## 재현

이 v1은 original 검색 프로필의 결과다. 같은 설정을 재현하려면 서버를 original 프로필로
실행하고 기존 공개 collection에5개52청크가 있어야 한다. 식별자 보완 프로필의 결과는 별도 v2로 구분한다.
처음 기본 실행은 검색 사전 검사만 하며 생성 비용이 없다.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_generation.py --retrieval-profile original
```

아래 실행은 **새 유료 평가**다. 기존 generation-v1 실행은 중복 방지로 다시 실행할 수 없다.
새 실행은 별도 호출 범위·비용 승인을 받은 후 새 prefix로 수행한다.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_generation.py --execute --prefix generation-original-rerun --retrieval-profile original
```

최대30개 `/query` 요청이며 자동 재시도·재개는 없다. 실패도 행으로 저장하고 매 행마다 flush한다.
HTTP timeout 뒤 공급자 과금이 취소된다고 가정하지 않는다. 반복 실행을 위해 기존 파일을
삭제하지 않는다. 실제 평가 입력은 원래 공개30문항으로 고정하며 로컬 전용 자료는 사용하지 않는다.

`artifacts/<prefix>-reviews-template.jsonl`은 사람 검수용이며 원본은 보존하고 별도 사본을
작성한다. supported/contradicted/insufficient/pending과 정답/완전성/거절 판정을 기록하고
reviewer_kind를 human 또는 codex_orchestrator로 명시한다. 오프라인 집계는 다음과 같다.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_generation.py --score artifacts/generation-v1-reviews-codex.jsonl
```

원본/검색 진단/리뷰 템플릿은 Git 제외 `artifacts/generation-v1-*`에 있다.
공개 가능한 응답·채점·요약·입력/코드 해시는
[버전 관리 결과](../data/evaluation/results/generation-evaluation-v1.json)에 보존했다.
실제 token usage/청구 비용은 null이며, 미측정을0달러라고 표현하지 않는다.

실행 전 견적은 문항당 입력4000·출력1000토큰 가정에서30건0.027USD였고, 여유를 둔
0.03~0.10USD 예상 범위로 승인받았다. Standard 입력0.10/출력0.50USD per1M의
[공식 요금](https://developers.openai.com/api/docs/models/gpt-6-luna)을 사용한 추정이며 실제 청구액은 아니다.

## 검증과 남은 일

신규 평가와 기존 질의/평가 회귀35개, HTTP MockTransport4개가 통과했다(총39개).
이전 OpenAI 연결용39개는 사용자가 별도로 실행한 결과다. 변경 파일 Ruff도 통과했다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_generation_evaluation.py tests/unit/test_answer_metrics.py tests/unit/test_generation_evaluation_http.py tests/unit/test_grounded_query.py tests/unit/test_evaluation_runner.py tests/unit/test_evidence_metrics.py -q
```

기존 공개/평가 입력16개와 로컬 복제12개 해시를 보존했고 유료 질의 의도/결과30개가
고유 case ID와 일치함을 확인했다.

평가 수집·Codex1차 코드 대조는 완료했다. 사용자 독립 검수와 품질 수락은 남아 있다.
현재 핵심 한계는 답이 있는10건의 근거 누락과 q013의 인용 충분성이다.
단순히 모델의 거절 기준을 완화해 정답률을 높이는 변경은 하지 않는다.
검색 개선·재평가는 별도 범위로 정하고, 행 번호 포맷 호환성·운영 재현 등 남은 제출 작업도
계속 추적한다. 작은 합성5개 데이터셋의 결과를 실제 사내 COBOL 성능으로 일반화하지 않는다.
