# RAG 포트폴리오 — 에이전트 팀과 병렬 작업 계약

## 목표와 승인 경계

이 팀은 하네스 자체를 다시 만드는 팀이 아니다. 레거시 코드 질의에 실제 답변·출처·거절을 제공하고, 품질·한계·재현 가능한 실행을 증명하는 RAG 서비스를 완성한다. 2026-11-06까지 사용자 하루3~4시간이라는 기존 목표를 따른다.

현재 task는 `tasks/legacy-rag-portfolio-completion/`이다. 이번 승인은 프로필 정의와 Codex 작업자3개의 **읽기 전용 분석**이다. 구현·공급자 선택·유료 모델 호출·다운로드·클라우드 생성/과금·게시·Git 쓰기 승인은 포함하지 않는다. 사용자의 테스트 직접 실행 선호를 보존하며, 테스트 명령을 제공하고 실행되지 않은 검증을 완료로 기록하지 않는다.

## 구성

| 역할 | 실행 프로필 | 책임 | 구현 단계의 기본 후보 영역 |
|---|---|---|---|
| Orchestrator | 현재 Codex 세션 | 우선순위·승인·공유 계약·통합·검증·보고 | task 기록과 공유 파일 |
| 생성 | codex-main + rag-generation-expert | GenerationModel adapter·구조 출력·인용·거절·장애 | generation/** + 전용 테스트 |
| 평가 | codex-main + rag-evaluation-expert | 답변·인용·거절·성능 지표와 재현 결과 | evaluation/** + 평가 전용 테스트 |
| 운영 | codex-main + rag-runtime-expert | 컨테이너·영속성·설정·기본 관측성 | 명시된 Docker/운영 파일 + 전용 테스트 |
| 문서 | codex-main + rag-portfolio-expert | 구현 증거·실패 사례·재현·데모 | 할당된 문서/초안 |
| 검토 | codex-reviewer | 기존 산출물의 정확성·보안·회귀·과장 검토 | none |

영역은 **후보 소유권이지 쓰기 허가가 아니다.** 구현 승인을 받은 task/brief의 개별 경로가 최종 기준이다. 넓은 `tests/**`를 여러 worker에 겹치게 배정하지 않고 전용 파일을 지정한다. 기존 rag-backend-expert는 수집·검색·API 전반의 일반 역할로 유지하되, 이번 생성 역할과 같은 파일을 동시에 맡기지 않는다.

## Codex 설정 방식

프로필 정본은 `codex-agents/*.toml`의 name/description/developer_instructions다. 현재 저장소는 `.codex/agents/`의 실행 중 추가로 hot reload 문제가 발생했던 기록 때문에 수동 지시 전달 경로를 유지한다. 표준 자동 검색 경로를 새로 등록하거나 전역 설정·모델·한도를 변경하지 않는다.

Orchestrator는 호출 전에 codex-main과 도메인 프로필을 읽고 양쪽 developer_instructions를 작업 지시에 포함한다. reviewer는 해당 프로필을 읽고 기존 결과를 대상으로만 호출한다. 도메인 역할의 제약을 넘어서는 권한은 parent 세션으로부터 얻지 않는다. 이름과 write_scope 문서는 운영 계약이며 별도 OS sandbox나 완전한 보안 차단이라고 표현하지 않는다.

공식 custom agent 형식과 병렬 실행의 토큰 비용은 [OpenAI subagents 문서](https://learn.chatgpt.com/docs/agent-configuration/subagents)를 참고한다. 문서상 일반 기능과 현재 세션의 실제 가용 슬롯·기존 저장소 운영 방식을 구분한다.

## 병렬 실행 순서

현재 실제 한도는 Orchestrator 포함4슬롯이므로 작업자 최대3개다. 같은 목적/입력의 중복 worker, worker의 재귀 spawn·직접 상호 통신은 하지 않는다. 현재 모델과 reasoning 설정을 상속하고, 별도 모델·Claude·Gemini는 자동 사용하지 않는다.

1. Orchestrator가 task·공통 계약·각 brief·승인 범위를 고정한다.
2. 생성/평가/운영이 읽기 전용 현황·완료 기준·최소 작업·예상 충돌을 병렬 분석한다.
3. Orchestrator가 결과 원문을 각 workers/<role>/result.md에 보존하고 체크리스트를 검증·통합한다.
4. 구현 승인 후에는 생성 adapter 구현, 평가 runner/수동 채점 양식, 컨테이너 초안을 서로 겹치지 않는 파일로 병렬 진행할 수 있다. 실제 평가 실행은 생성 연결 이후, 실제 컨테이너 검증은 의존성·설정 확정 이후다.
5. 문서 역할은 앞 단계의 검증 근거가 나온 뒤 실행한다. 완료되지 않은 생성/배포/벤치마크를 미리 문서화하지 않는다.
6. 기존 산출물 검토 → Orchestrator 수정·재검증 → 사용자 재현 확인으로 마무리한다. 검토·문서 worker도 별도의 task별 호출 승인이 필요하다.

## 공유 파일과 충돌 처리

`api/dependencies.py`, `main.py`, `pyproject.toml`, `.env.example`, README, 공용 fixture, 모델/응답 계약은 기본적으로 Orchestrator 단일 소유다. worker는 필요 변경과 근거를 result에 patch 제안으로 남긴다. 계약 파일을 worker에 양도하려면 다른 작업을 중지하고 brief 소유권을 명시적으로 바꾼다.

평가 질문·근거 v1·기존 결과는 보존한다. 정답 주석은 오프라인 평가에만 쓰며 검색·프롬프트 선택으로 유출하지 않는다. 기존 사용자 변경과 실험 저장소를 초기화하지 않는다. 충돌 결과는 삭제하지 않고 근거를 병기해 Orchestrator가 결정한다.

실행 worker가 앱에 직접 쓰려면 target_repo·개별 write_scope·task workers_approved·별도 APPROVAL log의 네 조건을 모두 충족해야 한다. 이번 분석의 write_scope는 none이며 결과 파일도 Orchestrator가 쓴다. brief<=1200자, context<=1500자, log append-only 규칙을 유지한다.

## 완료 증거

- 생성: 승인된 실제 모델의 E2E와 인용/거절/장애 사례. 가짜 모델 통과와 구분한다.
- 평가: 실제 30문항의 판정 기준·분모·실패 및 설정 보존. ID·문자열 일치만으로 근거성을 주장하지 않는다.
- 운영: 실제 검증한 실행·영속성·오류·지연 결과. Docker 파일 작성과 빌드·배포 성공을 구분한다.
- 문서: 정상 질문·관계 질문·답변 불가 사례와 재현 절차, 작은 합성 데이터·미연결/미측정 한계 명시.
- 검토: 심각도·경로 근거·수락/보류 판단. 같은 Codex 계열의 별도 context 검토이며 교차 벤더 독립 검증은 아니다.

검색 추가 튜닝·MCP/멀티에이전트 RAG·새 DB·UI·Kubernetes·프라이빗 클라우드 구축은 이 일정의 자동 필수 범위가 아니다. 서비스 완성 후 남는 시간과 별도 승인으로만 추가한다.
