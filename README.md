# VerifyHome + Multi-Agent 부동산 분석 시스템

이 레포는 두 개의 서비스를 포함합니다.

---

## VerifyHome — 실거래가 시각화 + AI 시세 상담

> 주소 하나로 근처 동네 같은 평형 실거래가 비교 + AI와 가격 차이 이유를 상담하세요.

**배포**: Render.com에서 운영 중

### Quick Start (로컬)

```bash
pip install -r requirements.txt

# 환경 변수 설정
export ANTHROPIC_API_KEY="sk-ant-..."
export DATA_GO_KR_API_KEY="..."
export JUSO_CONFIRM_KEY="..."

uvicorn src.market_api:app --reload --port 8000
# → http://localhost:8000
```

### 구조

```
realestate-report/
  page0-web.html   # 랜딩 — 주소 검색 + 평형 선택
  market-web.html  # 시세 분석 — 산점도 차트 + AI 챗봇
src/
  market_api.py    # FastAPI 서버 (HTML 서빙 + /api/* 라우트)
  apartment.db     # 단지 좌표 DB (SQLite, 10,239개)
render.yaml        # Render.com 배포 설정
```

### 주요 API

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /` | 랜딩 페이지 |
| `GET /market` | 시세 분석 페이지 |
| `GET /api/address-search` | 주소 자동완성 (도로명주소 API) |
| `GET /api/apt-sizes` | 단지 평형 목록 |
| `GET /api/market-data` | 실거래가 데이터 (산점도 + 이동평균) |
| `POST /api/chat` | AI 챗봇 (Claude streaming) |

### Render 배포

1. [render.com](https://render.com) 가입 → New Web Service → GitHub 레포 연결
2. 환경변수 3개 입력: `ANTHROPIC_API_KEY`, `DATA_GO_KR_API_KEY`, `JUSO_CONFIRM_KEY`
3. `render.yaml` 자동 감지 → Deploy

---

## Multi-Agent 부동산 투자 자문 시스템

> "강남 오피스텔 수익률 3%면 낮은 거 아냐?" 한마디에,
> CFO·CSO·투자컨설턴트 세 명의 C-suite가 실거래 데이터를 놓고 토론합니다.

---

## 한 줄 요약

**공공 부동산 데이터 + 수익률 분석 + 시나리오 시뮬레이션을 바탕으로, 3명의 AI C-suite 에이전트가 텍스트로 토론하며 투자 의사결정을 돕는 멀티 에이전트 자문 시스템**

---

## Quick Start

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. API 키 설정
cp .env.example .env
# .env 파일에 ANTHROPIC_API_KEY 입력

# 3-A. CLI 실행
python src/main.py --demo                           # 강남 오피스텔 데모
python src/main.py --region 강남구 성동구 강서구      # 실거래 데이터 + 수익률 분석
python src/main.py --region 강남구 --file 매물.xlsx   # 파일 업로드 포함
python src/main.py --demo --cashflow --monte-carlo  # 현금흐름 + Monte Carlo 포함
python src/main.py --demo --debate --rounds 3       # 3라운드 토론 모드
python src/main.py --demo --property-type apartment # 아파트 데이터로 데모
python src/main.py --demo --tax --scorecard        # 세금 + 스코어카드
python src/main.py --demo --full                   # 모든 분석 한 번에

# 3-B. Web UI 실행
streamlit run src/app.py

# 4. Mock 데모 (API 키 불필요)
python src/demo_mock.py

# 5. 테스트
pytest tests/ -v
```

---

## 핵심 기능

### 1. 세 명의 C-suite가 동시에 토론한다

| 에이전트 | 직함 | 전문 영역 | 응답 예시 |
|---------|------|----------|----------|
| 📊 CFO | 재무총괄 | 수익률, 현금흐름, 세금, 대출 | "대출 60% 끼면 레버리지 수익률 0.2%인데, 취득세 회수에 57년 걸립니다" |
| 🔴 CSO | 전략총괄 | 시장 분석, 타이밍, 리스크 | "금리 0.5%p만 올라도 월 순수익이 마이너스 진입합니다" |
| 🧭 투자컨설턴트 | 투자자문 | 투자 적합성, 포트폴리오, 대안 비교 | "월세 목적이면 강남보다 성동·마곡 분산 매수가 현금흐름에 유리합니다" |
| 📝 비서실장 | 서기 | 회의 정리 | "결정: 강남 보류. Action: 성수 급매물 3건 리스트업 — 기한 4/27" |

