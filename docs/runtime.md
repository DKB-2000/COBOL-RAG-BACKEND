# 실행 재현과 기본 운영

Docker/Compose와 안전한 로그·오류 처리·검색 준비 검사를 구현했다. 최신 Windows 전체 테스트는
252개 통과했다. 2026-10-29 BGE 이미지의 Linux 빌드·실제 검색·재생성 영속성을 확인했다.
Windows와 필수 근거 충족 문항은 같지만 문맥 순서는 일치하지 않았다. 전체 검증 통과로 표현하지 않는다.
기존 컨테이너는 보존했고 전용 검증 서비스는 정지했다. 2026-10-27의 도입 전 측정도 아래에 보존한다.

## 최신 BGE Linux 검증 — 2026-10-29

Docker Engine29.7.2·Compose5.4.0, Linux/amd64·WSL2 VM 약8GB에서 공개5개52청크를 사용했다.
전용 project는 `legacy-rag-bge-verify-v1`, 포트는 `127.0.0.1:8015`, 볼륨은
`legacy-rag-bge-verify-v1_runtime-chroma`다. 생성 provider는 disabled, 실제 생성·`/query`·유료 호출은0회다.

| 관측 | 결과 |
|---|---|
| 이미지 빌드 | 196.910초, `legacy-rag-backend:bge-int8-verify-v1` |
| Linux 모델 확인 | torch2.14.1+cpu, x86 엔진, qint8 Linear146개, CPU threads4 |
| 최초 공개 색인, 초기화 포함 | 5개 파일·52청크, 28.689초 |
| 최초 검색 준비 검사 | 44.695초, 별도 모델 로딩·INT8 변환 포함 |
| 재생성 후 검색 준비 검사 | 24.729초 |
| 재생성 전/후 warm 검색 p50·p95, 각각 n10 | 13.324·18.374초 / 9.184·12.251초 |
| 고정30문항 warm `/search limit30` p50·p95 | 13.780·16.965초 |
| Windows와 후보 집합 일치 | 30/30 |
| 필수 근거를 모두 포함한 문항 | 22/24, Windows와 같은 문항·개선0·회귀0 |
| Windows와 선택 문맥 ID·순서 완전 일치 | **0/30, 실패**; 순서를 제외한 집합 일치도5/30 |
| 같은 이미지·볼륨으로 컨테이너 재생성 | 새 컨테이너 ID, 재색인 없이 상위10청크 해시 일치 |

청크 후보 집합과 근거 포함 지표가 같아도 LLM에 들어갈 문맥 순서·구성이 같다는 뜻은 아니다.
문맥은 실제 `/search limit30` 결과에서 최대10개/4000자로 재구성했다. 모델에 전달된 프롬프트를
관측한 검증이나 Linux 답변 정확도 평가가 아니다. Windows의 API/Qwen 생성 점수는 해당 Windows
문맥의 결과로 유지한다. 문맥 동등성 실패는 미해결 항목이다.

Linux는 ONNX Runtime1.31.1·양자화 x86, Windows 기준은1.30.0·oneDNN이었다.
같은 Linux 이미지·모델·DB에서 엔진만 oneDNN으로 바꾼 q001/q010/q024 진단도 모두 문맥이 달랐다.
엔진 차이만으로 원인을 단정할 수 없다. 진단 후 원래 x86 설정으로 재생성했으며 앱 코드·모델·기준 결과는
변경하지 않았다. 최초 strict 문맥 검사의 exit1·문항별 결과와 진단 원본을 보존했다.

실제 inspect로 UID/GID10001·읽기 전용 rootfs/모델/샘플·loopback·키 미전달을 확인했다.
설치 Python 코드 전체 해시는 호스트와 같고 `pip check`도 통과했다. 422/400 고정 오류 응답,
서버 생성 요청 ID, 합성 민감 문자열의 로그 비노출을 확인했다. 기존 컨테이너3개의 ID·이미지·실행 상태,
기존 볼륨의 존재와 이전 RAG 이미지를 확인했다. 검증 서비스는 정지하고 새 이미지·볼륨은 보존했다.

