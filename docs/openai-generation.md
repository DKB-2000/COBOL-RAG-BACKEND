# OpenAI 생성 연결

2026-10-27: 선택적 어댑터·환경 설정·오프라인 테스트를 작성했다. 기본 생성은 disabled다.
현재 세션은 실제 API 호출·SDK 설치·pytest를 수행하지 않았다. 실제 계정의 모델 접근 권한과
API 응답 호환성, 답변·거절 품질은 사용자의 수동 검증 이후에 판단한다.

후속 확인: 사용자가 신규 테스트39 passed(2.62초)를 보고했다. 최초 unavailable 응답은
사용자 PowerShell의 provider disabled/키 미설정 진단으로 이어졌다. 같은 PowerShell에서
설정을 수정하고 재시작한 뒤 공개5개52청크 색인과 실제 `/query` 정상1건을 확인했다.
HTTP200/answered, 주장2개/인용청크2개, HTTP 경과6.127초이며 답변을 원본과 대조했다.
위 미실행 설명은 최초 구현 시점 기록이다. 이후 별도 승인으로 고정30문항을 실행했고
[Codex1차 생성 평가](generation-evaluation-v1.md)를 기록했다. 독립 사람 검수는 남아 있다.
단건 연결 시간6.127초는30문항의 평균/p95가 아니다. usage·실제 청구 비용은 미측정이다.

## 계약과 설정

2026-10-29부터 기본 검색은 BGE INT8 재순위화를 포함한다. 실제 서버를 실행하기 전에
[BGE 의존성과 모델 준비](reranker-api.md)를 따른다. 기존 생성 평가15/24는 disabled 조건의
이전 문맥 결과다. 새 문맥의 [실제 생성 비교](reranked-generation-comparison.md)에서는
API 근거 충족22/24·올바른 거절6/6을 확인했다. 개발셋의 Codex1차 검수다.

공식 Python SDK의 Responses API `responses.parse(text_format=GeneratedAnswer)`를 사용한다.
시스템 지시와 질문/문맥을 역할별로 분리하고, 구조화된 주장·거절을 기존 계약으로 재검증한다.
실제 제공한 청크 외의 ID 인용은 기존 서비스가 답변 전체를 거절한다.

| 환경 변수 | 기본값 | 역할 |
|---|---|---|
| `LEGACY_RAG_GENERATION_PROVIDER` | `disabled` | `openai`일 때만 공급자 초기화 |
| `LEGACY_RAG_RETRIEVAL_PROFILE` | `identifier-aware` | 식별자 보완 표현, 이전 방식은 original |
| `OPENAI_API_KEY` | 없음 | 서버 환경변수, SecretStr로 설정 표현에서 숨김 |
| `LEGACY_RAG_OPENAI_MODEL` | `gpt-6-luna` | 첫 구현의 단일 지원 모델; 실제 사용 전 예산·계정 접근 확인 |
| `LEGACY_RAG_OPENAI_TIMEOUT_SECONDS` | `30` | SDK HTTP read/write/pool 제한, connect는 최대5초; 요청 전체의 절대 마감시간은 아님 |
| `LEGACY_RAG_OPENAI_MAX_OUTPUT_TOKENS` | `1000` | 출력 상한, 설정 허용 범위64~2048 |

reasoning effort는 `none`, SDK 자동 재시도는0이다. 실패한 요청에 자동 대체 모델·재호출을
붙이지 않는다. 질문 최대4000자, 원문 문맥 최대4000자/10청크, 시스템 지시와 직렬화된
문맥을 합친 생성 입력은 최대16000자로 제한한다. 문자 제한은 정확한 토큰/달러 상한이 아니다.
모델별 파라미터 차이 때문에 다른 모델 문자열을 임의로 넣지 않고 별도 호환성을 검증한다.

`store=False`로 요청하며 대화 이력·도구·파일 업로드를 사용하지 않는다. 이 설정은
모든 보존이0이라는 의미는 아니다. SDK 목적지는 `https://api.openai.com/v1`로 고정하고
환경의 임의 base URL·HTTP proxy를 사용하지 않는다. 프록시가 필수인 환경은 별도 구성 검토가 필요하다.
키·전체 프롬프트·공급자 예외를 앱에서 기록하지 않는다. SDK 디버그 로깅은 켜지 않는다.

## 데이터 경계

OpenAI 모드의 허용 입력은 기존 공개 합성5개다.

- `samples/account-balance.cbl`
- `samples/customer-import.cbl`
- `samples/daily-report.cbl`
- `samples/date-utility.cbl`
- `samples/transaction-post.cbl`

`api/public_corpus.py`의 명시된 경로·정규화된 원문 해시와 일치해야 색인할 수 있다.
생성 직전에도 승인 소스로 재구성한 청크와 ID·본문·출처·언어·심볼·원문해시·인덱스를
대조한다. 메타데이터만 공개 파일처럼 바꾼 비공개 본문도 모델 문맥에 포함하지 않는다.
허용 청크가 없으면 `refused/no_evidence`이고 모델은 호출하지 않는다.

identifier-aware OpenAI collection은 `legacy-rag-openai-public-identifier-v1`이며 기존 original의 `legacy-rag-openai-public-v1`과 구분한다.
Chroma 경로도 아래처럼 별도로 설정한다. 기존 벡터와 평가 결과는 이동·삭제하지 않는다.
공개 소스를 수정하면 새 해시/청크 승인이 필요하며 자동 승인하지 않는다.

