# COBOL-RAG-BACKEND

COBOL 같은 레거시 코드를 색인하고, 검색된 코드 위치를 근거로 답변하는 포트폴리오용 RAG 백엔드 골격이다.

현재는 합성 COBOL을 구조 단위로 청킹하고 로컬 다국어 임베딩으로 검색하는 API를 제공한다. P4의 `/query` 문맥·주장별 출처·거절 계약을 구현했으며, 생성 모델은 아직 연결하지 않았다. 정상 답변 경로는 가짜 모델로 테스트한다.

전체 구현 순서와 단계별 완료 기준은 [`docs/roadmap.md`](docs/roadmap.md)를 따른다.

## 구조

```text
src/legacy_rag/
├── api/          # FastAPI 라우트
├── ingestion/    # 로딩·정규화·청킹·색인
├── retrieval/    # Chroma와 검색 정책
├── generation/   # 근거 기반 답변 생성
└── evaluation/   # 평가 실행 코드
tests/
├── unit/
└── integration/
data/             # 반입 규칙과 로컬 데이터 위치
docs/             # 아키텍처와 의사결정
```

## 로컬 실행 예시

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
fastapi dev
```

OpenAPI 문서는 `http://127.0.0.1:8000/docs`에서 확인한다. 기본 데이터 루트는 `data/`, Chroma 경로는 `data/chroma/api-v2-multilingual/`이며 다음 환경 변수로 변경할 수 있다. 기존 `api-v1`과 실험 저장소는 자동 이동·삭제하지 않으므로 새 API 저장소에 다시 색인해야 한다.

- `LEGACY_RAG_DATA_ROOT`
- `LEGACY_RAG_CHROMA_PATH`
- `LEGACY_RAG_MODEL_DIR`: 아래에 명시한 로컬 모델 snapshot 디렉터리

설정은 프로세스 환경 변수로 읽는다. `.env.example`은 참고용이며 `.env`를 자동 로드하지 않는다. 설정을 바꾼 뒤에는 API 프로세스를 재시작한다.

주요 API는 다음과 같다.

- `GET /health`: 서비스 상태 확인
- `POST /documents/index`: 데이터 루트 안의 상대 경로를 색인
- `POST /search`: 관련 청크와 `chunk_id`, 상대 `source_path`, `symbol`, 점수 반환
- `POST /query`: 주장별 출처를 검증한 답변 또는 `refused`/`unavailable` 상태 반환

```powershell
$indexBody = @{
  source_paths = @("samples/account-balance.cbl", "samples/date-utility.cbl")
  rebuild = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/documents/index -ContentType application/json -Body $indexBody

$searchBody = @{ query = "잔액을 계산하는 프로그램은 무엇인가?"; limit = 3 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/search -ContentType application/json -Body $searchBody
```

API는 공개 모델 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`의 revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`를 로컬 CPU에서 사용한다. 기본 모델 디렉터리는 `data/models/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/snapshots/<revision>/`이다. API 자체는 다운로드하지 않으며, 모델이 없으면 색인·검색을 실행할 수 없다. 이미 다국어 실험을 실행했다면 해당 캐시를 그대로 사용한다. 새 환경의 공개 모델 다운로드 절차는 [다국어 기준선 실행 방법](docs/multilingual-embedding-baseline.md)을 따른다.

```powershell
$queryBody = @{ query = "잔액을 계산하는 프로그램은 무엇인가?"; limit = 10 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/query -ContentType application/json -Body $queryBody
```

생성 모델을 연결하지 않은 현재 기본 실행은 검색 문맥이 있으면 `status=unavailable`, `reason=generation_unavailable`을 반환한다. 검색 문맥이 없으면 `status=refused`, `reason=no_evidence`다. 실제 모델·비용 승인은 별도로 필요하며, 테스트 성공을 실제 답변 품질 검증으로 해석하면 안 된다. 상세 계약과 한계는 [P4 구현 기록](docs/grounded-query-contract.md)을 참고한다.

## 검색 품질 실험

파일 단위, 구조 기반 청킹, 경로·심볼 문맥화 입력과 다국어 임베딩을 동일 평가셋으로 비교했다. 실험상 최고 파일 순위 MRR은 다국어 창 평균 방식의 `0.6646`이다. API는 창 평균·관계 확장 없이 일반 다국어 구조·문맥화 검색(`MRR=0.6611`)으로 고정했다. 파일 지표와 실제 근거 검색은 구분해야 한다.

- [구조 청킹 비교](docs/structured-chunking-baseline.md)
- [문맥화 임베딩 비교와 재실행 방법](docs/contextual-embedding-baseline.md)
- [실제 상위 청크의 코드 근거 평가](docs/chunk-evidence-evaluation.md)
- [다국어 임베딩 비교와 재실행 방법](docs/multilingual-embedding-baseline.md)
- [호출·선언 관계 기반 문맥 보강 비교](docs/context-expansion-baseline.md)
- [긴 입력의 창 분할·평균 임베딩 비교](docs/windowed-embedding-baseline.md)

문맥화 구조 청크의 상위 5개에 필수 코드 근거가 모두 포함된 비율은 기존 영어 모델 `3/24`, 다국어 모델 `9/24`다. P2 실험에서는 API 전환을 보류했으나, 추가 튜닝을 중단하고 P4 개발을 시작하며 일반 다국어 방식을 연결했다. 이는 출시 품질 통과를 의미하지 않는다. 파일 단위 @5는 모든 5개 파일을 가져오므로 별도의 문맥 길이 비교가 필요하다.

다국어 상위 5개에 호출·선언 관계를 보강하면 `12/24`지만, 같은 최대 10개·4,000자 제한의 원래 검색은 `13/24`이며 평균 문맥도 더 짧았다. 관계 확장의 전체 적용은 보류했다.

긴 입력을 창으로 나눠 평균하면 상위 10개 근거 완전 포함은 `13/24 → 15/24`다. 그러나 상위 5개는 `9/24`로 같고 상위 1개는 `5/24 → 3/24`로 회귀해 기본 적용은 보류했다.

## 다음 구현 순서

1. 실제 생성 모델 선택·비용 승인 및 `GenerationModel` adapter 연결
2. 고정 질문의 실제 답변·인용·거절 평가로 P4 완료 여부 확인
3. P5 검색·답변 회귀 평가 자동화
4. 품질 게이트 통과 후 운영화와 배포 문서 작성

실제 코드나 데이터 추가 전 `CODEX.md`, `docs/architecture.md`, `data/README.md`를 읽는다.
