# Kubernetes OpenAI 생성 연결 검증 — 2026-11-04

로컬 단일노드 kind의 FastAPI에서 공개 COBOL을 검색한 뒤 OpenAI Responses API로
실제 답변을 생성했다. 공개3문항의 정상답변2건·근거부족거절1건을 확인했고,
응답의 인용ID·메타데이터·코드를 원문과 대조했다. **연결검증3/3 통과**이며
새30문항 정확도나 모델의 일반 성능을 측정한 결과는 아니다.

정본: [응답·인용코드·실행조건·정리 증거 JSON](../data/evaluation/results/kubernetes-openai-smoke-v1.json).

## 실제 결과

| 문항 | 확인할 동작 | 실제 결과 | HTTP /query 지연 |
|---|---|---|---:|
| q001 고객 입력 파일을 여는 문단 | 파일열기 코드와 출처 | answered: OPEN-FILES, OPEN INPUT CUSTOMER-IN | 17.684초 |
| q014 잔액계산 호출 대상 | 실제 CALL 구문과 출처 | answered: ACCOUNT-BALANCE, POST-TRANSACTIONS 인용 | 15.466초 |
| q025 DB2 고객 갱신 SQL | 없는 SQL을 생성하지 않음 | refused / insufficient_evidence, 답변·주장·출처 없음 | 13.533초 |

모든응답은 HTTP200이었다. 첫답변은 customer-import.cbl의 OPEN-FILES 청크,
두번째답변은 transaction-post.cbl의 실제 CALL 청크가 뒷받침한다.
공개5개에는 대응하는 DB2 SQL이 없다. 의미판정은 Codex의1차 원문대조이며 독립사람검수는 아니다.
지연은 BGE검색·OpenAI생성·응답직렬화를 포함한 순차3건의 개별값이고 SLA가 아니다.

## 실행조건과 관측 범위

- kind0.33.0 / Kubernetes1.36.4, 단일노드·API컨테이너1개·UID10001·재시작0.
- 기존 검증이미지·모델을 재사용했다. 앱소스45개 해시일치, 공개합성5개/52청크.
- OpenAI SDK2.54.0, 설정모델 gpt-6-luna, BGE INT8, 출력1000토큰,
  공급자timeout30초·SDK재시도0. 공개3문항은 각1회만 요청했다.
- 실제공급자 model ID·사용토큰·청구액은 이번 API응답에 노출하지 않아 미측정이다.
- 공개전용DB는 기존PVC 하위 openai-public-v1이다. 일반검색DB와 구분한다.
- Secret은 환경변수의 키를 stdin으로 전달해 만들며 키를 argv·파일·Git에 기록하지 않는다.
- 실제 /query 로그3개와 응답의 요청ID를 대조했다. 원응답은 검수 전에 저장했다.
- 문맥은 별도 /search로 재구성했으며 실제 공급자 요청본문을 가로채지 않았다.
  Windows기준 문맥순서는3/3에서 달랐다. 기존Windows의22/24 생성점수를 이환경에 적용하지 않는다.
- 관련 OpenAI/Secret 오프라인테스트42개 통과. 최종 Windows 전체테스트255개도 통과했다. Linux 전체pytest는 이번에 실행하지 않았다.

준비중 진단JSON파싱 실패가 있었고 stdout/stderr를 분리한 재시도에서 통과했다.
ONNX 경고와 최초실패 기록은 비공개 artifacts에 보존했다. 앱생성코드 변경은 없었다.
Ollama 테스트는 중지상태를 유지했고 로컬추론·새모델다운로드는 하지 않았다.

## 재현 순서