[공개 JSON](../data/evaluation/results/runtime-bge-docker-verification-v1.json)의 `all_checks_passed`는
문맥 불일치를 반영해 `false`다. 이미지 ID·base digest·소스/원본 해시·재생성 메타데이터·전체30문항과
[Linux 설치 목록](../data/evaluation/results/runtime-bge-linux-packages-v1.txt)을 함께 보존한다.
원본은 Git 제외 `artifacts/runtime-bge-docker-v1-*`에 있다. Windows pytest252개와 Linux의 실제
HTTP·이미지 검증을 구분한다. 작은 순차 표본의 nearest-rank 지연이며 생성·동시성 SLA나 전체 DB
백업 무결성 검증은 아니다. 워크스테이션의 다른 부하를 통제한 전후 성능 비교도 아니다.

### 격리된 재현 명령

빠른 시작의 의존성·로컬 모델을 준비한 뒤 새 이름으로 실행한다. 아래 `repro-v2`는 기존 검증 자원과
구분하는 예시다. 출력 파일은 덮어쓸 수 없으므로 이미 사용한 이름이면 새 이름을 지정한다.

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
@'
services:
  api:
    image: legacy-rag-backend:bge-int8-repro-v2
    ports: !override
      - "127.0.0.1:8015:8000"
    environment:
      LEGACY_RAG_RERANKING: bge-int8
      LEGACY_RAG_GENERATION_PROVIDER: disabled
      HF_HUB_OFFLINE: "1"
      TRANSFORMERS_OFFLINE: "1"
      HF_HUB_DISABLE_TELEMETRY: "1"
'@ | Set-Content -Encoding utf8 artifacts/runtime-bge-repro-v2-compose.yaml
$bgeComposeArgs = @('-p', 'legacy-rag-bge-repro-v2', '-f', 'compose.yaml', '-f', 'artifacts/runtime-bge-repro-v2-compose.yaml')
docker compose @bgeComposeArgs config --quiet
docker compose @bgeComposeArgs build api
docker compose @bgeComposeArgs up -d --no-build --wait --wait-timeout 90 api
.\.venv\Scripts\python.exe -X utf8 scripts/verify_runtime.py --port 8015 --index --output artifacts/runtime-bge-repro-v2-before.json
.\.venv\Scripts\python.exe -X utf8 scripts/verify_reranked_runtime.py --port 8015 --output artifacts/runtime-bge-repro-v2-parity.json
```

마지막 문맥 대조는 위 Linux 관측에서 불일치로 실패한 검사다. 출력 JSON과 exit 상태를 함께 확인한다.
그 결과와 별개로 같은 Linux 실행의 영속성은 아래처럼 **재색인 없이** 검사한다.

```powershell
docker compose @bgeComposeArgs up -d --no-build --no-deps --force-recreate --wait --wait-timeout 90 api
.\.venv\Scripts\python.exe -X utf8 scripts/verify_runtime.py --port 8015 --compare artifacts/runtime-bge-repro-v2-before.json --output artifacts/runtime-bge-repro-v2-after.json
docker compose @bgeComposeArgs stop api
```

## 준비와 구성

프로젝트 루트 `D:\BackEnd_Project\legacy-rag-backend`에서 실행한다.
Docker Desktop의 Linux 엔진과 로컬 ONNX·BGE snapshot이 필요하다. 앱은 모델을 다운로드하지 않는다.

| 항목 | 구성 |
|---|---|
| 공개 접속 | 호스트 `127.0.0.1:8001`, 컨테이너 내부 `0.0.0.0:8000` |
| 프로세스 | 비root UID/GID10001, Uvicorn worker1, reload 없음 |
| 샘플 | `data/samples`만 `/app/data/samples`에 읽기 전용 연결 |
| 모델 | 고정 revision snapshot을 `/models`에 읽기 전용 연결 |
| 재순위화 | CPU torch·BGE INT8 기본 사용, 고정 BGE snapshot을 `/reranker`에 읽기 전용 연결 |
| Chroma | `legacy-rag-runtime_runtime-chroma` named volume, 기존 `data/chroma`와 분리 |
| 파일 시스템 | 이미지 읽기 전용, `/tmp`와 전용 Chroma 볼륨만 쓰기 가능 |
| 생성 | 기본 disabled, API 키 전달 없음 |
| 로그 | JSON 요청 완료 메타데이터, Uvicorn access log 비활성화, 파일 크기 회전 |

모델 기본 경로는 `data/models/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/snapshots/e8f8c211226b894fcb81acc59f3b34ba3efd5f42/`다.
다른 경로라면 현재 PowerShell에 `LEGACY_RAG_RUNTIME_MODEL_DIR`를 지정한다.
포트 변경은 `LEGACY_RAG_RUNTIME_PORT`를 사용한다. Compose 경로와 앱 환경변수는 다르므로
호스트용 `.env.example`의 상대 경로를 컨테이너 안에 그대로 넣지 않는다.

BGE는 `data/models/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e/`를 사용한다.
다른 호스트 경로는 `LEGACY_RAG_RUNTIME_RERANKER_DIR`에 지정한다. 준비 명령은 [빠른 시작](../README.md)에 있다.
Compose 마운트는 `LEGACY_RAG_RERANKING=disabled`여도 존재하므로 해당 디렉터리를 준비해야 한다.
앱 직접 실행에서는 disabled일 때 BGE 파일·추가 패키지가 필요하지 않다.

`.dockerignore`는 기본 제외 후 앱 빌드 입력만 허용한다. 이미지에 모델·Chroma·로컬 원문·
평가 artifacts·가상환경·`.env`·Git/task 기록을 넣지 않는다. `COPY . .`는 사용하지 않는다.
`data/samples`의 보조 테스트 샘플도 읽을 수 있지만 검증 도구는 기존 공개5개만 색인한다.

## 빌드와 시작

아래 명령은 파일 준비 뒤 실제 컨테이너 검증을 위한 단계다. Docker Desktop Linux 엔진을
먼저 켠다. 기존 8000번 개발 서버를 종료할 필요는 없다.

```powershell
docker version --format '{{.Server.Version}} {{.Server.Os}}'
docker compose config --quiet
docker compose build
docker compose up -d --no-build
docker compose ps
Invoke-RestMethod http://127.0.0.1:8001/health
```

빌드는 Python base image·Debian 패키지·PyPI 의존성을 내려받을 수 있다. OpenAI 요청은 없다.
기존 모델을 이미지에 다시 내려받거나 호스트 저장소를 초기화하지 않는다.
같은 이름의 볼륨을 이미 쓰고 있다면 해당 데이터의 용도를 확인하고, 별도 검증 project 이름으로
실행한다. 이후 명령에도 같은 Compose project를 사용한다. 기존 볼륨을 삭제해 맞추지 않는다.

현재 base tag와 Python 의존성은 범위 지정이다. 검증한 이미지 ID·base digest와
[Linux 설치 목록](../data/evaluation/results/runtime-linux-packages-v1.txt)을 보존했다.
이는 설치 결과 snapshot이며 향후 빌드에 강제하는 lock은 아니다. 다시 빌드하면 의존성이
달라질 수 있으므로 실행 이미지 ID와 패키지 목록을 다음처럼 함께 기록한다.

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
docker image inspect --format '{{.Id}}' legacy-rag-backend:runtime | Out-File -Encoding utf8 artifacts/runtime-image-id.txt
docker compose exec -T api python -m pip freeze | Out-File -Encoding utf8 artifacts/runtime-linux-packages.txt
```

