# 승인된 테스트 COBOL 묶음

이 디렉터리는 사용자가 제공하고 저장소 반입·재배포가 가능하다고 확인한 테스트용
COBOL 소스를 원문 그대로 보관한다. 실제 회사·고객 코드가 아니며, 등록 전 비밀번호·토큰·
URL·로컬 및 네트워크 경로 패턴을 검사해 일치 항목이 없음을 확인했다.

## 파일과 관계

| 파일 | 역할 | 주요 관계 |
|---|---|---|
| `DRIVER.CBL` | 단건 주문 호출 드라이버 | `ORDERMAIN` 호출 |
| `DRIVER-LOOP.CBL` | 배열 기반 반복 호출 드라이버 | `ORDERMAIN` 호출 |
| `ORDERMAIN.CBL` | 주문 입력·수수료·파일/SQL 처리 | `MEMBERREG`, `FEECALC` 호출 |
| `FEECALC.CBL` | 상품·채널·회원등급별 수수료 계산 | `ORDERMAIN`에서 호출됨 |
| `MEMBERREG.CBL` | 대화형 회원 입력과 SQL 등록 | `ORDERMAIN`에서 호출됨 |

## 사용 범위와 알려진 제한

- `evaluation/questions-v1.jsonl`의 고정 평가 대상에는 포함하지 않는다. v1의 기준선은
  `samples/` 바로 아래에 있는 합성 샘플 5개만 사용한다.
- `ORDERMAIN.CBL`이 참조하는 `ORDERREC`, `ORDERWS` copybook은 제공 묶음에 없다.
- `DRIVER.CBL`의 개별 인자 호출과 `ORDERMAIN.CBL`의 단일 그룹 인자 계약은 형태가 다르다.
- 원문의 일본어 식별 값, SQL 예제, 인터페이스 형태를 수정하지 않았다.
- 텍스트 내용은 원본과 일치하지만 저장소 등록 과정에서 줄바꿈은 정규화될 수 있다.
- 완전한 copybook과 DB 전처리 환경이 없어 컴파일·실행 가능성은 검증하지 않았다.