먼저 [기본 Kubernetes 실습](runtime.md#kubernetes-로컬-실습)의 전용cluster·kubeconfig·
로컬모델·API이미지·PVC를 준비한다. 기존PVC나DB를 삭제하지 않는다.
아래명령은 저장소루트 PowerShell 기준이다. 실제생성단계는 유료이므로 모델·문항·
최대호출수를 확인해 명시승인 후 실행하며 오류시 자동재시도하지 않는다.

```powershell
$lab = @('--kubeconfig', (Join-Path $PWD 'artifacts/k8s-lab-v1.kubeconfig'), '--context', 'kind-legacy-rag-lab')
docker start legacy-rag-lab-control-plane
kubectl @lab wait --for=condition=Ready node/legacy-rag-lab-control-plane --timeout=120s
# 기존 전용실습 Pod가 0개인지 먼저 확인한다.
kubectl @lab -n legacy-rag-lab get pods
# OPENAI_API_KEY는 프로세스/사용자 환경변수에 설정한다. 채팅이나 명령인자로 넣지 않는다.
.\.venv\Scripts\python.exe scripts/prepare_k8s_openai_secret.py --execute
kubectl @lab apply --dry-run=server -k deploy/kubernetes-openai
kubectl @lab apply -k deploy/kubernetes-openai
kubectl @lab -n legacy-rag-lab get pods
```

Pod가 Running이 된 뒤 API의 /health 수신을 먼저 확인한다. Running만으로 API가
포트를 열었다고 판단하지 않는다. 최초 공개색인 전에는 Ready가 아니어도 정상이다.
다른터미널에서 특정Pod로 loopback포트포워딩을 실행한다.

```powershell
$lab = @('--kubeconfig', (Join-Path $PWD 'artifacts/k8s-lab-v1.kubeconfig'), '--context', 'kind-legacy-rag-lab')
$pod = (kubectl @lab -n legacy-rag-lab get pod -l app=legacy-rag-api -o json | ConvertFrom-Json).items[0].metadata.name
kubectl @lab -n legacy-rag-lab exec $pod -c api -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status)"
kubectl @lab -n legacy-rag-lab port-forward --address 127.0.0.1 "pod/$pod" 8018:8000
```

공개5파일 색인은 [기존 색인절차](runtime.md)를 같은주소의 /documents/index로 실행한다.
/ready가 ready를 반환하는지 확인한뒤 해당 공개DB의 초기화표식을 기록한다.
아래는 모델요청을 하지 않는다.

```powershell
$namesJson = .\.venv\Scripts\python.exe -X utf8 -c "import json; from legacy_rag.api.public_corpus import PUBLIC_SOURCE_HASHES; print(json.dumps(list(PUBLIC_SOURCE_HASHES)))"
$paths = $namesJson | ConvertFrom-Json
$body = @{ source_paths = @($paths); rebuild = $false } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8018/documents/index -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 300
Invoke-RestMethod http://127.0.0.1:8018/ready -TimeoutSec 300
kubectl @lab -n legacy-rag-lab exec deployment/rag-api -c api -- python -c "from pathlib import Path; Path('/var/lib/legacy-rag/chroma/openai-public-v1/.lab-initialized').write_text('public-v1-indexed-5-52',encoding='utf-8')"
kubectl @lab -n legacy-rag-lab rollout status deployment/rag-api --timeout=180s
```

실제생성은 q001/q014/q025의 질문을 /query에 limit10으로 각1회 전송한다.
[질문원문](../data/evaluation/questions-v1.jsonl)과 위 결과표를 사용한다.
응답전체를 검수전에 저장하고 claims[].chunk_ids와 sources를 공개원문에 대조한다.
HTTP200만으로 정답이나 올바른거절을 인정하지 않는다.

## 종료와 데이터보존

포트포워딩을 종료한뒤 전용실습자원만 정리한다.

```powershell
kubectl @lab -n legacy-rag-lab scale deployment/rag-api --replicas=0
kubectl @lab -n legacy-rag-lab wait --for=delete pod -l app=legacy-rag-api --timeout=120s
kubectl @lab -n legacy-rag-lab delete secret rag-openai-credentials --ignore-not-found=true
docker stop legacy-rag-lab-control-plane
```

이번실행은 Pod0·Secret삭제·노드정지를 확인했고 3회정지관측을 보존했다.
원래DB6파일·타컨테이너4개·볼륨목록·기본kubeconfig는 불변이며 공개색인52행·PVC·모델도 보존했다.
정리 직후의 정지확인은 위 시각의 관측값이다. 후속확인에서 노드가 06:13:40 UTC에
다시 시작된 것을 관측했다. 원인은 미확정이며 restart policy는 변경하지 않았다.
이때 API replicas0·Pod0·OpenAI Secret 부재를 확인했고 추가생성은 없었다.
전용노드만 다시 정지하고 RunningFalse를3회 확인했다. 노드 재기동을
Kubernetes 자동장애복구 성과로 해석하지 않는다. 후속관측도 결과JSON에 보존했다.

## Kubernetes와 외부접속

현재흐름은 `내PC → 127.0.0.1:8018 포트포워딩 → API Pod → 검색 → OpenAI API`다.
Service는 ClusterIP이며 외부IP·공개LoadBalancer·Ingress는 설정하지 않았다.
OpenAI로 나가는 HTTPS통신과 다른사람이 내API로 들어오는 인터넷접속은 별개다.
이번검증완료로 외부접속이 열리지 않는다.

Deployment는 원하는Pod 실행개수·교체를 관리하고 Service는 Pod교체에도 사용할
클러스터내부 접속점을 제공한다. PVC는 Pod교체와 독립적으로 검색DB를 보존한다.
현재Chroma 단일소유 때문에 replicas1/Recreate를 유지한다. 다중노드·고가용성검증이 아니며,
외부접속은 실제배포환경에 맞는 진입점·라우팅·방화벽설정을 추가하는 별도단계다.

참고: [Kubernetes 개요](https://kubernetes.io/docs/concepts/overview/),
[Service](https://kubernetes.io/docs/concepts/services-networking/service/),
[port-forward](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/).
