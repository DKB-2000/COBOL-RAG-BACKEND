# COBOL 식별자 표현 보완

2026-10-27, 실제 생성 평가의 실패10건에 대해 위치 확인→최소 수정→무료 검증을 수행했다.
고정 질문·근거·원문·청크ID는 유지하고 임베딩 표현만 보완했다.

## 누락 위치와 가설

기존52청크의 cosine 순위를 재계산해 실제 기록의 상위10개와24/24 일치를 확인했다.
실패10건의 필수 근거는11~48위였고, 그10건에서는 문자 예산으로 제외된 청크가0개였다.
q013의 반복 근거도12위였다. 직접 누락 지점은4000자 예산 뒤가 아니라 상위10개 후보 선택 전이다.

8개 실패 문항의 필수 앵커는 기존128토큰 입력에도 포함돼 있었고 q011/q012만 일부가 잘렸다.
토큰 상한 확대만으로 전부 해결된다고 가정하지 않았다. 실제 tokenizer에서 대문자·하이픈
식별자가 여러 조각으로 분절되고 `apply transaction`은 일반 단어로 인코딩되는 차이를 확인했다.

## 수정과 무료 결과

영문 식별자 사이 하이픈/밑줄을 공백으로 바꾸고 소문자로 만든 표현을 추가한다.
숫자 음수·날짜의 숫자 간 하이픈은 유지한다. 원래 표현과 정규화 표현을 같은 기존 encoder로
각각 인코딩하고 동일 비중 평균 후 L2 정규화한다. 문서와 질문에 같은 규칙을 쓰며,
정규화 전후가 같은 질문은 한 번만 인코딩한다. 원문과 인용 자료는 수정하지 않는다.

| 방식 | 4000자·최대10청크 필수 근거 완전 포함 | 기존13건 회귀 |
|---|---:|---:|
| 기존 표현 | 13/24,54.2% | 기준 |
| 정규화 표현으로 교체 | 16/24,66.7% | q017, 적용 보류 |
| 원래 표현+정규화 표현 동일 비중 | **16/24,66.7%** | **0건** |

치환 후보의 회귀를 확인한 뒤 원래 신호를 보존하는 동일 비중 결합1개만 추가 확인했다.
개선은 q012(테이블 크기), q013(순회 인덱스), q014(호출 대상)다. 가중치/모델/검색 파라미터의
추가 탐색은 종료했다. 두 표현은 각각128토큰 encoder를 사용하며 최종 벡터는384차원이다.

실제 로컬 ONNX·별도 in-memory Chroma·프로덕션 서비스에서도13→16과 기존13건 보존을 확인했다.
가짜 모델이 실제 GenerationRequest를 캡처해 문맥을 검증한 것으로, **실제 답변 정확도나
거절률의 재측정은 아니다.** 전체 pytest167개와 변경 파일 Ruff가 통과했다.
원본 비교는 [버전 관리 결과](../data/evaluation/results/identifier-aware-retrieval-v1.json)에 있다.

## 적용·복구

기본 `LEGACY_RAG_RETRIEVAL_PROFILE=identifier-aware`이며 기존 벡터와 섞이지 않게 분리했다.

| 프로필 | 검색 collection | OpenAI 공개 collection |
|---|---|---|
| original | legacy-rag-api-v2-multilingual | legacy-rag-openai-public-v1 |
| identifier-aware | legacy-rag-api-v3-identifier-aware | legacy-rag-openai-public-identifier-v1 |

키를 설정한 같은 PowerShell에서 서버를 Ctrl+C로 종료하고 다시 시작한다.

```powershell
$env:LEGACY_RAG_RETRIEVAL_PROFILE = "identifier-aware"
$env:LEGACY_RAG_CHROMA_PATH = "./data/chroma/openai-public-identifier-v1"
.\.venv\Scripts\python.exe -m uvicorn legacy_rag.main:app --host 127.0.0.1 --port 8000
```

새 collection에 공개5개를 재색인한다. 같은 PowerShell의 OpenAI 모드·키 설정이 유지돼야 한다.
기존 데이터는 이동·삭제하지 않는다. 복구할 때는 original 프로필과 이전 Chroma 경로로 재시작한다.

```powershell
$env:LEGACY_RAG_RETRIEVAL_PROFILE = "original"
$env:LEGACY_RAG_CHROMA_PATH = "./data/chroma/openai-public-v1"
```

평가 실행기는30문항의 검색 문맥이 지정 프로필 검증 결과와 일치하는지 먼저 확인한다.
재시작하지 않은 기존 서버에서는 생성 요청 전에 중단함을 확인했다.

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_generation.py --prefix generation-v2 --retrieval-profile identifier-aware
```

위 명령은 검색 사전 검사만 수행한다. `--execute`는 별도 승인된 최대30회 유료 재평가다.
original 결과 재현에는 original 서버와 `--retrieval-profile original`을 사용한다.

## 한계

같은5개 합성 파일과 개발에 사용한24문항의 근거 지표이며 독립 holdout 성능이 아니다.
새 표현은 문서 인코딩을 두 번 수행하고 다른 입력에서 회귀할 가능성이 있다.
후속 [실제 생성 재평가](generation-evaluation-v2.md)에서는 인용 충족13/24→15/24를 확인했다.
q012/q013/q014가 개선됐지만 q002가 invalid_citations로 회귀했다. 위 무료 검색의 회귀0을
실제 생성 회귀0으로 해석하지 않는다. 새 모델·프레임워크·질문별 정답 규칙은 추가하지 않았다.
행 번호 COBOL 청킹과 운영 재현은 별도 남은 작업이며 이번 비교를 확장하지 않는다.
