# 평가셋

고정 질문은 JSON Lines 파일로 관리한다. 파일명이나 내용이 바뀌면 평가 결과에 데이터셋 버전과 변경 사유를 함께 기록한다. 필드 형식은 상위 `data/README.md`를 따른다.

## 코드 근거 보조 주석

`evidence-v1.jsonl`은 `questions-v1.jsonl`의 answerable 24건에 대한 필수 코드 근거다. 원본 질문을 변경하지 않으며 검색·임베딩 입력으로 사용하지 않는다.

```json
{"case_id":"q001","required_evidence":[{"source_path":"samples/payroll-main.cbl","anchors":["PROGRAM-ID. PAYROLL-MAIN."]}]}
```

위는 형식 예시다. 실제 주석은 파일을 따른다. 각 단위의 모든 `anchors`가 같은 출처의 한 청크에 있어야 충족하며, 질문의 모든 단위가 충족돼야 `evidence_complete`다. 누락·중복 질문, 잘못된 출처, 원문에 없는 조각은 평가 오류로 처리한다. 근거가 변경되면 새 주석 버전을 만들고 변경 이유를 기록한다.

[평가 정의·결과·한계](../../docs/chunk-evidence-evaluation.md)를 참고한다.
