# BGE INT8 API 연결 — 2026-10-29

기본 검색에 로컬 `BAAI/bge-reranker-v2-m3`를 연결했다. 벡터 후보를 재정렬한 뒤
생성 문맥을 선택하며, 생성 공급자의 기본값은 계속 disabled다.
기존 API/Qwen의 근거 충족15/24는 재순위화 도입 전 [생성 비교](ollama-generation-comparison.md)의 결과다.
후속 [실제 생성 비교](reranked-generation-comparison.md)에서는 API22/24·Qwen17/24,
올바른 거절6/6·3/6을 관측했다. 아래 무료 검색·문맥 검증과 별도로 측정한 결과다.

## 실제 API 검증 결과

공개5개52청크·같은30문항을 사용했고, 두 방식 모두 실제 생성 입력의 본문·순서가
각각의 고정 기준과30/30 일치했다. [버전 관리 결과](../data/evaluation/results/reranker-api-verification-v1.json)에
문항별 문맥·근거 판정·지연·실행 이력·해시를 보존했다.

| 항목 | 기존 disabled | 기본 BGE INT8 |
|---|---:|---:|
| 답변 가능24문항의 필수 근거 완전 확보 | 16/24 (66.7%) | 22/24 (91.7%) |
| 기존 성공에서 회귀 | — | 0 |
| warm `/query` HTTP p50, 생성 stub | 0.034761초 | 11.425304초 |
| warm `/query` HTTP p95, 생성 stub | 0.075421초 | 15.810257초 |
| 실제 LLM 호출 | 0 | 0 |

개선은 q003/q005/q010/q011/q018/q022의6건이다. 첫 문항의 `/search` 후보30개 순위도
기존 INT8 실험과 일치했고 벡터 점수는 그대로였다. 실제 런타임에서 CPU4threads·onednn·
INT8 Linear146개·캐시된 모델 소유자1개를 확인했다.

BGE 새 프로세스의 첫 `/ready`는41.796673초였다. 임베딩·BGE 로딩·INT8 변환·첫 검색/추론을
합친 값이며 순수 모델 로딩 시간이 아니다. disabled의 준비 검사는 같은 프로세스의 색인 후
임베딩이 이미 로드된 상태였으므로 두 준비 시간을 동일한 cold 시작으로 비교하지 않는다.

Windows/Core Ultra5 125U/RAM16GB의 순차30회/profile·nearest-rank 관측이다.
이전 단독 재순위화12.644초와 이번 HTTP11.425초는 실행 조건이 달라 속도 개선의 인과관계로
해석하지 않는다. 개발셋의 검색 근거 지표이며 실제 답변 정확도·거절률·holdout 성능은 아니다.
전체 오프라인 테스트245개(11.14초), Ruff·pip check·Compose 기본/선택 구문 검사가 통과했다.

## 현재 경로

1. identifier-aware MiniLM 임베딩과 기존 Chroma에서 후보를 검색한다.
2. `/search`는 최소30개(`max(30, limit)`)를 BGE로 재정렬한 뒤 응답 limit을 적용한다.
3. `/query`는 재정렬된30개를 사용한다. OpenAI 모드에서는 승인 공개 청크만 남긴 다음
   최대10개·원문4000자를 선택한다. 긴 청크를 건너뛴 경우 뒤 후보도 계속 살핀다.
4. 기존 주장·인용 검증 계약으로 선택한 생성 어댑터를 호출한다.

반환 `score`는 원래 벡터 유사도이며 BGE 점수나 정답 확률이 아니다. 따라서 반환 순서와
score의 내림차순이 일치하지 않을 수 있다. 원문·ID·메타데이터와 기존 색인은 유지한다.

로컬 고정 revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`만 읽는다.
원격 코드와 자동 다운로드를 사용하지 않는다. CPU4threads·batch4·길이순 계산·최대512토큰이다.
Linear 계층만 동적INT8로 변환하며 원본 모델 파일은 변경하지 않는다.
동시 초기화에도 프로세스당 모델 소유자는 하나이고, 모델 잠금으로 추론을 직렬화한다.
다중 worker는 각각 모델 메모리를 사용하므로 현재 Docker는 worker1을 유지한다.

## 설치와 설정

프로젝트 루트에서 CPU torch를 먼저 설치한 다음 optional extra를 설치한다.

```powershell
.\.venv\Scripts\python.exe -m pip install "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[dev,evaluation,openai,reranking]"
.\.venv\Scripts\python.exe -m pip check
```

추가 패키지는 torch2.14.1·transformers5.21.0·tokenizers0.23.3·sentencepiece0.2.2로 고정한다.
모델 준비 명령은 [README](../README.md)의 빠른 시작에 있다. 이번 검증은 기존 캐시를 사용했다.

| 환경변수 | 기본값/의미 |
|---|---|
| `LEGACY_RAG_RERANKING` | `bge-int8`, 이전 검색 복구는 `disabled` |
| `LEGACY_RAG_RERANKER_MODEL_DIR` | `data/models/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| `LEGACY_RAG_GENERATION_PROVIDER` | `disabled`, 실제 생성은 별도 설정 |
| `LEGACY_RAG_RUNTIME_RERANKER_DIR` | Docker에 마운트할 호스트 snapshot 경로 |

