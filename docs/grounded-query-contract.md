# P4 — 검색 연결과 근거 기반 질의 계약

## 구현 범위와 상태

2026-10-14, 추가 검색 튜닝을 중단하고 P4 개발을 시작했다. 일반 다국어 구조·문맥화 검색을 서비스에 연결하고 생성 port·프롬프트·문맥·출처·거절 계약을 구현했다. 외부 생성 공급자는 추가하지 않았고 유료 추론·새 모델 다운로드·worker 호출도 하지 않았다.

이 문서의 완료는 **모델 없는 계약 구현과 검색 연결**에 한정된다. 실제 모델의 답변 정확성·인용 근거성·거절 정확도, P4 전체 완료 및 P5 릴리스 게이트는 아직 확인하지 않았다.

## 고정 검색 설정

- `cobol-structure-v1`, 임베딩 입력은 상대 경로·심볼·원문이다.
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
- 로컬 CPU, 128토큰 접두 입력, masked mean·L2 정규화, cosine, 384차원
- 창 평균 및 호출·선언 확장은 사용하지 않는다.
- 기본 저장소 `data/chroma/api-v2-multilingual/`, collection `legacy-rag-api-v2-multilingual`
- 기존 file-v1과 모든 실험 저장소·결과는 보존한다. 새 API collection에는 재색인이 필요하다. 기존 경로를 환경 변수로 지정해도 collection 이름은 새 이름이므로 기존 벡터를 섞지 않는다.

일반 encoder와 문맥화 입력은 `retrieval`에서 API·평가가 공유한다. `evaluation`의 기존 import 경로는 재노출해 비교 실험과 테스트를 유지한다. 구조 색인은 모든 문서의 임베딩을 먼저 계산하고 저장할 때 원문·메타데이터·ID를 보존한다. encoder 실패 전에는 기존 벡터를 지우지 않는다. Chroma 삭제·upsert는 원자적 트랜잭션이 아니므로 저장 단계 장애의 자동 롤백은 이 범위에 없다.

## 문맥과 생성 port

`/query`는 기본 10개, 요청 시 1~10개를 검색한다. 검색 순서와 첫 ID를 유지하며 중복 ID·빈 본문을 제외한다. 원문 길이 합계 4000자 안에서 청크 전체만 선택한다. 예산을 초과하는 청크는 건너뛰고 다음 청크를 검사한다. 원문을 잘라 근거의 일부를 유효한 청크로 제시하지 않는다.

4000자는 **원문 문자 예산**이다. 시스템 지시, 질문, 경로·심볼·JSON 직렬화 길이는 추가되며 모델 토큰 상한이나 비용 상한이 아니다. 실제 공급자 연결 시 전체 요청의 토큰 예산·타임아웃을 별도로 정해야 한다. 구조 청크 하나가 4000자를 넘으면 문맥에서 빠질 수 있다.

`GenerationModel.generate(GenerationRequest) -> GeneratedAnswer`를 adapter 경계로 사용한다. 요청은 시스템 지시와 질문·문맥 JSON을 분리한다. 코드·경로·질문은 지시가 아닌 비신뢰 데이터로 취급하도록 요구하고, 부족한 근거와 충돌은 거절하도록 명시한다. 이 프롬프트만으로 prompt injection 방어 또는 의미적 정확성을 보장하지 않는다.

모델 출력은 자유 형식 답변이 아니라 주장 목록이다. 각 주장에는 `text`, `chunk_ids`가 있다. 서비스는 빈 답변·빈 주장, 거절과 답변의 혼합을 허용하지 않으며, 각 주장의 ID가 **실제 모델에 제공한 문맥**에 있는지 검증한다. 미인용 주장이나 문맥에서 빠진 청크 인용은 답변 전체를 거절한다. 출력 `answer`는 검증된 주장에 `[chunk_id]`를 붙여 조립하고 `sources`는 인용된 문맥만 검색 순서로 반환한다.

