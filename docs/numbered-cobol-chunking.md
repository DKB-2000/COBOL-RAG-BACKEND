# 행 번호 COBOL 구조 청킹

2026-10-27, 행 번호가 붙은 고정 형식 입력의 구조 인식을 보완했다.
기존 청커는 제목 앞의 공백7칸을 요구해 `000100 IDENTIFICATION DIVISION.`을
구조 경계로 인식하지 못했다. 새 공개 합성 fixture는 수정 전1개, 수정 후8개 청크로 나뉜다.

## 변경과 보존

1~6열이 숫자/공백이고7열이 공백인 줄은 **경계 판별용 문자열에서만** 번호 영역을
공백으로 바꾸고 코드 영역을72열까지 읽는다. 원문을 자르거나 번호를 삭제해 저장하지 않는다.
73열 이후 식별 영역도 원본 청크에는 남는다. 주석·페이지·연속·디버그 표시가 있는 줄을
새 구조 제목으로 취급하지 않는다. 이는 [IBM의 참조 형식 설명](https://www.ibm.com/docs/en/cobol-zos/6.4.0?topic=structure-reference-format)을 참고한 제한적 경계 처리다.

문서 본문에서 계산한 원래 offset으로 청크를 나누므로 청크를 순서대로 합치면
입력 `SourceDocument.text`와 정확히 같다. 경로·언어·내용 해시·인덱스와 결정적 ID 생성
규칙은 유지한다. 로더의 기존 줄바꿈 정규화 동작은 변경하지 않았다.

새 자료는 직접 작성한 `tests/fixtures/numbered-structure.cbl`이며 회사·사용자 원문에서
복사하지 않았다. 기존 공개5개나 OpenAI 허용 목록에 추가하지 않았다.

## 회귀와 검증

| 확인 | 결과 |
|---|---|
| 합성 번호 입력 | 1청크 → 8청크, DIVISION/SECTION/문단 인식 |
| 주석·페이지·연속·디버그 표시 | 별도 문단으로 잘못 분리하지 않음 |
| 번호/공백 혼용·73열 식별자·LF/CRLF | 원문 보존과 경계 인식 통과 |
| 기존 공개5개 | 52청크의 ID·심볼·본문·메타데이터 전체 동일 |
| 기존 공개30문항 | 수정 전후 상위10개·선택 문맥 ID/문자 수 모두 동일 |
| 공개 근거 문맥 | 답변 가능24건 중16건으로 동일, 최대10청크/4000자 |
| 전체 테스트 | **174 passed in 6.89s**, 변경 파일 Ruff 통과 |

새 테스트7건이 수정 전에 실패하는 것을 확인한 뒤 수정했다. 이후 관련19건과 전체174건이
통과했다. 공개 회귀는 같은 identifier-aware 임베딩·캐시된 로컬 ONNX·독립 Ephemeral Chroma로
비교했으며 기존 영속 색인을 갱신하지 않았다. 질문30건의 검색만 수행했고 생성 호출은0회다.
원본5개와 질문/근거, 기존 생성v1/v2 결과는 보존했다.

[회귀 결과 JSON](../data/evaluation/results/numbered-chunking-regression-v1.json)에
공개 입력·청커/fixture 해시·전후 청크 해시·30문항 검색 결과를 남겼다.
무료 근거16/24는 [실제 생성 평가](generation-evaluation-v2.md)의 인용 충족15/24와 구분한다.

직접 확인할 때는 프로젝트 루트에서 다음을 실행한다. 모델 다운로드·유료 API 없이 동작한다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_numbered_chunker.py tests/unit/test_structured_chunker.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

## 적용 범위와 한계

기존 정규식이 처리하는8열 시작 제목과 숫자/공백 번호 영역을 지원한다. 일반 COBOL parser,
영문 sequence label, 임의 위치의 free-format 제목, continuation 결합, copybook 전개,
SQL 전처리·컴파일 지원을 추가하지 않았다. 디버그 표시 줄의 활성화 여부도 해석하지 않는다.
중첩 프로그램의 문서 심볼은 여전히 로더가 찾은 첫 PROGRAM-ID다.

번호 소스를 이미 색인했다면 재시작 후 해당 자료를 다시 색인해야 새 경계가 반영된다.
청크가 바뀌므로 이전 번호 소스의 청크 ID와 질의 결과는 달라질 수 있다. 공개5개는 전후
청크가 동일하다. 새 합성 fixture나 로컬 전용 자료를 OpenAI 공개 collection에 넣지 않는다.

사용자 로컬 자료의 전후 평가와 회귀·한계는 Git 제외
`data/raw/local-evaluation/results/numbered-chunking-comparison.md`에만 기록했다.
공개 결과에 원문·질문·답안·파일별 결과를 섞지 않았다. 이번 호환성 수정과 검증을 완료하고
추가 검색 튜닝은 종료한다. 다음 단계는 Docker 등 실행 재현과 기본 운영 검증이다.