모델은 첫 비어 있지 않은 검색에서 로드한다. `/health`는 모델을 로드하지 않고,
`/ready`는 실제 검색·재순위화를 수행하므로 첫 호출에 로딩·변환·추론 시간이 포함된다.
모델/패키지 누락이나 Python 추론 예외는 `/search`, `/query`, `/ready`에서
`503 {"detail":"service_unavailable"}`로 격리한다. 실패 시 자동으로 이전 검색으로 대체하지 않는다.
OS가 메모리 부족으로 프로세스를 종료하는 상황은 이 Python 예외 처리로 복구할 수 없다.

이전 검색으로 복구하려면 서버를 시작하는 PowerShell에서 설정한 뒤 프로세스를 재시작한다.

```powershell
$env:LEGACY_RAG_RERANKING = "disabled"
```

앱 직접 실행의 disabled 모드에서는 BGE 파일과 추가 패키지가 필요하지 않다.
Compose는 disabled일 때도 BGE bind mount가 존재하므로 호스트 경로를 준비해야 한다.
설정은 프로세스에서 캐시하며 실행 중 환경변수 수정으로 바뀌지 않는다. `.env`는 앱이 자동 로드하지 않는다.

## 실제 HTTP 검증 재현

```powershell
.\.venv\Scripts\python.exe scripts/verify_reranking_api.py
.\.venv\Scripts\python.exe scripts/verify_reranking_api.py --execute --prefix reranker-api-check-1
```

첫 명령은 입력만 검사한다. `--execute`는 127.0.0.1:8013의 새 API와 별도 Chroma를 사용한다.
공개5개52청크·고정30문항을 disabled와 기본 bge-int8로 각각 실행하며, 기존 서버/DB를 교체하지 않는다.
실제 검색·DI·문맥 조립을 통과한 모델 입력을 기록용 stub에서 관측하고 공개 원문과 대조한다.
OpenAI 공개 필터가 문맥 선택보다 먼저 적용되는지는 전용 API 통합 테스트에서 따로 검증한다.
stub은 고정 거절만 반환한다. **실제 LLM 호출은0회이고 답변/거절 정확도 평가가 아니다.**
소스 해시·문항·본문·청크 순서·기존 실험 문맥·첫 문항의 후보30개 순위와 벡터 점수 보존을 검증한다.
출력은 Git 제외 `artifacts/<prefix>-*`에 보존하며 기존 prefix는 덮어쓰지 않는다.
순차 HTTP30회/profile의 nearest-rank p50/p95와 cold `/ready` 각1회를 분리한다.
실행 중 임시 idle 절전 가드는 종료 시 해제한다.

유료 생성 평가의 `scripts/evaluate_generation.py`도 기본 bge-int8 문맥을 검사하도록 바꿨다.
기존 original/identifier-aware 생성 기준선을 재현하려면 서버에 disabled를 설정하고 CLI에도
`--reranking disabled`를 지정한다. 문맥 불일치는 생성 전에 중단한다.
Ollama 비교 CLI는 과거 비교 조건을 보존하도록 자식 API에 disabled를 명시한다.

## 메모리와 검증 범위

첫 HTTP 실행 v1은 FP32 모델 전체를 복제하는 INT8 변환 중 중단됐다.
Windows는 같은 시각에 가상 메모리 부족과 `c10.dll / 0xc0000005` 종료를 기록했다.
다른 앱을 종료하거나 페이지파일을 변경하지 않고 `inplace=True` 변환으로 전체 복제를 제거했다.
원본 v1 자료를 보존하고 새 v2에서 전체 검증을 완료했다. v1의 stub30회와 v2의60회를 합해
기록용 stub은90회, 실제 생성은0회다. 메모리 절감량의 통제된 peak 측정은 수행하지 않았다.

Dockerfile의 CPU 패키지와 Compose의 읽기 전용 BGE 마운트를 맞췄다.
2026-10-29 전용 project에서 실제 이미지 빌드·Linux CPU INT8·HTTP 검색·컨테이너 재생성 후
재색인 없는 검색 해시 보존을 확인했다. 기존 서버/컨테이너는 교체하지 않았고 검증 서비스는 정지했다.
후보 집합30/30과 필수 근거22/24의 충족 문항은 Windows와 같았지만 **문맥 완전 일치는0/30으로 실패**했다.
Linux x86 엔진을 oneDNN으로 바꾼3문항 진단에서도 일치하지 않아 원인은 미분리 상태다.
프로덕션 설정·모델·기준 문맥을 바꿔 검사를 통과시키지 않았다. Linux 실제 생성은 호출하지 않았으며
Windows의 생성 정확도·거절률을 Linux에 적용할 수 없다.
[최신 Linux 결과와 재현 절차](runtime.md#최신-bge-linux-검증--2026-10-29)에 실패 원본과 범위를 기록한다.
과거 Linux 검색 지연도 [운영 기록](runtime.md)에 도입 전 값으로 보존한다.
