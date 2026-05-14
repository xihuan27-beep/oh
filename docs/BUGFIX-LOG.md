# VerifyHome 버그 수정 및 UX 개선 로그

기준일: 2026-05-12  
브랜치: feat/ia-amenity

---

## 1. 데이터 파이프라인

### 1-1. 서버 env 미로드 (주소 검색 빈 결과)
- 증상: `/api/address-search` 항상 `{"results": []}` 반환
- 원인: uvicorn 실행 시 `.env` 파일이 자동 로드되지 않음
- 수정: `market_api.py` 상단에 `load_dotenv()` 추가
- 파일: `src/market_api.py`

### 1-2. 단지 데이터 all-zero (단지명 오매칭)
- 증상: 차트에서 단지 평단가가 36개월 전부 0
- 원인: JUSO의 `신동아아파트` vs MOLIT의 `신동아(22)` — 정확 일치 실패
- 수정: `normalize_apt_name()` 함수로 "아파트" 등 접미사 제거 후 부분 일치
- 파일: `src/market_api.py`

### 1-3. 평형 칩 오매칭 (타 동 건물 섞임)
- 증상: 논현동 신동아아파트 평형 조회 시 수서동·청담동 신동아 데이터 혼입
- 원인: `apt-sizes` 엔드포인트에 dong 필터 없음 → 강남구 전체에서 "신동아" 검색
- 수정: `apt-sizes`에 `dong` 파라미터 추가 + `market-data` complex 필터에도 dong 조건 추가
- 파일: `src/market_api.py`, `realestate-report/page0-web.html`
- 교훈: 단지명 부분 일치는 반드시 동(洞) 필터와 함께 사용해야 함

### 1-4. 건축년도 데이터 추가
- 배경: 신축 프리미엄이 가격 차이 설명의 핵심 팩터
- 수정: MOLIT 실거래 API 응답의 `buildYear` 필드 추출 → `market-data` 응답 및 챗봇 컨텍스트에 포함
- 형식: "논현동 신동아아파트 (26평, 1997년 준공)"
- 파일: `src/market_api.py`, `realestate-report/market-web.html`
- 주의: 세대수는 MOLIT 단지정보 API 권한 없어 미지원. 거래량은 세대수 proxy로 부적절 → 포기

---

## 2. 입지 분석

### 2-1. 좌표 없을 때 amenities 422 에러
- 증상: entX/entY 빈 문자열 전달 시 FastAPI 422 Unprocessable Entity
- 원인: 파라미터 타입이 `float` — 빈 문자열 파싱 실패
- 수정: `str` 타입으로 변경 후 try/except로 파싱, 실패 시 zero 반환
- 파일: `src/market_api.py`

### 2-2. 좌표 없을 때 학교·교통 데이터 0 → 챗봇 오답
- 증상: JUSO가 entX/entY를 안 줄 때 챗봇이 "학교 정보가 없습니다" 오답
- 원인: 좌표 없으면 모든 카운트가 0 → 챗봇이 데이터 부재로 해석
- 수정: `dong_name` 파라미터 추가, 서울 주요 동 36개의 중심 좌표 fallback 테이블 내장
- 적용 동: 강남구 13개 동, 서초구 6개, 송파구 6개, 강동구 3개, 마포구 4개 등
- 파일: `src/market_api.py`, `realestate-report/market-web.html`
- 한계: 동 중심 좌표는 약 500m 오차 가능. 건물 정확 좌표가 있으면 그게 우선

---

## 3. 차트 및 레이아웃

### 3-1. x축 연도 레이블 사라짐
- 증상: 36개월 차트에서 2024년/2025년/2026년 레이블 미표시
- 원인: Chart.js `autoSkip: true` (기본값)이 1월(.01) 레이블을 건너뜀
- 수정: `autoSkip: false` 추가 — callback이 직접 제어
- 파일: `realestate-report/market-web.html`

### 3-2. 차트 타이틀 하드코딩
- 증상: 11평 선택해도 "30평형대 평단가 추이" 표시
- 수정: `Math.floor(pyeong / 10) * 10` 계산으로 동적 표시
- 파일: `realestate-report/market-web.html`

### 3-3. 차트 스크롤 시 사라짐
- 수정: `.chart-card { position: sticky; top: 0; z-index: 10; }`
- 파일: `realestate-report/market-web.html`

### 3-4. 채팅창 대화 길어지면 계속 늘어남
- 증상: 채팅 메시지 추가될수록 오른쪽 컬럼 높이가 뷰포트 밖으로 확장
- 원인: `body`에 `min-height: 100vh` → 콘텐츠에 맞게 body 확장 가능
- 수정:
  - `html, body { height: 100vh; overflow: hidden; }`
  - `.right-col { min-height: 0; height: 100%; }`
  - `.chat-messages { min-height: 0; }`