ID 검증은 출처 연결의 구조적 검사다. 주장 내용이 실제 코드에서 뒷받침되는지, 한 `text`에 숨은 여러 주장이 모두 맞는지는 자동으로 판정하지 않는다. 검색 점수 역시 확률·신뢰도가 아니다. 의미적 근거성과 실제 답변 불가 6건의 거절은 모델 연결 후 평가해야 한다.

## HTTP 계약

`POST /query`, 요청 `{"query":"질문", "limit":10}`. 빈/공백 질문과 범위 밖 limit은 HTTP 422다. 응답은 HTTP 200에 명시적 결과 상태를 포함한다.

| status | reason | 동작 |
|---|---|---|
| `answered` | `null` | 검증된 주장·인용 표시 답변·출처 반환 |
| `refused` | `no_evidence` | 사용 가능한 문맥 없음, 생성 모델 미호출 |
| `refused` | `insufficient_evidence` | 모델이 근거 부족 판단 |
| `refused` | `conflicting_evidence` | 모델이 근거 충돌 판단 |
| `refused` | `invalid_citations` | 주장에 출처 없거나 문맥 밖 ID |
| `unavailable` | `generation_unavailable` | 기본 모델 미연결·모델 장애·잘못된 모델 출력 |

답변 외 상태에서는 `answer=null`, `claims=[]`, `sources=[]`다. 출처는 `chunk_id`, 상대 `source_path`, `language`, `symbol`, `chunk_index`, `score`를 가진다. 응답으로 전체 프롬프트나 모델 예외 문자열을 내보내지 않으며 서비스에서 입력·예외를 로깅하지 않는다. 검색/색인 자체 장애는 별개의 경계로서 이번 생성 장애 계약에 포함하지 않는다.

## 검증 결과

- 가짜 모델 단위·HTTP 통합 테스트: 정상 답변, 무근거 미호출, 부족·충돌 거절, 미인용·문맥 밖 ID, 예산에서 빠진 청크 인용, 비정상 출력, 모델 미연결·장애, 오류 정보 비노출, `/search` 유지, OpenAPI.
- 실제 캐시 모델/Chroma/API: 고정 5개 파일 → 52청크, 24개 answerable 질문의 API top10 ID 순서·본문이 기존 다국어 결과와 모두 일치.
- 전체 52개 청크 순위를 출처 중복 제거한 파일 Hit@5=1.0, MRR=0.6611111111. 이것은 top5 청크 또는 답변 정확도가 아니다.
- 원문 4000자/최대10개 문맥의 필수 근거 완전 포함 13/24(54.17%), 평균 원문 2335.96자. 정답 근거 주석은 **오프라인 검증에서만** 사용하고 API 선택·프롬프트에는 전달하지 않는다.
- 30개 질문에서 모델 미연결 상태를 확인했으며 실제 답변·거절 정확도는 평가하지 않았다.
- 기존 질문·주석·소스·모델 해시와 부모 결과 SHA-256 `d62690e9434d897a5028d8462389708dba788e26206a7ce1b84d70398e816926`를 검증·보존했다.

검증 스크립트와 결과는 `tasks/legacy-rag-p4-grounded-query/artifacts/verify_api_retrieval.py`, `api-retrieval-verification.json`에 있다. 재실행은 프로젝트 루트에서 다음과 같다. 매 실행 새로운 Git 제외 진단 저장소를 만들며 기존 저장소는 삭제하지 않는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 ..\tasks\legacy-rag-p4-grounded-query\artifacts\verify_api_retrieval.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

## 다음 단계

실제 생성 모델·실행 위치·비용·데이터 전송 범위를 사용자와 확정하고 필요한 호출 승인을 받은 뒤 adapter를 연결한다. 실제 답변·인용 근거성·답변 불가 질문을 평가한 다음 P4 전체 완료 여부를 판단한다. 별도의 검색 개선 실험을 선행 조건으로 다시 추가하지 않는다.