`data/raw/`의 로컬 평가24문항과 원문, 별도 승인된 주문 예제 묶음은 이번 OpenAI 허용 범위가
아니다. 별도 `/search`나 다른 로컬 도구의 일반 데이터 접근을 모두 막는 기능은 아니다.
질문 본문은 외부로 전송되므로 로컬 전용 코드·질문·답안을 직접 붙여넣지 않는다.
질문의 일반 민감정보 탐지·마스킹은 구현하지 않았다. 공개 샘플만 확인하는 로컬 데모 범위다.

## 비용 없는 테스트

프로젝트 루트에서 의존성을 설치한다. SDK 설치는 모델 API 호출과 다르며 아래 테스트는
가짜 응답 또는 httpx MockTransport만 사용한다. 실제 키가 필요하지 않다.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,openai]"
$env:LEGACY_RAG_GENERATION_PROVIDER = "disabled"
.\.venv\Scripts\python.exe -m pytest tests/unit/test_openai_generation.py tests/unit/test_openai_dependencies.py tests/integration/test_openai_query.py tests/unit/test_grounded_query.py tests/integration/test_query_api.py tests/integration/test_structured_api_index.py -q
```

SDK가 없으면 실제 SDK 전송 계약 테스트 파일은 skip된다. 설치 후에는 skip 없이 실행됐는지 확인한다.
생성 정상·근거 거절·잘린/잘못된 출력·공급자 안전 거절·401/429/500·timeout·미등록 인용·
비공개/위조 문맥 차단·색인 전 거절·키 미설정·초기화 실패·클라이언트 정리를 확인한다.
이 테스트는 실제 OpenAI 서버가 해당 모델·계정·schema를 수락하는지 검증하지 않는다.

## 수동 실제 연결 확인 — 유료 호출

모델과 호출 예산을 확정한 뒤 실행한다. 키는 채팅/소스/명령행 인자에 넣지 않는다.
환경변수는 해당 터미널과 그 자식 프로세스에만 설정한다. `.env`는 자동 로드하지 않는다.

```powershell
$ragApiKeySecure = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $ragApiKeySecure).Password
Remove-Variable ragApiKeySecure
$env:LEGACY_RAG_GENERATION_PROVIDER = "openai"
$env:LEGACY_RAG_OPENAI_MODEL = "gpt-6-luna"
$env:LEGACY_RAG_RETRIEVAL_PROFILE = "identifier-aware"
$env:LEGACY_RAG_CHROMA_PATH = "./data/chroma/openai-public-identifier-v1"
.\.venv\Scripts\python.exe -m uvicorn legacy_rag.main:app --host 127.0.0.1 --port 8000 --no-access-log --log-config logging.json
```

다른 터미널에서 먼저 허용된5개를 새 collection에 색인한다. 색인은 로컬 임베딩만 사용하므로
OpenAI 비용이 없다. 원래 공개 모델 캐시가 있어야 하며 앱은 자동 다운로드하지 않는다.

```powershell
$ragIndexBody = @{
  source_paths = @(
    "samples/account-balance.cbl", "samples/customer-import.cbl",
    "samples/daily-report.cbl", "samples/date-utility.cbl", "samples/transaction-post.cbl"
  )
  rebuild = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/documents/index -ContentType "application/json" -Body $ragIndexBody
```

다음 `/query` 요청은 사용 가능한 문맥이 있으면 유료 호출1회를 시도한다.

```powershell
$ragQueryBody = @{ query = "ACCOUNT-BALANCE는 잔액을 어떻게 처리하나요?"; limit = 10 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/query -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($ragQueryBody))
```

정상 답변의 인용 ID/출처를 실제 코드와 대조한다. 근거 부족 질문은 모델의 의미적 판정이므로
전체30문항의 별도 평가가 필요하다. 처음에는 자동 평가 루프 대신 소수 수동 요청만 사용한다.
클라이언트 종료나 timeout은 공급자 처리·과금 취소를 보장하지 않으며 달러 단위 강제 상한은
앱에 구현하지 않았다. 실제 사용량은 API 프로젝트에서 확인한다.

## 장애 응답과 복구

키/SDK 미설정·초기화 실패: 문맥이 있으면 `unavailable/generation_unavailable`.
인증/쿼터/timeout/잘못된 JSON/출력 잘림/공급자 안전 거절도 같은 상태로 정리하고
원시 예외는 응답에 넣지 않는다. 공급자 안전 거절을 코드 근거 부족으로 오표기하지 않는다.
근거 부족·충돌의 구조화된 답변은 기존 `refused` 이유를 보존한다.
생성 실패가 `/search` 호출을 비활성화하지 않는다.

키·설정을 바꾼 뒤에는 서버를 재시작한다. 초기화 결과는 프로세스에서 캐시되며 종료 때
SDK 클라이언트를 닫는다. 서버를 종료한 뒤 같은 터미널에서 필요하면 다음처럼 해제한다.

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
$env:LEGACY_RAG_GENERATION_PROVIDER = "disabled"
```

## 실제 평가 기록

공개 고정30문항의 [v1 평가](generation-evaluation-v1.md)와
[식별자 보완 후 v2 비교](generation-evaluation-v2.md)를 보존한다.
Codex1차 검토에서 인용 충족 답변은13/24→15/24, 올바른 근거 부족 거절은6/6으로 같았다.
개선3건과 invalid_citations 회귀1건이 있으며 독립 사람 검수는 남아 있다.
두 평가 모두 각30회·자동 재시도0이며 실제 사용 토큰과 청구액은 미측정이다.

## 공식 근거

- [Structured Outputs와 Python parse](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [GPT-6 Luna와 reasoning 설정](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [공식 SDK](https://developers.openai.com/api/docs/libraries)
- [데이터 보존 정책](https://developers.openai.com/api/docs/guides/your-data)
