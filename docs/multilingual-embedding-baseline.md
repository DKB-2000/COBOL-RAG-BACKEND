# 다국어 임베딩 비교

## 고정 조건과 모델

문맥화 구조 청크 52개, 질문 v1의 answerable 24건, 근거 주석 v1, cosine 거리 및 출처 중복 제거 규칙을 유지했다. 질문은 번역하지 않고 원래 한국어를 사용한다. API는 변경하지 않았다.

기존 Chroma ONNX `all-MiniLM-L6-v2`와 공개 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`를 비교했다. 다국어 모델은 [공식 모델 카드](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)의 384차원·128토큰·mean pooling 설정을 따른다. revision은 `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, 파일은 FP32 `onnx/model.onnx`다. [공식 ONNX 안내](https://sbert.net/docs/sentence_transformer/usage/efficiency.html#onnx)에 따라 토큰 출력에 attention mask 기반 mean pooling과 L2 정규화를 적용했다.

기존 ONNX Runtime·tokenizers로 CPU 로컬 추론한다. 공개 가중치와 tokenizer 약 480MB만 다운로드했으며 외부 추론 API, 유료 모델, 별도 worker는 사용하지 않았다. 코드·질문을 외부 추론 서비스에 전송하지 않았다. 가중치 캐시는 Git 제외 `data/models/`, 벡터 저장소는 기존 기준선과 분리된 `data/chroma/multilingual-structured-v1/`이다.

문서 임베딩 입력은 `Source path: ...\nSymbol: ...\n\n<원문>`이며 저장 본문은 원문 그대로다. 근거 주석은 임베딩 입력에 넣지 않았다. 모델·tokenizer·설정·질문·주석·소스의 SHA-256과 라이브러리 버전을 결과 JSON에 기록했다. 다운로드한 ONNX 파일의 SHA-256은 `10f7a088420252b26caf819236ca2c9d2987afd0fc06fec7553b542a5655a05a`다.

## 결과

파일 순위 지표는 전체 청크를 검색하고 출처 중복을 제거한 순위다.

| 문맥화 구조 청크의 모델 | 파일 Hit@1 | 파일 Hit@3 | 파일 Hit@5 | 파일 MRR |
|---|---:|---:|---:|---:|
| 기존 영어 MiniLM | 0.2917 | 0.8333 | 1.0000 | 0.5493 |
| 다국어 MiniLM | 0.4583 | 0.8750 | 1.0000 | 0.6611 |

파일 MRR은 +0.1118로 잠정 수치 목표 0.60을 넘었다. 파일 순위는 10건 개선, 6건 회귀, 8건 동일하다. 파일 5개뿐이므로 Hit@5는 품질 판단에 한계가 있다.

실제 청크의 필수 근거를 모두 포함한 질문 수는 다음과 같다. [근거 평가 정의와 한계](chunk-evidence-evaluation.md)는 기존과 동일하다.

| 모델 | 근거 완전 포함 @1 | @3 | @5 | @10 | 평균 원문 문자 수 @5 |
|---|---:|---:|---:|---:|---:|
| 기존 영어 MiniLM | 0/24 | 0/24 | 3/24 | 9/24 | 1,422.0 |
| 다국어 MiniLM | 5/24 | 7/24 | 9/24 | 13/24 | 1,298.5 |

다국어의 심볼 포함률 @5는 0.5417(기존 0.2500), 출처 적중률 @5는 0.7917(기존 0.5417)이다. @10 평균 원문 길이는 2,348.0자다. 문자 수는 토큰 수나 프롬프트 전체 길이가 아니며, 두 방식의 동일 k는 동일 토큰 예산 비교가 아니다.

## 개선과 회귀

근거 완전 포함 @5가 실패에서 성공으로 바뀐 질문은 8건이다:

`q002, q008, q015, q016, q019, q020, q021, q023`

기존 성공에서 실패로 회귀한 질문은 `q009, q010`이다. q007은 성공을 유지한다. q009의 LINKAGE 반환 계약은 기대 심볼을 모두 찾고도 필요한 여러 근거 단위를 모두 찾지 못했다. 심볼 포함만으로 근거 완전성을 보장할 수 없는 사례다.

다국어 상위 5개에서 정답 출처는 찾았지만 필수 근거가 부족한 질문은 다음 10건이다:

`q001, q004, q006, q009, q010, q013, q014, q017, q018, q024`

질문별 누락 심볼·근거, 검색된 청크 ID와 원문, 전체 파일 순위는 결과 JSON에 보존했다. 평균 개선을 모든 질문의 개선으로 해석하지 않는다.

## 입력 길이와 인과 해석의 한계

현재 설치된 Chroma의 기존 ONNX 구현은 256토큰을 사용하지만 다국어 모델은 공식 설정인 128토큰을 사용한다. 다국어 tokenizer 기준으로 문맥화 문서 8/52개가 잘리고 질문은 0/24개가 잘렸다. 특수 토큰을 포함한 원래 토큰 수를 기록했다.

- CUSTOMER-IMPORT: WORKING-STORAGE SECTION 159, MAIN-PROCESS 131
- DAILY-REPORT: WORKING-STORAGE SECTION 198, READ-AND-SUMMARIZE 131, WRITE-SUMMARY 129
- DATE-UTILITY: FORMAT-DATE 174
- TRANSACTION-POST: WORKING-STORAGE SECTION 275, LOAD-TRANSACTIONS 170

검색 결과에는 여전히 청크 원문 전체를 반환한다. 입력 절단은 임베딩이 보는 범위에 영향을 주며 근거 평가의 원문을 자르지는 않는다. 모델 구조·학습·tokenizer·입력 길이가 함께 바뀌었으므로 이번 개선을 언어 지원만의 효과라고 단정할 수 없다. 합성 자료 5개·질문 24개에서의 비교이며 일반적인 다국어 또는 COBOL 검색 성능을 보장하지 않는다. 답변 불가 6건의 거절 성능과 생성 답변 정확성은 측정하지 않았다.

## 재현성과 적용 판단

같은 경로에서 두 번째·세 번째 실행의 전체 결과 SHA-256은 `d62690e9434d897a5028d8462389708dba788e26206a7ce1b84d70398e816926`로 같았다. 최초 실행과 두 번째 실행의 해시는 달랐다. 별도의 새 Chroma 저장소를 만들어 확인한 결과, 파일 순위·상위 청크 ID 순서·근거 지표는 모두 같았고 저장된 소수점 6자리 score가 4곳에서 0.000001 달랐다. 새 저장소의 경로도 설정에 기록되므로 전체 바이트 동일성 대신 순위·지표 동일성을 재현성 기준으로 삼는다. 다른 환경에서의 바이트 동일성은 보장하지 않는다.

전체 pytest 58건과 Ruff 검사를 통과했다. 단위 테스트는 padding 제외 풀링, 정규화, 128토큰 절단, 16개 배치 분할, 비절단 길이 기록을 검증한다. 통합 테스트는 모델·다운로드를 대체해 네트워크 없이 고정 입력 보존, 근거 비교 결과, 입력 덮어쓰기 방지를 확인한다. 실제 모델 평가는 별도 로컬 실행으로 검증했다.

다국어 모델을 다음 검색 실험의 비교 후보로 유지한다. 파일 MRR 목표를 넘었지만 근거 완전 포함 @5가 37.5%, @10도 54.2%이므로 구조 청킹·다국어 모델의 API 전환 및 답변 생성 준비 완료로 처리하지 않는다. API는 기존 파일 단위 구성을 유지한다. 후속 [호출·선언 문맥 보강 비교](context-expansion-baseline.md)와 입력 절단 분석은 별도 결과로 보존한다.

## 재실행

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,evaluation]"
.\.venv\Scripts\python.exe -m legacy_rag.evaluation.run_multilingual_baseline
```

최초 실행은 고정 revision의 공개 파일을 내려받는다. 캐시가 준비된 뒤에는 다음처럼 네트워크 없이 실행할 수 있다.

```powershell
.\.venv\Scripts\python.exe -m legacy_rag.evaluation.run_multilingual_baseline --local-files-only
```

기본 결과는 `data/evaluation/results/multilingual-structured-baseline-v1.json`이다. `--data-root`, `--dataset-path`, `--evidence-path`, `--baseline-path`, `--chroma-path`, `--model-cache-path`, `--output-path`로 경로를 지정할 수 있다. 기존 기준선 결과는 덮어쓰지 않는다.