## 색인·검색·재생성 검증 — 생성 비용 없음

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/verify_runtime.py --index --output artifacts/runtime-docker-before.json
docker compose up -d --no-build --no-deps --force-recreate api
.\.venv\Scripts\python.exe -X utf8 scripts/verify_runtime.py --compare artifacts/runtime-docker-before.json --output artifacts/runtime-docker-after.json
```

첫 명령은 공개5개52청크를 색인한 뒤 준비 상태와 검색을 검사한다. 두 번째 검증은 **재색인
없이** 같은 검색의 순서·ID·본문·메타데이터 해시를 비교한다. 생성 `/query`를 호출하지 않는다.
일부 상위10청크의 보존을 확인하는 검사이며 전체 DB 백업 무결성 시험은 아니다.
출력 파일이 있으면 HTTP 호출 전에 중단하므로 재실행에는 새 파일명을 쓴다.
네트워크 오류를 자동 재시도하거나 검색 실패를 성공 표본에서 빼지 않는다.

지연은 같은 질문에 대한 별도 warmup 후 순차 검색10회이며 nearest-rank p50/p95를 기록한다.
색인 초기화·준비 검사·warmup 시간은 따로 저장한다. 동시성 부하나 생성 성능/SLA 지표가 아니다.
프로세스를 재생성한 직후에는 모델을 다시 로드하므로 `/ready`가 더 오래 걸릴 수 있다.

## 상태와 장애 계약

| 요청/상황 | 의미와 응답 |
|---|---|
| `GET /health` | 프로세스 liveness, `200 {status: ok}`; 모델·DB·키 준비 보장은 아님 |
| `GET /ready` | 실제 로컬 임베딩/Chroma 검색·기본 재순위화; 비어 있으면 `503 {detail: index_empty}` |
| 모델 누락·권한 오류·예기치 못한 의존성/라우트 실패 | 응답 시작 전이면 `503 {detail: service_unavailable}` |
| 잘못된 색인 입력 | `400 {detail: invalid_source}`, 원문 경로나 예외를 반사하지 않음 |
| 요청 스키마 검증 실패 | `422 {detail: invalid_request}`, 입력값·원본 validation 오류 제외 |
| 생성 timeout/공급자 오류 | 기존 `200`의 `unavailable/generation_unavailable`; 검색은 유지 |

`/ready`는 검색 준비 검사다. OpenAI 키/모델 권한·쿼터·공급자 연결은 검사하지 않는다.
Docker healthcheck는 비용과 모델 로딩을 피하기 위해 `/health`만 사용한다. 컨테이너 healthy와
검색 준비 완료를 구분한다. 400/422의 상세 응답은 이전 원시 메시지에서 위 고정 코드로 바뀌었다.

모델 누락이면 host snapshot 경로와 `onnx/model.onnx`, `tokenizer.json`,
`sentence_bert_config.json`, `1_Pooling/config.json`의 존재를 확인한다. bind source가 없을 때
빈 디렉터리를 자동 생성하지 않게 설정했다. 볼륨 권한 문제는 UID10001 쓰기 가능 여부를
확인한다. 기존 DB 삭제·공개 접속·광범위한 권한 부여로 우회하지 않는다.

예외 문자열·요청/응답 본문·질문·소스·헤더·키·query string·사용자 요청 ID는 앱 로그에 넣지 않는다.
요청 ID는 서버가 매번 생성해 `X-Request-ID`로 반환한다. 정해진 이벤트/메서드·라우트 템플릿·
HTTP 상태·소요 시간·정해진 오류 분류·질의 결과 상태만 기록한다.
`logging.json`과 `--no-access-log`를 함께 사용한다. SDK debug나 별도 프록시의 원문 로깅을
켜면 이 앱 로그 정책 바깥에서 노출될 수 있다. 이미 전송을 시작한 응답은 상태를503으로
바꿀 수 없으며 실패 시 남은 전송을 끝내고 원시 예외를 기록하지 않는다.

## 선택적 OpenAI 연결

기본 영속성 검증에는 필요 없다. 실제 생성이 필요한 경우에만 [기존 키 설정 안내](openai-generation.md)에
따라 현재 터미널에 키를 설정한 뒤 선택 override를 사용한다. 키는 빌드 인자나 파일에 넣지 않는다.

```powershell
docker compose -f compose.yaml -f compose.openai.yaml config --quiet
docker compose -f compose.yaml -f compose.openai.yaml up -d --no-build
```

OpenAI 모드는 별도 공개 collection이므로 공개5개 재색인이 필요하다. `verify_runtime.py --index`는
OpenAI 모드에서도 검색만 실행하며 생성하지 않는다. 실제 `/query`는 별도 비용·호출 범위 승인 후
실행한다. OpenAI override의 전체 `config`/환경을 출력하면 키가 보일 수 있으므로 검사는 `--quiet`로
한다. 키가 들어간 프로세스 환경은 Docker 호스트 관리자가 접근할 수 있으며 별도 secret manager를
구현한 것은 아니다. 허용 corpus/timeout/store 정책은 기존 생성 안내를 따른다.

## 운영 범위

색인 요청은 한 번에 하나만 수행하고 색인 중에는 검색·질의를 멈춘다. 같은 Chroma 경로를
여러 프로세스가 공유하지 않는다. worker1도 동기 요청의 병렬 처리를 완전히 막는 잠금은 아니다.
색인 갱신은 삭제 후 저장이라 비원자적이며 저장 단계 실패 시 자동 롤백이 없다.

종료는 `docker compose stop api` 또는 `docker compose down`을 사용한다. 볼륨 삭제 옵션은
사용하지 않는다. 백업은 서비스를 멈춘 상태에서 볼륨 전체를 일관되게 복사해야 하며 일부
SQLite 파일만 복사하지 않는다. 자동 백업·무중단 갱신은 이번 범위가 아니다.

인증·TLS·다중 사용자/프로세스·Kubernetes·클라우드는 구현하지 않았다. loopback 데모 범위다.
로컬 컨테이너 실행과 Linux 의존성 기록을 확인했다. 다중 사용자 서비스 운영이나
클라우드 배포 검증은 별도 범위다.

## 확인한 Linux 컨테이너 증거

빌드196.546초 후 비root UID/GID10001, 읽기 전용 루트·모델/샘플 마운트,
기본 생성 disabled·키 미전달·loopback8001 바인딩을 실제 컨테이너 inspect로 확인했다.
`/app/.env`, 가상환경·raw 자료·artifacts·tasks·Git 파일이 이미지에 없음을 확인했다.
원래 개발 서버와 `data/chroma`는 사용하지 않았다.

| 관측 | 결과 |
|---|---:|
| 공개5개52청크 최초 색인, 초기화 포함 | 20.459초 |
| 컨테이너 재생성 후 준비 검사 | 7.590초 |
| 재검증 시 재생성 전 warm 검색 p50/p95, n10 | 0.020초 / 0.026초 |
| 재생성 후 warm 검색 p50/p95, n10 | 0.030초 / 0.039초 |
| 실행 중 검증 볼륨 크기, WAL 포함 | 917668bytes |
| 컨테이너 재생성 후 재색인 | 없음 |
| 같은 검색의 상위10청크 ID·본문·메타데이터 | 해시 일치 |

최초 검증 도구는 정렬하지 않은 마운트 배열 비교에서 중단됐다. 이 상태에서도 재색인 없이
원래 검색 해시가 일치함을 먼저 확인했다. 이후 도구가 경로별로 정렬해 비교하고 재생성 전후
메타데이터를 즉시 보존하게 수정했다. 재검증에서는 새 컨테이너 ID·같은 이미지/볼륨·검색
해시 일치가 모두 통과했다. 앱 코드는 변경하지 않았다.

실제 컨테이너의422/404 응답과 로그에도 합성 민감 문자열이 나타나지 않는지 확인했다.
Linux 설치 버전은 Python3.11.18·FastAPI0.162.0·Chroma1.5.9·ONNX Runtime1.31.1·
Uvicorn0.54.0·OpenAI SDK2.54.0이다. Windows pytest186개와 별개로 Linux에서는 실제
HTTP/이미지/영속성 검증을 수행했으며 전체 Linux pytest 실행으로 표현하지 않는다.

[Linux 검증 결과](../data/evaluation/results/runtime-verification-v2.json)에 이미지 ID,
base digest, 설치 목록 해시, 컨테이너 전후 메타데이터, 측정 범위를 보존했다.
실행별 원본은 Git 제외 `artifacts/runtime-docker-v1/`, `runtime-docker-v2/`와
`runtime-docker-build-v1.*`다. 기존 Windows v1 결과는 변경하지 않았다.
검색은 동일 질문의 순차10회 관측이며 생성·동시성 SLA나 전체 DB 백업 검증이 아니다.
실제 생성 요청0회이고 검증 중 추가 OpenAI 비용은 없다.

## 확인한 로컬 증거

독립 Windows 프로세스에 공개5개만 복제한 새 데이터/저장소를 사용했다. 키를 넘기지 않았고
사용자의 기존 서버·모델·벡터 저장소를 변경하지 않았다. 프로세스 종료 후 새 프로세스로
같은 저장소를 열었을 때 검색 상위10개의 ID·본문·메타데이터 해시가 일치했다.

| 관측 | 결과 |
|---|---:|
| 첫 색인, 모델/저장소 초기화 포함 | 46.889초 |
| 재시작 직후 준비 검사 | 4.049초 |
| 첫 프로세스 warm 검색 p50/p95, n10 | 0.033초 / 0.056초 |
| 재시작 후 warm 검색 p50/p95, n10 | 0.057초 / 0.074초 |
| 종료 후 검증 저장소 크기 | 684196bytes |

이는 Windows 로컬 HTTP 관측값이며 Linux 컨테이너 성능이 아니다. 동일 질문의 작은 표본이고
성공한 단일 재시작 사례다. 실행별 증거는 Git 제외 `artifacts/runtime-local-v2/`에 있다.
[버전 관리 검증 결과](../data/evaluation/results/runtime-verification-v1.json)는 공개 샘플 기반
요약과 설정/코드 해시를 보존한다. 기존 [실제 생성 평가](generation-evaluation-v2.md)를
재사용하고 추가 유료 생성을 하지 않았다.

참고: [Compose 서비스 명세](https://docs.docker.com/reference/compose-file/services/),
[Dockerfile 명세](https://docs.docker.com/reference/dockerfile/),
[Uvicorn 로그 설정](https://uvicorn.dev/concepts/logging/).