- 파일: `realestate-report/market-web.html`
- 교훈: flex/grid 레이아웃에서 스크롤 고정은 `min-height: 0` + `overflow: hidden` 조합 필수

---

## 4. page0 UX

### 4-1. 없는 주소 입력해도 다음 페이지로 이동
- 증상: 자동완성 미선택 상태에서 검색 버튼 누르면 market-web으로 이동 → 데이터 없음
- 수정: `selectedJuso`가 null이면 이동 차단 + "목록에서 주소를 선택해주세요" 3초 에러 표시
- 파일: `realestate-report/page0-web.html`

### 4-2. 드롭다운 키보드 탐색 불가
- 수정: 방향키 위/아래로 항목 이동, Enter로 선택, `.focused` 하이라이트 스타일 추가
- 파일: `realestate-report/page0-web.html`

---

## 5. 챗봇 퀵 질문

### 5-1. 답변 불가 질문 제거
- 제거: "지금 사면 비싼 건가요?", "역삼동 대비 어때요?", "상승세 전망은?"
  - 이유: 매수 타이밍·미래 예측·하드코딩 동 이름 — 데이터로 답 불가
- 교체 (팩트 기반):
  - "왜 주변보다 비싸요?" → 입지·건축년도 데이터 기반 답변 가능
  - "교통은 어때요?" → subway_10min, highway_ic_3km
  - "학군은 어때요?" → school_1km, secondary_school_1km
  - "가격 차이 이유가 뭔가요?" → 동 비교 + 입지 차이

---

## 6. 챗봇 대화 품질 개선

### 6-1. 시스템 프롬프트 재설계
- 증상: 챗봇이 "입지 분석 데이터가 없어 ~" 같은 면피성 답변, 수치 없이 일반론만 나열
- 원인: 규칙 13개 나열 방식 — 어떤 답변이 좋은지 모델이 학습할 수 없음
- 수정: "팩트 먼저, 해석 뒤" 원칙 + 4개 few-shot 예시 (왜 비싸요/교통/학군/가격 차이)
- few-shot 예시 효과: 모델이 수치 밀도·해석 방식을 직접 학습 → 할루시네이션 없이 구체적 답변
- 파일: `src/market_api.py`

### 6-2. 입지 데이터 해석 기준 추가
- 증상: 지하철역 2개가 많은 건지 적은 건지 AI가 판단 못 함
- 수정: 시스템 프롬프트에 숫자별 판단 기준 명시
  - 지하철역(800m 내): 0개=불편, 1개=보통, 2+개=우수
  - 초등학교(1km 내): 0개=취약, 1개=보통, 2+개=양호
  - 중고등학교(1km 내): 2+개=학군 수요 지역
  - 혐오시설: "관련이 있을 수 있다" 수준으로만 언급
- 파일: `src/market_api.py`

### 6-3. 비교 동 입지 데이터 챗봇 주입
- 증상: 삼성동 추가해도 "삼성동과 가격 차이 원인을 알 수 없습니다" 답변
- 원인: 비교 동의 입지 데이터(교통·학군·인프라)가 챗봇 컨텍스트에 없었음
- 수정:
  - `toggleDong()` 실행 시 해당 동의 amenities도 함께 fetch (dong_name centroid fallback 활용)
  - `dongAmenities` 딕셔너리에 저장, 동 제거 시 함께 삭제
  - `/api/chat` 요청 body에 `dong_amenities` 필드로 전달
  - 백엔드 `/api/chat`에서 "비교 동 입지" 섹션으로 컨텍스트에 주입
- 효과: "삼성동(지하철 3개, 백화점 2개) vs 논현동(지하철 2개, 백화점 0개)" 비교 가능
- 파일: `src/market_api.py`, `realestate-report/market-web.html`

### 6-4. 볼드 마크다운 제거
- 증상: 챗봇 답변에 **굵은글씨** 남발로 가독성 저하
- 수정: 시스템 프롬프트에 "마크다운 볼드(**) 절대 사용 금지" 규칙 추가
- 파일: `src/market_api.py`

---

## 다음 버전 고려사항

| 항목 | 내용 |
|------|------|
| 세대수 데이터 | 단지정보 API 별도 권한 신청 필요 |
| entX/entY 보완 | JUSO 확장 API 또는 Kakao 지도 API geocoding |
| fallback 동 좌표 | 현재 서울 36개 동 — 비강남권 확장 필요 |
| 단지명 매칭 | 정규화 로직 edge case 보완 필요 (e.g. "래미안", "자이" 등 브랜드 포함 이름) |
| 챗봇 벤치마크 | 정답 케이스 5개 확보 후 프롬프트 자동 평가 루프 구축 필요 |
