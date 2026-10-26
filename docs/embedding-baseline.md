# P2 임베딩 기준선 결정

## 선택

P2의 최초 파일 단위 검색 기준선은 Chroma `DefaultEmbeddingFunction`이 제공하는
ONNX `all-MiniLM-L6-v2`와 cosine 거리를 사용한다. 기준 환경은 Chroma 1.5.9다.

## 선택 근거

| 기준 | 결정 내용 |
|---|---|
| 비용 | API 호출 비용이 없는 로컬 모델이다. 최초 모델 다운로드 비용과 로컬 CPU·디스크만 필요하다. |
| 오프라인 | 최초 다운로드 후 Chroma 캐시의 ONNX 모델로 오프라인 실행할 수 있다. |
| 차원 | 384차원 dense vector를 생성한다. |
| 재현성 | 모델명, Chroma 버전, cosine 거리, 모델 아카이브 SHA-256을 기준선 설정으로 기록한다. |

설치된 Chroma 1.5.9의 모델 아카이브 SHA-256은
`913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3`이다.
Chroma 공식 문서는 기본 임베딩이 ONNX Runtime의 `all-MiniLM-L6-v2`임을 설명하고,
모델 카드는 384차원과 Apache-2.0 라이선스를 명시한다.

- Chroma embedding functions: https://docs.trychroma.com/guides/embeddings
- Chroma collection configuration: https://docs.trychroma.com/reference/python
- Model card: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2

## 고정 설정

- embedding function: `chromadb.utils.embedding_functions.DefaultEmbeddingFunction`
- model: `all-MiniLM-L6-v2` ONNX
- distance: `cosine`
- model max tokens: 256
- baseline Chroma version: 1.5.9
- corpus: `data/samples/` 바로 아래 합성 COBOL 5개
- chunking: 파일 하나당 청크 하나

## 알려진 한계

- 모델이 영어 중심이라 한국어 평가 질문과 영어 COBOL 식별자 사이의 교차 언어 검색이 약할 수 있다.
- 256토큰을 넘는 파일 단위 청크는 모델 입력에서 잘리므로 파일 후반의 근거가 손실될 수 있다.
- 이 선택은 최종 모델 선정이 아니라 실패 원인을 측정하기 위한 최초 기준선이다.
- 기준선이 낮으면 결과를 보존한 뒤 다국어 임베딩과 구조 기반 청킹을 각각 분리해 비교한다.

## 보류한 대안

다국어 Sentence Transformers 계열은 한국어 질의에 유리할 가능성이 있지만 별도 의존성,
모델 다운로드, 모델별 입력 규약을 추가한다. 파일 단위 기본선 결과가 나오기 전에는 도입하지 않는다.
