# oura-mcp

[![PyPI](https://img.shields.io/pypi/v/mcp-oura?label=PyPI)](https://pypi.org/project/mcp-oura/)
[![Glama score](https://glama.ai/mcp/servers/proscar87/oura-mcp/badges/score.svg)](https://glama.ai/mcp/servers/proscar87/oura-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](https://github.com/proscar87/oura-mcp/blob/main/README.md) | [简体中文](https://github.com/proscar87/oura-mcp/blob/main/README_zh_CN.md) | 한국어 | [Español](https://github.com/proscar87/oura-mcp/blob/main/README_es.md)

<!-- Glama 배지는 스크린샷이 아니라 실시간입니다. 그 독립적인 인덱스가 오늘 이
     서버에 매긴 점수를 그대로 보여줍니다. 올라가기만 하는 배지는 장식이고,
     내려갈 수도 있는 배지가 증거입니다. -->

[Oura](https://ouraring.com) v2 API를 [MCP](https://modelcontextprotocol.io)
서버로 만든 것입니다. 19개 컬렉션 전부, 세 개의 도구, MCP SDK 외에는 의존성이
없습니다.

### 로컬 기준 하루치 심박수는 2 페이지에 걸친 1,231개의 표본입니다

Oura의 `next_token`을 따라가지 않는 클라이언트는 그중 **1,000개, 즉 81%를
돌려받습니다. 완전해 보이고, 그렇지 않다고 알려주는 것은 아무것도 없습니다.**
2026년 8월 9일에 실제 API를 상대로 측정했습니다. 한 사람, 반지 하나, 24시간.

**어떤 Oura MCP 서버든, 이 서버까지 포함해서 적용해 볼 시험:** `next_token`을,
혹은 `cursor`나 `limit`을 도구 파라미터로 받습니까? 받는다면 페이지네이션은
모델의 몫이 되고, 다시 물어보는 것을 잊은 모델은 부분적인 데이터 위에서 확신에 찬
답을 만들어냅니다. 이 서버는 반환하기 전에 끝까지 페이지를 넘기고, 몇 페이지가
걸렸는지 알려줍니다.

이것은 Oura가 아무 말 없이 덜 주는 **네 가지** 방식 중 하나입니다. 네 가지 모두
아래에서 측정했고, 네 가지 모두 여기서 바로잡았습니다.

### 설치

[최신 릴리스](https://github.com/proscar87/oura-mcp/releases/latest)에서
**`oura-mcp.mcpb`** 를 내려받아 더블클릭하세요. 나머지는 Claude Desktop이 합니다.
터미널도, Python도, Node도 필요 없습니다. 설치 직후에는 Oura의 공식 샘플 데이터로
동작하며, 모든 샘플 응답이 그 사실을 밝히기 때문에 어떤 것도 당신의 실제 수면인
척할 수 없습니다.

명령줄이 더 편하신가요? `uvx --from mcp-oura oura-mcp`.

기기에 Python을 아예 두고 싶지 않으신가요?

```
docker run -i --rm -e OURA_SANDBOX=1 ghcr.io/proscar87/oura-mcp
```

`-i`는 선택 사항이 아닙니다. MCP 서버는 포트가 아니라 stdin과 stdout으로
말합니다. 이 옵션이 없으면 컨테이너에 stdin이 없고, 핸드셰이크는 영영 도착하지
않으며, 클라이언트는 서버가 뜨지 않는다고 보고합니다.

---

## 측정된 문제

Oura는 요청한 것을 줄 수 없을 때 오류를 돌려주지 않습니다. 올바른 응답의 모양을 한
다른 것을 돌려줍니다. 2026년 8월 9일 실제 API를 상대로 측정하면서 찾아낸 네 가지는
다음과 같습니다.

### 1. 페이지네이션을 건너뛰면 일부만 받습니다

```json
{ "data": [ ... ], "next_token": "eyJ0eXAiOi..." }
```

`next_token`이 돌아왔는데 따라가지 않으면 첫 페이지만 받게 되고, **아무것도
경고해 주지 않습니다**. 로컬 기준 하루치 `heartrate`는 — 한 사람, 반지 하나,
24시간 — **2 페이지에 걸친 1,231개의 표본**입니다. 페이지를 넘기지 않는
클라이언트는 1,231개 중 1,000개를 받습니다. 81%, 완전해 보입니다. 한 달이면
~37,000개입니다.

### 2. 하루만 요청했더니 0건이 돌아왔습니다

`end_date`는 **컬렉션마다 동작이 같지 않습니다**:

| 요청한 마지막 날을 제외 | 포함 |
|---|---|
| `daily_activity`, `sleep`, `workout` | `daily_sleep`, `daily_readiness`, `daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`, `sleep_time` |

게다가 **`workout`은 UTC 날짜로 걸러내면서 `day`는 현지 시각으로 보고합니다**.
`-06:00`에서 7월 16–18일을 요청하자 15일과 16일 기록이 돌아왔습니다. 요청한
시작일보다 *앞선* 날짜입니다.

여기서 범위는 언제나 양쪽 끝을 포함합니다. 양옆으로 이틀씩 더 요청한 뒤 잘라내는데,
이렇게 하면 특정 컬렉션이 어느 쪽으로 동작하든 옳고, Oura가 그 동작을 바꾸더라도
계속 옳습니다.

### 3. `latest=true`는 해당되지 않는 곳에서 무시됩니다

`heartrate`와 `ring_battery_level`만 이것을 지킵니다. 나머지 열일곱 개에서 Oura는
오류를 내지 않습니다. **컬렉션 전체를 돌려줍니다.** 가장 최근 기록 하나를
요청했는데 열 건을 받고, 그것이 하나라고 믿게 됩니다. 여기서는 요청이 나가기 전에
거절됩니다.

### 4. 존재하지 않는 필드는 조용히 무시됩니다

`fields=does_not_exist`는 **완전한** 레코드를 돌려줍니다. 프로젝션이 아예 일어나지
않습니다. 그리고 `fields=score,does_not_exist`는 멀쩡한 쪽은 적용하고 잘못된 쪽은
한마디도 없이 버립니다. 여기서는 한 번도 나타나지 않은 필드를 `ignored_fields`로
알려줍니다.

**패턴은 언제나 같습니다.** 하나를 요청하면 다른 것이 오고, 아무것도 경고하지
않습니다. 이 패키지가 조용히 덜 주느니 차라리 소리를 지르는 쪽을 택하는 이유가
바로 이것입니다.

## 설치 방법

### 자격 증명 없이 시험해 보기

```bash
pip install mcp-oura
OURA_SANDBOX=1 oura-mcp --check
```

샌드박스는 공식입니다. Oura의 OpenAPI 명세에 34개의 미러 라우트와 함께 들어 있고,
인증 없이 합성 데이터를 제공합니다. 19개 컬렉션 중 18개가 거기서 동작합니다.
`personal_info`는 안 되는데, 이메일과 나이, 체중, 키를 돌려주는 바로 그
컬렉션이라는 점을 생각하면 납득이 갑니다.

이 순서가 옳습니다. 먼저 서버가 동작하는 것을 보고 데이터의 모양을 익힌 다음,
자격 증명을 받으러 가는 것입니다.

### 내 데이터로 쓰기

**Oura는 2025년 12월에 Personal Access Token 발급을 중단했습니다.** 기존 토큰은
계속 동작하지만, 새로 만들 수는 없습니다. 그래서 길은 두 갈래입니다.

**a) OAuth2 — 오늘 실제로 되는 쪽.**
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
에서 애플리케이션을 등록하고 redirect를 `http://localhost:9876/callback/`로
지정하세요. **끝의 슬래시는 필수입니다.** 포털은 다른 형태를
`invalid_redirect_uri`로 거절합니다.

> **대신 `developer.ouraring.com`에 등록했다면**, 그 앱은 Oura의 더 새로운 포털에
> 속하고 그쪽의 토큰 엔드포인트는 다른 것입니다. 레거시 엔드포인트는 그런 앱을
> **매번** 갱신할 때마다 거절합니다. 그래서 등록은 딱 한 번, 첫 액세스 토큰이 만료될
> 때까지만 동작하고, 그 뒤로는 이유를 설명해 주는 것 하나 없이 영원히 실패합니다.
> 이 서버는 레거시 엔드포인트를 먼저 시도하고 자동으로 새 엔드포인트로
> 넘어갑니다. 어느 쪽이든 따로 설정할 것은 없습니다.


```bash
export OURA_CLIENT_ID="…"
export OURA_CLIENT_SECRET="…"
oura-mcp --authorize             # opens the browser, waits for the callback
oura-mcp --authorize --manual    # headless machines: you paste the URL back
```

토큰은 `~/.config/oura-mcp/credenciales.json`에 600 권한으로 저장되며 — 혹시
`keyring`이 설치되어 있다면 시스템 키체인에 저장됩니다. `keyring`은 이 패키지의
의존성이 아닙니다 — 스스로 갱신됩니다. `oura-mcp --forget`으로 지웁니다.

**b) 개인 토큰, 이미 갖고 있었다면.**

```bash
export OURA_PAT="your-token"
oura-mcp --check
```

`--check`는 자가 점검입니다. 어떤 자격 증명을 쓰고 있는지, 어떤 scope가
부여됐는지, 접근 권한이 얼마나 남았는지를 **토큰도, 건강 수치 하나도 돌려주지 않고**
보고합니다. 토큰의 길이를 보고하지, 토큰 자체는 결코 보고하지 않습니다. 오류
메시지는 채팅과 이슈에 복사·붙여넣기 되기 마련이고, 그 이상을 담고 있을 이유가
없습니다.

### Claude Code에 연결하기

패키지를 설치한 상태에서(`pip install mcp-oura`):

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- oura-mcp
```

`oura-mcp --authorize`를 실행하고 나면 `OURA_SANDBOX`는 빼세요.

**[uv](https://docs.astral.sh/uv/)를 쓴다면** 영구적으로 설치할 것이 하나도
없습니다.

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- uvx --from mcp-oura oura-mcp
```

배포판 이름은 `mcp-oura`이고 실행 파일은 `oura-mcp`이기 때문에 `--from`이
필요합니다. *(이것은 `uv`가 있어야 합니다. 없으면 위 명령은 "command not found"로
실패하고, 그때는 `pip install`이 갈 길입니다.)*

Claude Code 플러그인으로:

```bash
claude plugin marketplace add proscar87/oura-mcp
claude plugin install oura@oura-mcp
```

### Claude Desktop에 연결하기

**클릭 한 번:** [릴리스 페이지](https://github.com/proscar87/oura-mcp/releases)에서
`oura-mcp.mcpb`를 내려받아 더블클릭하세요. Claude Desktop이 설치합니다. 터미널도,
JSON도, Python도 없습니다. 샘플 데이터가 켜진 채로 배포되므로 자격 증명이 하나도
없는 상태에서도 동작합니다.

내 데이터를 보고 싶어지면 그냥 무언가를 요청하면 됩니다. Claude를 통해 Oura의 인증
페이지를 열고, 콜백을 기다린 다음, 요청했던 것을 다시 시도합니다. 터미널은 필요
없습니다. 이것이 되는 이유는 MCP에 바로 이런 상황을 위한 방식 — URL elicitation —
이 있고, 페이지를 여는 쪽이 클라이언트이기 때문입니다.

Oura가 여전히 요구하는 단 한 가지는 모든 애플리케이션이 등록되어야 한다는 것이라,
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
에서 client ID와 secret을 한 번은 받아와야 합니다. 그것은 Oura의 규칙이지 이 서버의
규칙이 아닙니다. `oura-mcp --authorize`는 터미널을 쓰는 사람과 URL을 띄울 수 없는
클라이언트를 위해 그대로 남아 있습니다.

**또는 직접,** `~/Library/Application Support/Claude/claude_desktop_config.json`에서:

```json
{
  "mcpServers": {
    "oura": {
      "command": "/full/path/to/oura-mcp",
      "env": { "OURA_SANDBOX": "1" }
    }
  }
}
```

`which oura-mcp`가 전체 경로를 알려줍니다. Claude Desktop은 터미널의 `PATH`를
물려받지 않기 때문에 거기에 이름만 적으면 조용히 실패합니다. MCP 서버를 설정할 때
가장 흔한 실수 중 하나입니다.

## 도구

| | |
|---|---|
| `oura_collections` | 19개 전부, 각각이 무엇을 담고 있고 어떤 파라미터를 받는지 |
| `oura_query` | 한 컬렉션을 범위 전체에 걸쳐, 끝까지 페이지를 넘기며 |
| `oura_check` | 아무것도 노출하지 않는 자가 점검 |

**열아홉 개가 아니라 세 개입니다.** 컬렉션마다 도구를 하나씩 두는 서버는, 각각이
무엇을 담고 있는지 알기도 전에 모델에게 비슷한 이름 19개 중 하나를 고르라고
강요합니다. 여기서는 컬렉션이 파라미터이고, 목록은 필요할 때 조회합니다.

셋 다 스스로를 읽기 전용이라고 선언하는데, 이것은 약속이 아닙니다. 패키지 어디에도
`POST`, `PUT`, `DELETE`가 없고, 계속 그렇게 유지되도록 소스를 읽는 테스트가
있습니다.

### `oura_query` 파라미터

| | |
|---|---|
| `collection` | 19개 중 어느 것인지. `oura_collections`가 목록을 보여줍니다 |
| `day` | 하루. `start=end=day`의 축약형 |
| `start`, `end` | 범위, **양쪽 끝 모두 포함** |
| `fields` | 이 필드들만. Oura가 자기 쪽에서 잘라내므로 내려오는 양이 줄어듭니다 |
| `latest` | 가장 최근 기록. `heartrate`와 `ring_battery_level`에서만 |
| `format` | `json` 또는 `csv`. 절감폭은 컬렉션마다 다릅니다: `heartrate`에서 55%, `daily_sleep`에서 10% |

그리고 무언가 깔끔하게 나오지 않았을 때 응답이 알려주는 것들:
도달한 마지막 날을 가리키는 `continue_from`을 동반한 `truncated`, Oura가 토큰을
반복할 때의 `pagination_cycle`, `ignored_fields`, `discarded_out_of_range`,
`uneven_columns`, 조회 결과가 비었을 때의 `empty`, 그리고 돌아온 내용이 무시하기
어려울 만큼 무거울 때의 `large_response`.

그 밖에 네 가지는, 그러지 않았다면 결코 알 수 없었을 일이 일어났다고 말해 줍니다.

- **`synthetic`** — 이것은 당신의 데이터가 아니라 Oura의 샘플 데이터입니다. 샘플
  모드의 모든 응답에 함께 실려 오고 확장 프로그램은 바로 그 모드로 배포되므로,
  모델이 지어낸 숫자를 당신의 수면이라고 보고할 수 없습니다.
- **`rate_limited`** — Oura가 429로 거절했고 재시도가 통과했습니다. **데이터는
  완전합니다.** 이 경고는 *다음* 조회에 대한 것입니다. Oura는 성공한 응답에
  레이트 리밋 헤더를 보내지 않으므로, 거절당하는 것이 한계에 가까워졌다는 유일한
  신호입니다.
- **`fields_split`** — `fields`가 `["day","score"]`가 아니라 `"day,score"`로
  도착해서 쪼개졌습니다. Oura의 필드 이름에는 쉼표가 없으므로 쪼개는 데에 모호함은
  없습니다. 하지만 당신의 입력을 말없이 재해석하는 것은 이 패키지 전체가 문제
  삼는 바로 그 잘못입니다.
- **`cached`** — 답이 Oura가 아니라 이번 세션의 메모리에서 왔습니다. **오늘 이전에**
  닫힌 범위에 대해서만 그렇게 하는데, 이미 끝난 하루는 기록이 더 늘어날 수 없기
  때문입니다. 오늘은 절대 붙잡아 두지 않습니다. 반지는 제 내키는 대로 동기화하기
  때문입니다. 빈 답도 결코 붙잡아 두지 않습니다. "데이터가 없다"와 "반지가 아직
  동기화되지 않았다"를 구별해 주는 것이 아무것도 없고, 후자를 얼려 두면 일시적인
  공백이 영구적인 공백이 되어 버립니다. 이 저장소는 메모리에 살고 프로세스와 함께
  죽습니다. **건강 데이터는 결코 디스크에 기록되지 않습니다.**

마지막 항목은 측정에서 나왔습니다. **30일치 `daily_activity`는 252,000자**이고,
그중 87%가 분당 MET 시계열인 `met` 한 필드입니다. `fields`로 세 개의 열만
요청하면 같은 30일치가 5,000자로 줄어듭니다. **99% 감소입니다.** 서버가 알아서
잘라내지는 않습니다. 그것이야말로 덜 주는 일이니까요. 다만 무엇이 무거운지, 어떻게
덜 요청할 수 있는지는 알려줍니다.

*(파라미터 이름은 안정적이고, 여기에 문서화되어 있으며, 모델이 읽는 도구 설명도
같은 정보를 담고 있습니다. 0.2.0까지는 스페인어였고, 영어로의 개명은 0.3.0에서
이루어졌으며 CHANGELOG에 호환성을 깨는 변경으로 기록되어 있습니다.)*

## 이 서버가 하지 않는 일

**분석하지 않습니다.** 상관관계도, 이상 탐지도, 기간 비교도 없습니다. 다른 서버들이
자신의 가치를 두는 곳이 바로 거기인데도 말입니다.

이유는 이렇습니다. 여기 안에서 계산된 평균은 방법론이 빠진 하나의 숫자로 모델에
도착합니다. 9년치 실제 데이터를 놓고 보면, **연속된 두 측정값 사이의 변화 네 번 중
세 번은 그 지표 자체의 정상적인 진폭 안에 들어갑니다.** 그 지표가 혼자서 얼마나
흔들리는지는 말하지 않은 채 "당신의 HRV가 12% 올랐습니다"를 건네는 서버는 알려주고
있는 것이 아닙니다. 신호를 만들어내고 있는 것입니다.

여기서 당신이 받는 것은 데이터입니다. 분석은 방법을 인용할 수 있는 곳에 있어야
합니다. 예를 들면 혈액 바이오마커에 대해 바로 그 구분을 하는
[cotejo](https://github.com/proscar87/cotejo) 같은 곳입니다.

## 19개 컬렉션

**일일 요약** — `daily_sleep`, `daily_readiness`, `daily_activity`,
`daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`,
`vO2_max`

**점수가 감추는 세부 정보** — `sleep`(수면 단계, HRV, 체온, 입면 잠복기),
`sleep_time`, `workout`, `session`, `rest_mode_period`, `tag`, `enhanced_tag`

**고해상도** — `heartrate`, `ring_battery_level`

**범위 없음** — `personal_info`, `ring_configuration`

날짜 범위를 쓰는 컬렉션은 `YYYY-MM-DD`를 사용합니다. `heartrate`와
`ring_battery_level`은 시각이 포함된 ISO 8601을 사용합니다.

## 다른 Oura MCP 서버들

2026년 8월 기준으로 여럿 있고, 차이를 정확히 짚어 둘 가치가 있습니다.
[`benngermin/oura-mcp`](https://github.com/benngermin/oura-mcp)는 재개 가능한
커서로 **페이지네이션을 제대로 합니다**.
[`daveremy/oura-mcp`](https://github.com/daveremy/oura-mcp)는 `end_date` 수정을
우리와 같은 주에 냈습니다.
[`davidmosiah/oura-mcp`](https://github.com/davidmosiah/oura-mcp)는 MCP 표면이
가장 완전합니다. 페이지네이션은 이제 누구도 구별해 주지 않습니다.

우리가 확인할 수 있었던 범위에서, 실제로 구별되는 것은 이렇습니다. **`workout`의
UTC 어긋남은 그중 어디에도 문서화되어 있지 않고**, Oura가 무시하는 곳에서 `latest`를
거절하는 것도, 한 번도 적용되지 않은 필드에 대해 경고하는 것도 없습니다. 그리고
분석하지 않는 것을 하나의 입장으로 내세우는 곳은 어디에도 없습니다.

## 개인정보 처리방침

이 절이 존재하는 이유는 Claude 커넥터 디렉터리가 요구하기 때문입니다. 짧은 이유는
설명할 것이 별로 없기 때문입니다. 서버는 당신의 기기에서 돌고, 오직 하나의
서비스인 Oura API하고만 이야기합니다.

**무엇을 수집하는가.** 우리 쪽에서는 아무것도 수집하지 않습니다. 당신이 요청한
건강 데이터는 Oura API에서 당신의 MCP 클라이언트로 가며, 우리의 어떤 서버도 거치지
않습니다. 그런 서버가 아예 없기 때문입니다.

**무엇이, 어디에 저장되는가.** 당신의 자격 증명만, 그리고 당신의 기기에만:

| | |
|---|---|
| OAuth2 토큰 | `~/.config/oura-mcp/credenciales.json`, 권한 `600` — 또는 `keyring`이 있다면 시스템 키체인 |
| 개인 토큰 | 당신이 둔 곳에: `OURA_PAT`, 또는 `OURA_PAT_FILE`이 가리키는 파일 |

건강 데이터는 디스크에 기록되지 않으며, 이것은 나중에 갖다 붙인 주장이 아니라
캐시가 애초에 그 제약을 중심으로 설계되었다는 뜻입니다. 이미 끝난 하루에 대한
답은 프로세스가 살아 있는 동안 **메모리에만** 보관되고, `--forget`이 그것을
지웁니다. 당신의 수면에 관한 어떤 것도 서버가 종료된 뒤까지 남지 않습니다.

**누구와 공유되는가.** 아무와도 공유되지 않습니다. 유일한 외부 연결은 요청한 것을
가져오기 위해 당신의 토큰과 함께 `api.ouraring.com`으로 가는 것뿐입니다. Oura가
당신의 데이터를 어떻게 사용하는지는 이 방침이 아니라
[Oura의 개인정보 처리방침](https://ouraring.com/privacy-policy)이 규율합니다.

**얼마나 보관되는가.** 자격 증명은 당신이 지울 때까지입니다. `oura-mcp --forget`,
또는 파일을 삭제하면 됩니다. 건강 데이터는 아예 보관되지 않습니다. 그 응답 안에
살아 있다가 끝입니다.

**진단은 아무것도 노출하지 않습니다.** `oura_check`는 토큰의 길이를 보고하지 토큰
자체는 보고하지 않고, 프로필의 필드 이름을 보고하지 그 값은 보고하지 않습니다.
토큰은 스택 트레이스에서조차 출력되지 않는 타입으로 감싸여 있습니다.

**연락처.** [저장소 이슈](https://github.com/proscar87/oura-mcp/issues).

## 언어에 관한 참고

이 저장소는 영어로 되어 있습니다. 코드와 그 주석, 테스트, 그리고 내부
문서(`AGENTS.md`, `ROADMAP.md`, `CHANGELOG.md`)까지 그렇습니다. 지금 읽고 계신 이
문서는 그 영어 README의 번역본입니다.

0.2.0까지는 스페인어로 쓰여 있었습니다. 도구 파라미터는 0.3.0에서 이름이
바뀌었고 — 호환성을 깨는 변경이며, CHANGELOG에도 그렇게 기록되어 있습니다 —
산문도 그 뒤를 따랐습니다. 아직 스페인어로 남아 있는 것은 저장소 키인데, 누군가
이미 저장해 둔 자격 증명을 고아로 만들지 않고서는 이름을 바꿀 수 없는 것들이고,
그렇다고 이름을 짚어 말하는 테스트가 있습니다.

## 라이선스

MIT.

---

*이 번역은 기계의 도움을 받아 작성되었습니다. 잘못되었거나 어색한 부분을 발견하시면
pull request로 수정해 주시면 감사하겠습니다:
[저장소 이슈](https://github.com/proscar87/oura-mcp/issues).*
