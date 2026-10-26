# 데이터 규약

이 폴더에는 공개 라이선스가 확인된 코드 또는 직접 만든 합성 코드만 둔다. 사내 저장소, 고객 코드, 자격 증명, 개인정보가 포함된 로그는 반입하지 않는다.

## 디렉터리

- `samples/`: Git에 포함 가능한 소형 공개·합성 샘플과 승인된 테스트 샘플
- `evaluation/`: 질문과 정답 근거를 담은 버전 관리 평가셋
- `raw/`: 로컬 원본 데이터, Git 제외
- `chroma/`: 로컬 Chroma 영속 데이터, Git 제외

## 평가 질문 형식

평가셋은 JSON Lines로 관리하며 한 줄은 다음 필드를 가진다.

```json
{"id":"q001","question":"질문","expected_sources":["samples/example.cbl"],"expected_symbols":["READ-CUSTOMER"],"answerable":true,"tags":["cobol","file-io"]}
```

- `id`는 데이터셋 안에서 고유하고 변경하지 않는다.
- `expected_sources`는 데이터 루트 기준 상대 경로다.
- 답변할 수 없는 질문은 `answerable: false`로 명시한다.
- 평가셋 변경은 버전 또는 변경 사유를 결과와 함께 기록한다.

## 평가 데이터 v1

`evaluation/questions-v1.jsonl`은 합성 COBOL 5개를 대상으로 고정한 첫 평가셋이다.
총 30개 질문 중 24개는 소스에서 답을 확인할 수 있고, 6개는 근거가 없어 답변을
거절해야 한다. v1의 질문과 기대 근거는 검색 기준선이 만들어질 때까지 내용 변경 없이
유지하며, 수정이 필요하면 새 버전 파일을 만든다.

| 파일 | 주요 검증 주제 | 호출 관계 |
|---|---|---|
| `samples/customer-import.cbl` | 순차 파일 I/O, EOF 반복, 고객 검증, 오류 분기 | 없음 |
| `samples/account-balance.cbl` | LINKAGE 데이터, 입출금 분기, 잔액·보류 규칙 | `TRANSACTION-POST`에서 호출됨 |
| `samples/transaction-post.cbl` | OCCURS 테이블, `PERFORM VARYING`, 결과 코드 처리 | `ACCOUNT-BALANCE` 호출 |
| `samples/daily-report.cbl` | 파일 집계, 상태 분기, 보고서 문자열 | `DATE-UTILITY` 호출 |
| `samples/date-utility.cbl` | 날짜 구조, 부분 참조, 유효성 검사 | `DAILY-REPORT`에서 호출됨 |

### 출처와 라이선스

샘플 5개와 평가 질문은 이 프로젝트를 위해 직접 작성한 합성 자료다. 실제 회사·고객
시스템의 코드나 데이터에서 복사하지 않았으며 특정 개인을 나타내는 값도 포함하지 않는다.
프로젝트 저장소와 동일한 라이선스로 배포한다. 파일명과 업무 규칙은 RAG 검색 검증을 위한
가상의 예시이며 실제 금융 업무 규칙으로 사용하면 안 된다.

### 합성 규칙

- 각 프로그램은 하나 이상의 독립적인 검색 주제를 가진다.
- 문단명과 데이터명은 질문의 기대 심볼을 사람이 소스에서 직접 찾을 수 있게 명시적으로 쓴다.
- 파일 간 관계는 정적 `CALL` 문으로 표현하고 호출 대상의 `PROGRAM-ID`와 이름을 맞춘다.
- 의도적으로 DB2, CICS, MQ, XML, 자격 증명 관련 구현은 넣지 않아 답변 불가 사례로 사용한다.
- 평가 질문을 위한 숨은 주석이나 정답 문자열은 소스에 추가하지 않는다.

## P1 로더 입력 사례

P1의 `.cbl` 로더는 다음 사례를 타입과 테스트로 고정한다.

| 사례 | 입력 | 기대 동작 |
|---|---|---|
| 정상 | `samples/customer-import.cbl` | UTF-8 텍스트를 읽고 상대 `source_path`와 `language=cobol`을 반환 |
| 빈 파일 | 크기가 0인 `.cbl` fixture | `ValueError`로 거절 |
| 잘못된 확장자 | 동일 내용의 `.txt` fixture | 지원하지 않는 확장자 오류로 거절 |
| 중복 입력 | 같은 경로를 한 요청에 두 번 전달 | 해석된 경로 기준으로 한 번만 로드하고 최초 입력 순서를 유지 |

fixture는 P1 테스트 안에서 생성하며 `samples/`에는 평가 대상 5개만 유지한다.

## 보조 테스트 샘플

`samples/authorized-test/`에는 사용자가 저장소 반입·재배포 가능하다고 확인한 테스트용
COBOL 5개를 별도로 보관한다. 이 묶음은 더 현실적인 `CALL`, embedded SQL, copybook 참조,
일본어 업무 문자열 사례를 제공하지만 `questions-v1.jsonl`의 고정 평가 대상은 아니다.
출처, 파일 관계, 누락 의존성과 검증 범위는 해당 디렉터리의 `README.md`에 기록한다.
