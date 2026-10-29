# 로컬 Ollama 생성 어댑터

`LEGACY_RAG_GENERATION_PROVIDER=ollama`를 선택하면 기존 `GenerationModel` 계약으로
로컬 Qwen3를 호출한다. 기본값은 계속 `disabled`다. OpenAI 키는 필요하지 않다.

## 호스트에서 실행

Ollama 서버와 `qwen3:4b` 모델이 먼저 설치되어 있어야 한다. 어댑터는 모델을 다운로드하거나
서버를 시작하지 않는다. Windows 설치 예시 경로는 프로그램 `D:\Model\Ollama`,
모델 `D:\Model\models`다. 모델 저장 경로는 Ollama 서버의 `OLLAMA_MODELS` 설정이며
RAG 앱의 임베딩 모델 경로 `LEGACY_RAG_MODEL_DIR`와 다르다.

저장소 루트 PowerShell에서 실행한다. `.env`는 자동으로 로드하지 않는다.

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/version
Invoke-RestMethod http://127.0.0.1:11434/api/tags
$env:LEGACY_RAG_GENERATION_PROVIDER = "ollama"
$env:LEGACY_RAG_OLLAMA_TIMEOUT_SECONDS = "300"
$env:LEGACY_RAG_OLLAMA_MAX_OUTPUT_TOKENS = "1024"
.\.venv\Scripts\python.exe -m uvicorn legacy_rag.main:app --host 127.0.0.1 --port 8000 --no-access-log --log-config logging.json
```

사용 중인 검색 프로필과 Chroma 경로에 기존 색인이 있으면 재사용한다. Ollama용 collection은
새로 만들지 않는다. OpenAI 전용 공개 collection과 일반 검색 collection은 기존처럼 구분한다.
색인이 없는 환경에서는 [README](../README.md)의 공개 샘플 색인 절차를 먼저 수행한다.
설정 변경 후 앱 서버를 재시작해야 캐시된 생성 클라이언트가 교체된다.

## 요청과 응답 계약

- 모델은 설치된 `qwen3:4b`, 주소는 `http://127.0.0.1:11434/api/chat`로 고정한다.
  `OLLAMA_HOST`, 환경 프록시, cloud 모델 선택을 사용하지 않고 리디렉션을 따라가지 않는다.
- 기존 시스템 프롬프트와 검색 문맥을 전달하고, `GeneratedAnswer`의 JSON Schema를 `format`에
  넣으며 `status`, `claims`, `reason` 모두 필수로 전달한다. 최종 `message.content`만
  Pydantic으로 다시 검증하고 `message.thinking`은 무시한다.
- `stream=false`, `think=false`, 온도0, 문맥8192토큰, 출력 기본1024토큰이다.
  `think=false`는 요청 설정이며 설치된 모델에서 추론 억제가 항상 성공한다는 보장은 아니다.
- 입력은 시스템/사용자 문자열 합계16000자까지 허용한다. 문자 상한은 정확한 토큰 계산이나
  문맥 절단 방지 검증이 아니다. 출력 상한은64~4096, timeout은0초 초과~600초까지 설정한다.
- `done=true`, `done_reason=stop`인 최종 JSON만 수락한다. 잘린 응답, 빈 응답, 잘못된 JSON,
  출력 계약 위반, HTTP 오류/시간 초과는 기존 `unavailable / generation_unavailable`로 반환한다.
  실제 제공하지 않은 청크를 인용하면 기존 서비스가 `refused / invalid_citations`로 거절한다.
- 재시도와 다른 공급자로의 자동 전환은 없다. 요청마다 `keep_alive=0`으로 모델을 내리므로
  후속 요청에 다시 로딩 시간이 들 수 있다. 앱 종료 시 HTTP 클라이언트와 캐시를 정리한다.

이 구성은 같은 Windows 호스트의 Ollama를 위한 것이다. 현재 Docker 구성의
`127.0.0.1`은 컨테이너 자신을 가리키므로 호스트 Ollama 연결을 지원하지 않는다.

## 검증 범위

HTTP MockTransport와 FastAPI 테스트로 정상 응답·근거 부족 거절·잘못된 인용·잘린 출력·
오류 격리·공급자 선택·클라이언트 종료를 검증한다. 실제 생성 API는 테스트에서 호출하지 않는다.
실제 HTTP `/query`의 고정30문항 평가도 완료했다. 근거 충족15/24, 올바른 거절4/6,
환경 영향 분리 후 p50/p95 88.176/173.417초였다. 원본 운영 실패와 별도 환경 재측정,
기존 API 비교와 검수 한계는 [평가 보고서](ollama-generation-comparison.md)를 따른다.

프로토콜 근거: [Ollama Chat API](https://docs.ollama.com/api/chat),
[구조화 출력](https://docs.ollama.com/capabilities/structured-outputs),
[추론 출력 제어](https://docs.ollama.com/capabilities/thinking).
