# CLAUDE.md — 협업 가이드

## 프로젝트 개요

이 레포는 두 개의 서비스를 포함한다:

1. **Multi-Agent 투자 자문 시스템** — CFO·CSO·투자컨설턴트 3명의 AI C-suite가 실거래 데이터 기반으로 토론하며 투자 의사결정을 돕는다 (KAIST IMMS MBA).
2. **VerifyHome** — 주소 하나로 아파트 실거래가를 시각화하고 AI와 시세를 상담하는 웹 서비스. Render.com에 배포됨.

## 작업 방식

### 1. Forest First, Then Trees

- 새 작업을 시작할 때 **전체 그림(목표, 범위, 영향받는 파일)을 먼저 파악**한 뒤 세부 구현에 들어간다.
- 코드를 바로 작성하지 말고, 어떤 파일들이 변경되는지 먼저 정리해서 보여준다.
- 큰 작업은 Phase 단위로 나눠서 단계적으로 진행한다.

### 2. 확인하면서 진행 (Interview & Check)

- 모호한 요청이 들어오면 **추정으로 진행하지 말고 질문**한다.
- 각 단계 완료 후 결과를 요약해서 보고하고, 다음 단계로 넘어가기 전에 사용자 확인을 받는다.
- 단, "바로 반영해줘", "계속 진행하자" 같은 명확한 지시에는 즉시 실행한다.

### 3. 항상 테스트 → 커밋

- **커밋 전에 반드시 `pytest tests/ -v` 전체 테스트를 실행**한다.
- 테스트 실패 시 수정 후 재실행하여 전체 통과를 확인한 뒤 커밋한다.
- 새 기능 추가 시 해당 테스트도 함께 작성한다.

### 4. Git 워크플로우

- **세션 시작 시 항상 `git pull origin main`** — GitHub 웹에서 수정한 내용을 놓치지 않는다.
- 작업 브랜치에서 개발 → PR 생성 → **squash merge**로 main에 반영.
- 커밋 메시지는 conventional commits 스타일: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- 푸시 실패 시 rebase 후 재시도. 네트워크 오류는 최대 4회 지수 백오프 재시도.
- 각 스테이지 완료 후 **바로 커밋+푸시** — 다음 스테이지를 시작하기 전에 현재 작업을 안전하게 저장.

## 기술 스택

- **언어**: Python 3.10+
- **LLM**: Anthropic Claude API (`claude-sonnet-4-6`), `AsyncAnthropic`
- **테스트**: pytest (260+ tests), API 키 없이 전체 로직 검증 (E2E + 경계 + 할루시네이션 가드)
- **멀티에이전트 프론트엔드**: Streamlit
- **VerifyHome 백엔드**: FastAPI (`src/market_api.py`), uvicorn
- **VerifyHome 프론트엔드**: Vanilla JS + Chart.js (HTML 단일 파일)
- **VerifyHome DB**: SQLite (`src/apartment.db`) — 단지 좌표 10,239개
- **배포**: Render.com (Web Service, Python)
- **의존성**: requirements.txt 참조

## 프로젝트 구조

```
src/
  main.py              # 멀티에이전트 CLI 엔트리포인트
  app.py               # Streamlit Web UI
  market_api.py        # VerifyHome FastAPI 서버 (HTML 서빙 + /api/* 라우트)
  apartment.db         # 단지 좌표 DB (SQLite, 10,239개 단지, ~1.7MB)
  ...                  # 멀티에이전트 모듈들

realestate-report/
  page0-web.html       # VerifyHome 랜딩 페이지 (주소 검색)
  market-web.html      # VerifyHome 시세 분석 페이지 (차트 + AI 챗봇)
  IA.md                # Information Architecture 문서
  api-schema.md        # API 스키마 문서
  market-chat-prompt.md  # AI 챗봇 프롬프트 설계

agents/                # 멀티에이전트 페르소나 명세서 (*.md)
tests/                 # pytest 테스트 스위트 (260+ tests)
meetings/              # 멀티에이전트 회의록 저장 디렉토리
render.yaml            # Render.com 배포 설정
MANIFESTO.md           # 핵심 가치와 설계 원칙
```