3명의 에이전트가 `asyncio.gather()`로 **동시에** 응답을 생성합니다.
각 에이전트는 자신의 발언만 `assistant`, 나머지를 `user`로 보는 POV 메시지 구조로 API를 호출합니다.

### 2. 실거래가 데이터 자동 연동

```
■ 강남구 (조회기간: 202602)
  매매 건수: 5건
  평균 매매가: 4억 4,600만원
  평균 전용면적: 42.1㎡
  최근 거래:
    - 역삼 센트럴 오피스텔 42.3㎡ 8층 → 4억 5,000만원 (2026.02.15)
```

- 국토교통부 오피스텔/아파트 매매/전월세 실거래 API (`data.go.kr`)
- **오피스텔 + 아파트** 두 가지 매물 유형 지원
- API 키 없을 때 자동 샘플 데이터 fallback (강남구/성동구/강서구)
- **전국 주요 지역 지원**: 서울 25개구 + 경기 주요 시 + 부산/대구/인천/광주/대전 (총 80+ 지역)
- 권역별 그룹 선택 UI (서울/경기/부산/대구/인천/광주/대전)
- TTL 기반 캐싱 + 지수 백오프 재시도로 안정적 API 호출

### 3. 수익률 자동 분석

```
■ 권역 비교 요약
  권역     매매가      월세    표면   실질   레버리지   월순수익
  강남구   4억 4,600만  116만   3.1%   2.5%     0.2%     3만원
  성동구   3억 3,250만  115만   4.2%   3.3%     2.3%    25만원
  강서구   2억 8,500만   97만   4.1%   3.2%     1.9%    18만원
```

- 표면/실질/레버리지 수익률 자동 계산
- **IRR** (내부수익률) + **NPV** (순현재가치) 자동 산출
- 취득세, 관리비, 공실, 대출이자 반영
- 손익분기점 분석 (취득세 회수 기간)
- 권역 간 비교표 + 1위 랭킹

### 4. 시나리오 시뮬레이션 (What-If)

```
▸ 강남구 — 스트레스 테스트 (최악 / 기본 / 최선)
  최악 시나리오   금리 5.5% | 공실 3개월 | 월순수익 -38만원
  기본 시나리오   금리 4.0% | 공실 1개월 | 월순수익   3만원
  최선 시나리오   금리 3.0% | 공실 0.5개월 | 월순수익  35만원
  → 최악~최선 월순수익 변동폭: 73만원
```

- 금리 민감도: ±1.5%p 범위 6단계
- 공실 민감도: 0~3개월 6단계
- 매매가 민감도: ±20% 7단계
- 스트레스 테스트: 최악/기본/최선 3-시나리오

### 5. 10년 현금흐름 프로젝션

```
■ 강남구 — 10년 현금흐름 (IRR: 3.4% | NPV: 264만원)
  연도   임대수입   비용    대출상환   순수익    누적      자산가치
  1     1,392만   348만   1,070만   -26만    -26만    4.55억
  ...
  10    1,665만   468만   1,070만    127만    393만    5.33억
  Equity Multiple: 1.08x
```

- 임대료 성장률, 비용 인플레이션, 자산 상승률 반영
- 매각 시 처분비용 포함 터미널 밸류 계산
- IRR/NPV/Equity Multiple 자동 산출

### 6. Monte Carlo 시뮬레이션

```
▸ 강남구 — IRR 분포 (3,000회)
  P5: -2.1% | P25: 1.5% | P50: 3.4% | P75: 5.3% | P95: 8.9%
  손실 확률: 28.3%
```

- 임대성장률/공실/금리/자산가치 4변수 동시 시뮬레이션
- **Cholesky 분해** 기반 상관관계 반영 (순수 Python, numpy 불필요)
- 백분위 분포표 + 손실 확률 자동 계산

### 7. 다중 라운드 토론 모드

- 에이전트들이 **2~3라운드**에 걸쳐 상호 반론/보완
- **합의 감지**: 모든 에이전트가 같은 방향이면 확증편향 방지 챌린지 자동 주입
- **다양성 추적**: 각 에이전트가 사용한 관점을 추적, 미사용 관점을 리마인더로 제시

### 8. 세금 시뮬레이션

- 취득세: 주택 수별 세율 자동 적용 (1주택 1.1~3% / 2주택 8% / 3주택 12%)
- 보유세: 재산세 + 종합부동산세 연간/누적 계산
- 양도소득세: 장기보유특별공제 + 누진세율 자동 적용
- 실효세율 및 세후 순이익 비교

### 9. 투자 판단 스코어카드

```
■ 강남구 — 대기 (48/100점)
  수익률 [████░░░░░░] 11/25  표면 3.1% / 실질 2.5%
  현금흐름 [█████░░░░░] 12/25  IRR 3.5% / EM 1.40x
  리스크 [████░░░░░░] 10/25  손실확률 50% / P50 IRR 3.5%
  세금효율 [██████░░░░] 15/25  실효세율 15% / 세후 3,200만원
```

- 수익률/현금흐름/리스크/세금 4개 축 각 25점 (총 100점)
- 투자 추천(70+) / 조건부 추천(55+) / 대기(40+) / 패스 자동 판정
- 강점/리스크 자동 식별

### 10. 포트폴리오 분석

- 다중 권역 조합별 기대수익률/변동성 비교
- Cholesky 기반 분산효과 측정
- 수익 최적 / 안정 최적 조합 추천
- 단일 매물 vs 2개 조합 vs 전체 조합 비교표

### 11. Plotly 시각화 차트

- 권역 비교 레이더 차트 (5축: 표면/실질/레버리지/순수익/안정성)
- 금리/공실/매매가 민감도 차트
- 스트레스 테스트 비교 바 차트
- 10년 현금흐름 차트 (순수익 + 누적 + 자산가치)
- Monte Carlo IRR 분포 히스토그램 (P5/P50/P95 마킹)
- 세금 비교 스택 차트 (취득세/보유세/양도세)
- 스코어카드 수평 바 차트 (4축 점수 비교)
- 포트폴리오 효율적 프론티어 산점도 (IRR vs 변동성)

### 12. 파일 업로드

- **Excel** (.xlsx/.xls): 매물 리스트, 수익률 비교표
- **PDF**: 계약서, 감정평가서
- 파일 내용이 에이전트 컨텍스트에 자동 주입

### 13. 비서실장 회의록

회의 종료 시 자동 생성:
- 핵심 안건 / 주요 논의 (C-suite별 1줄 요약)
- 결정사항 / 보류사항 (보류 이유 명시)
- Next Action Plan (동사 + 담당자 + 기한)
- 다음 회의 아젠다

### 14. 세션 지속성

- 매 턴 자동 체크포인트 (`.sessions/*.json`)
- `--resume <session-id>`로 중단된 회의 재개
- 과거 회의록 자동 로딩 (`--context`)

---

## 아키텍처

```
사용자 입력
    │
    ▼
┌─────────────────────────────────────────────┐
│  main.py / app.py (CLI / Streamlit UI)      │
│  --region, --file, --context, --demo        │
└────────────────┬────────────────────────────┘
                 │
    ┌────────────▼────────────┐
    │      meeting.py         │
    │  (Meeting orchestrator) │
    │  asyncio.gather()       │
    └──┬──────┬──────┬────────┘
       │      │      │          parallel
  ┌────▼─┐ ┌─▼───┐ ┌▼────┐
  │ CFO  │ │ CSO │ │투자컨설턴트│    ← personas.py + agents/*.md
  └──┬───┘ └──┬──┘ └──┬──┘
     └────────┼───────┘
              ▼
         비서실장 (finalize)
              │
              ▼
         meetings/*.md (회의록)

데이터 주입 (transcript 시작 전):
  real_estate.py  → 실거래 데이터
  yield_analyzer.py → 수익률 분석
  scenario.py     → 시나리오 시뮬레이션
  file_parser.py  → 업로드 파일
  archive.py      → 과거 회의 맥락
```

---

## 기술 스택

| 모듈 | 기술 | 역할 |
|------|------|------|
| LLM | Anthropic Claude (claude-sonnet-4-6) | 에이전트 대화 생성 |
| 데이터 | 국토교통부 실거래가 API | 오피스텔/아파트 매매/전월세 시세 |
| 분석 | yield_analyzer + scenario + cashflow | 수익률 + What-If + 10년 현금흐름 |
| 시뮬레이션 | monte_carlo | Cholesky 기반 Monte Carlo 시뮬레이션 |
| 시각화 | Plotly | 레이더/민감도/스트레스/현금흐름/MC 차트 |
| 세금 | tax | 취득세/보유세/양도세 시뮬레이션 |
| 스코어카드 | scorecard | 100점 만점 투자 판단 + 추천 |
| 포트폴리오 | portfolio | 다중 매물 조합 최적화 |
| 토론 | consensus + personas | 합의 감지, 확증편향 방지, 다양성 추적 |
| 파일 | openpyxl + pdfplumber | Excel/PDF 파싱 |
| Frontend | Streamlit | 멀티 에이전트 채팅 UI |
| 테스트 | pytest (260 tests) | API 키 없이 전체 로직 검증 (E2E + API mock 포함) |