## 핵심 규칙

- 에이전트 페르소나 수정은 `agents/*.md` 파일 편집으로 한다 (코드 변경 아님).
- 내부 코드 키(`"mentor"`, `"practitioner"`, `"redteam"`, `"clerk"`)는 변경하지 않는다.
- 사용자 표시용 이름은 `src/personas.py`의 `AGENT_CONFIG`에서 관리한다.
- 모든 수치에는 출처를 명시한다 (MANIFESTO 핵심 가치 1번).

## 주요 모듈

### VerifyHome

| 모듈 | 역할 |
|------|------|
| `src/market_api.py` | FastAPI 서버 — `/`, `/market` HTML 서빙 + `/api/*` 엔드포인트 |
| `src/apartment.db` | 단지 좌표 SQLite DB (sgg_cd, umd_nm, apt_nm, lat, lng) |
| `realestate-report/page0-web.html` | 랜딩 페이지 — 주소 자동완성 + 평형 선택 |
| `realestate-report/market-web.html` | 시세 분석 페이지 — Chart.js 산점도 + AI 챗봇 |

### 멀티에이전트

| 모듈 | 역할 |
|------|------|
| `src/meeting.py` | 회의 오케스트레이터 (asyncio.gather 병렬 호출) |
| `src/personas.py` | 페르소나 로더 + 시스템 프롬프트 빌더 |
| `src/real_estate.py` | 국토교통부 실거래가 API + 샘플 데이터 |
| `src/yield_analyzer.py` | 수익률 분석 (표면/실질/레버리지) |
| `src/scenario.py` | 민감도·스트레스 시뮬레이션 |
| `src/cashflow.py` | 10년 현금흐름 프로젝션 (IRR/NPV) |
| `src/monte_carlo.py` | Monte Carlo 시뮬레이션 (Cholesky) |
| `src/tax.py` | 취득세/보유세/양도세 시뮬레이션 |
| `src/scorecard.py` | 100점 만점 투자 판단 스코어카드 |
| `src/portfolio.py` | 포트폴리오 조합 최적화 |
| `src/charts.py` | Plotly 시각화 (8종 차트) |
| `src/archive.py` | 회의록 저장 + 세션 체크포인트 + 과거 회의 검색 |

## 로컬 실행

### VerifyHome

```bash
uvicorn src.market_api:app --reload --port 8000
# http://localhost:8000/ → 랜딩
# http://localhost:8000/market → 시세 분석
```

환경 변수 필요:
- `ANTHROPIC_API_KEY` — AI 챗봇 응답 생성
- `DATA_GO_KR_API_KEY` — 국토교통부 실거래가 API
- `JUSO_CONFIRM_KEY` — 도로명주소 API (주소 자동완성)

### 멀티에이전트 시스템

```bash
pytest tests/ -v              # 전체 테스트 (260+)
pytest tests/test_e2e.py -v   # E2E 파이프라인 테스트
python src/demo_mock.py       # API 키 없이 Mock 데모
python src/main.py --demo     # 실제 API 데모
streamlit run src/app.py      # Streamlit Web UI
```

## 세션 관리

- 세션 시작 시 **반드시 `git fetch && git pull origin main`** 먼저 실행 — GitHub 웹 수정을 놓치지 않는다.
- 최근 커밋 5개를 확인하고, 이전 세션에서 중단된 작업이 있는지 파악한 후 작업을 시작한다.
- 한 세션에서 1~2개 스테이지만 완결하는 것을 목표로 한다 — 4개를 시작하는 것보다 2개를 완결하는 게 ��다.

## 페르소나 리팩터 규칙

- 페르소나 명세서(`agents/*.md`)를 수정할 때는 **반드시** 관련 테스트 키워드도 동시에 갱신한다.
- 영향받는 파일: `tests/test_personas.py`, `tests/test_demo_mock.py`, `src/demo_mock.py`의 Gold Standard, `src/personas.py`의 DIVERSITY_ANGLES
- 페르소나만 수정하고 테스트를 나중에 고치지 않는다 — 한 커밋에 같이 반영.