---

## 프로젝트 구조

```
buildteam/
├── agents/                    # 페르소나 명세서 (Markdown)
│   ├── practitioner.md        # CFO — 재무총괄
│   ├── redteam.md             # CSO — 전략총괄
│   ├── mentor.md              # 투자컨설턴트 — 투자자문
│   └── clerk.md               # 비서실장 — 서기
├── src/
│   ├── main.py                # CLI 엔트리포인트
│   ├── app.py                 # Streamlit Web UI
│   ├── meeting.py             # 회의 오케스트레이터
│   ├── personas.py            # 페르소나 로더 + 시스템 프롬프트
│   ├── real_estate.py         # 국토교통부 API + 샘플 데이터
│   ├── yield_analyzer.py      # 수익률 분석기
│   ├── scenario.py            # 시나리오 시뮬레이터
│   ├── cashflow.py            # 10년 현금흐름 프로젝션
│   ├── monte_carlo.py         # Monte Carlo 시뮬레이션
│   ├── consensus.py           # 합의/분기 감지 + 확증편향 방지
│   ├── tax.py                 # 세금 시뮬레이터 (취득/보유/양도)
│   ├── scorecard.py           # 투자 판단 스코어카드
│   ├── portfolio.py           # 포트폴리오 분석
│   ├── charts.py              # Plotly 시각화 차트
│   ├── file_parser.py         # Excel/PDF 파서
│   ├── archive.py             # 회의록 저장 + 세션 체크포인트
│   └── demo_mock.py           # Mock 데모 (API 불필요)
├── tests/                     # pytest 테스트 스위트 (260 tests, E2E 포함)
├── meetings/                  # 회의록 저장 디렉토리
├── MANIFESTO.md                # 핵심 가치와 설계 원칙
├── WHYTREE.md                 # Why Tree 분석
├── PREMORTEM.md               # 사전 부검
├── COMPARISON.md              # ChatGPT 비교 시연 자료
└── glossary.md                # 용어집
```

---

## 설계 원칙 (MANIFESTO)

1. **출처 있는 숫자만 말한다** — CFO는 모든 수치에 `[출처: ___]` 필수
2. **각자의 자리에서 발언** — CFO는 숫자, CSO는 전략, 투자컨설턴트는 적합성 자문만
3. **예스맨 필요 없다** — CSO는 매 응답에 최소 1개 반론/리스크 제시
4. **대화로 끝나면 수다** — 비서실장이 Next Action (동사+담당자+기한) 강제

---

## 왜 텍스트 기반인가?

부동산 의사결정은 데이터 집약적이다:
- "3.2% vs 4.1% vs 2.8%" 수익률을 귀로 듣고 비교하기 어렵다
- 권역 비교표, 민감도 분석표는 시각적으로 봐야 한다
- Excel/PDF 첨부는 텍스트 채팅에서만 자연스럽다

---

## 배포

### VerifyHome — Render.com

`render.yaml` 기반 자동 배포. `main` 브랜치 push 시 자동 재배포.

```yaml
startCommand: uvicorn src.market_api:app --host 0.0.0.0 --port $PORT
```

### 멀티에이전트 — Streamlit Cloud

1. GitHub 리포지토리를 [Streamlit Cloud](https://share.streamlit.io)에 연결
2. Main file path: `src/app.py`
3. Secrets에 환경변수 추가:
   ```
   ANTHROPIC_API_KEY = "sk-ant-..."
   DATA_GO_KR_API_KEY = "..."
   ```

### 로컬 실행

```bash
pip install -r requirements.txt

# VerifyHome
uvicorn src.market_api:app --reload --port 8000

# 멀티에이전트
streamlit run src/app.py
```

### CI

GitHub Actions로 PR마다 `pytest tests/ -v` 자동 실행 (`.github/workflows/ci.yml`).
Python 3.10/3.11/3.12 매트릭스 테스트.

---

## 팀

KAIST IMMS (정보경영프로그램) MBA 과정 — AI 인공지능 전략과 실습