## 환경 변수

| 변수 | 용도 | 없을 때 |
|------|------|---------|
| `ANTHROPIC_API_KEY` | AI 에이전트 응답 생성 (멀티에이전트 + VerifyHome 챗봇) | Mock 데모만 가능 |
| `DATA_GO_KR_API_KEY` | 국토교통부 실거래가 API | 샘플 데이터 자동 fallback |
| `JUSO_CONFIRM_KEY` | 도로명주소 API (VerifyHome 주소 자동완성) | 자동완성 비활성화 |

API 키가 없을 때는 즉시 사용자에게 알리고, 조용히 mock으로 대체하지 않는다.

## Custom Skills

- `/ship-stage`: 테스트 → 커밋 → 푸시 → PR → 머지 전체 플로우 자동화
- `/refactor-persona`: 페르소나 변경 + 테스트 키워드 동시 갱신 TDD 루프

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

Available skills: `/office-hours`, `/plan-ceo-review`, `/plan-eng-review`, `/plan-design-review`, `/design-consultation`, `/design-shotgun`, `/design-html`, `/review`, `/ship`, `/land-and-deploy`, `/canary`, `/benchmark`, `/browse`, `/connect-chrome`, `/qa`, `/qa-only`, `/design-review`, `/setup-browser-cookies`, `/setup-deploy`, `/setup-gbrain`, `/retro`, `/investigate`, `/document-release`, `/codex`, `/cso`, `/autoplan`, `/plan-devex-review`, `/devex-review`, `/careful`, `/freeze`, `/guard`, `/unfreeze`, `/gstack-upgrade`, `/learn`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. The
skill has multi-step workflows, checklists, and quality gates that produce better
results than an ad-hoc answer. When in doubt, invoke the skill. A false positive is
cheaper than a false negative.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke /office-hours
- Strategy, scope, "think bigger", "what should we build" → invoke /plan-ceo-review
- Architecture, "does this design make sense" → invoke /plan-eng-review
- Design system, brand, "how should this look" → invoke /design-consultation
- Design review of a plan → invoke /plan-design-review
- Developer experience of a plan → invoke /plan-devex-review
- "Review everything", full review pipeline → invoke /autoplan
- Bugs, errors, "why is this broken", "wtf", "this doesn't work" → invoke /investigate
- Test the site, find bugs, "does this work" → invoke /qa (or /qa-only for report only)
- Code review, check the diff, "look at my changes" → invoke /review
- Visual polish, design audit, "this looks off" → invoke /design-review
- Developer experience audit, try onboarding → invoke /devex-review
- Ship, deploy, create a PR, "send it" → invoke /ship
- Merge + deploy + verify → invoke /land-and-deploy
- Configure deployment → invoke /setup-deploy
- Post-deploy monitoring → invoke /canary
- Update docs after shipping → invoke /document-release
- Weekly retro, "how'd we do" → invoke /retro
- Second opinion, codex review → invoke /codex
- Safety mode, careful mode, lock it down → invoke /careful or /guard
- Restrict edits to a directory → invoke /freeze or /unfreeze
- Upgrade gstack → invoke /gstack-upgrade
- Save progress, "save my work" → invoke /context-save
- Resume, restore, "where was I" → invoke /context-restore
- Security audit, OWASP, "is this secure" → invoke /cso
- Make a PDF, document, publication → invoke /make-pdf
- Launch real browser for QA → invoke /open-gstack-browser
- Import cookies for authenticated testing → invoke /setup-browser-cookies
- Performance regression, page speed, benchmarks → invoke /benchmark
- Review what gstack has learned → invoke /learn
- Tune question sensitivity → invoke /plan-tune
- Code quality dashboard → invoke /health

## 의사소통 언어

- 한국어를 기본으로 사용한다.
- 커밋 메시지와 PR 제목은 한국어 또는 영어 모두 가능.
