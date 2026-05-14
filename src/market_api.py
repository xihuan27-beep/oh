"""
market_api.py — FastAPI 백엔드 for VerifyHome 시세 AI 챗봇 + 실거래 파이프라인

실행:
    uvicorn src.market_api:app --reload --port 8000
"""

import asyncio
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

app = FastAPI(title="VerifyHome Market API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

APT_TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
DATA_GO_KR_API_KEY = os.environ.get("DATA_GO_KR_API_KEY")
JUSO_CONFIRM_KEY = os.environ.get("JUSO_CONFIRM_KEY")
JUSO_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"

# 서울 25개 구 LAWD_CD
LAWD_CD_MAP: dict[str, str] = {
    "종로구": "11110", "중구": "11140", "용산구": "11170",
    "성동구": "11200", "광진구": "11215", "동대문구": "11230",
    "중랑구": "11260", "성북구": "11290", "강북구": "11305",
    "도봉구": "11320", "노원구": "11350", "은평구": "11380",
    "서대문구": "11410", "마포구": "11440", "양천구": "11470",
    "강서구": "11500", "구로구": "11530", "금천구": "11545",
    "영등포구": "11560", "동작구": "11590", "관악구": "11620",
    "서초구": "11650", "강남구": "11680", "송파구": "11710",
    "강동구": "11740",
}


# ── Request/Response 스키마 ──

class DongData(BaseModel):
    name: str
    data: list[float]

class ChartStats(BaseModel):
    complex_change_pct: float
    dong_change_pct: float
    complex_vs_dong_pct: float
    latest_complex: float
    latest_dong: float

class ChartContext(BaseModel):
    address: str = ""
    size_pyeong: int = 30
    months: list[str] = []
    complex: list[float] = []
    dong: list[float] = []
    active_dongs: list[DongData] = []
    stats: ChartStats | None = None

class HistoryMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    context: ChartContext
    history: list[HistoryMessage] = []

class ChatResponse(BaseModel):
    reply: str


# ── 실거래 API 헬퍼 ──

def get_last_n_months(n: int = 6) -> list[str]:
    """최근 n개의 완료된 월 YYYYMM 목록 (당월 제외)"""
    today = datetime.today()
    months = []
    for i in range(n, 0, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        months.append(f"{year}{month:02d}")
    return months


def parse_address(address: str) -> tuple[str, str, str | None]:
    """
    주소 문자열 → (lawd_cd, apt_name, dong_name)
    예) '강남구 역삼래미안' → ('11680', '역삼래미안', None)
        '역삼동 래미안아파트' → ('11680', '래미안아파트', '역삼동')  # 동 → 강남구 default
    """
    lawd_cd = "11680"  # gu 미인식 시 강남구 기본값
    remaining = address.strip()

    for gu, cd in LAWD_CD_MAP.items():
        if gu in remaining:
            lawd_cd = cd
            remaining = remaining.replace(gu, "").strip()
            break

    dong_name: str | None = None
    dong_match = re.search(r"(\S+동)", remaining)
    if dong_match:
        dong_name = dong_match.group(1)
        remaining = remaining.replace(dong_name, "").strip()

    # "서울시", "서울특별시" 등 불필요한 접두사 제거
    remaining = re.sub(r"^서울(특별)?시?\s*", "", remaining).strip()
    apt_name = remaining or address.strip()

    return lawd_cd, apt_name, dong_name


async def fetch_month_items(lawd_cd: str, deal_ymd: str) -> list[dict]:
    """단일 월 실거래 데이터 fetch → 정제된 항목 리스트 반환"""
    if not DATA_GO_KR_API_KEY:
        return []

    params = {
        "serviceKey": DATA_GO_KR_API_KEY,
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "numOfRows": "1000",
        "pageNo": "1",
    }
    async with httpx.AsyncClient(timeout=15) as hclient:
        res = await hclient.get(APT_TRADE_URL, params=params)

    try:
        root = ET.fromstring(res.text)
    except ET.ParseError:
        return []

    result = []
    for item in root.findall(".//item"):
        if item.findtext("cdealType", "").strip():  # 계약 해제 건 제외
            continue
        if item.findtext("landLeaseholdGbn", "").strip() == "Y":  # 지분거래 제외
            continue
        try:
            price = int(item.findtext("dealAmount", "0").replace(",", "").strip())
            area = float(item.findtext("excluUseAr", "0"))
            apt_nm = item.findtext("aptNm", "").strip()
            umd_nm = item.findtext("umdNm", "").strip()
        except (ValueError, AttributeError):
            continue

        if area <= 0 or price <= 0:
            continue

        pyeong = area / 3.3058
        result.append({
            "apt_nm": apt_nm,
            "umd_nm": umd_nm,
            "price": price,
            "area": area,
            "pyeong": round(pyeong, 1),
            "price_per_pyeong": round(price / pyeong),
        })

    return result


def filter_area(items: list[dict], min_p: float = 18, max_p: float = 26) -> list[dict]:
    return [i for i in items if min_p <= i["pyeong"] <= max_p]


def avg_ppp(items: list[dict]) -> float | None:
    """평균 평단가 (만원/평), 데이터 없으면 None"""
    if not items:
        return None
    return round(sum(i["price_per_pyeong"] for i in items) / len(items))


def forward_fill(lst: list[float | None]) -> list[float]:
    """None을 앞 값으로 채움. 앞에서도 None이면 뒤 값으로"""
    result: list[float | None] = list(lst)
    # forward pass
    last = None
    for i, v in enumerate(result):
        if v is not None:
            last = v
        elif last is not None:
            result[i] = last
    # backward pass (앞부분 None 처리)
    last = None
    for i in range(len(result) - 1, -1, -1):
        if result[i] is not None:
            last = result[i]
        elif last is not None:
            result[i] = last
    return [v or 0.0 for v in result]


def change_pct(data: list[float]) -> float:
    valid = [x for x in data if x]
    if len(valid) < 2:
        return 0.0
    return round((valid[-1] / valid[0] - 1) * 100, 1)


def month_label(yyyymm: str) -> str:
    return f"{yyyymm[:4]}.{yyyymm[4:]}"  # "202501" → "2025.01"


# ── 실거래 엔드포인트 ──

@app.get("/api/address-search")
async def address_search(keyword: str) -> dict:
    """주소 자동완성 — 프론트 검색창 debounce 호출용"""
    if not JUSO_CONFIRM_KEY or not keyword.strip():
        return {"results": []}

    async with httpx.AsyncClient(timeout=10) as hclient:
        res = await hclient.get(JUSO_URL, params={
            "confmKey": JUSO_CONFIRM_KEY,
            "currentPage": "1",
            "countPerPage": "10",
            "keyword": keyword,
            "resultType": "json",
        })

    try:
        jusos = res.json().get("results", {}).get("juso", []) or []
    except Exception:
        return {"results": []}

    return {
        "results": [
            {
                "roadAddr": j.get("roadAddr", ""),
                "jibunAddr": j.get("jibunAddr", ""),
                "bdNm": j.get("bdNm", ""),
                "admCd": j.get("admCd", ""),
            }
            for j in jusos
            if j.get("bdNm")  # 건물명 있는 것(아파트)만
        ]
    }


@app.get("/api/market-data")
async def market_data(
    address: str,
    lawd_cd: str | None = None,
    apt_name: str | None = None,
    dong: str | None = None,
    pyeong: int | None = None,
) -> dict:
    """주소 → 단지 + 동 평균 월별 평단가 (최근 6개월)"""
    # juso API에서 직접 받은 값이 있으면 파싱 건너뜀
    if lawd_cd and apt_name:
        dong_name = dong
    else:
        lawd_cd, apt_name, dong_name = parse_address(address)
    months_ym = get_last_n_months(36)

    all_items = await asyncio.gather(*[
        fetch_month_items(lawd_cd, ym) for ym in months_ym
    ])

    complex_prices: list[float | None] = []
    dong_prices: list[float | None] = []
    volume_counts: list[int] = []
    months_display: list[str] = []

    for ym, month_items in zip(months_ym, all_items):
        months_display.append(month_label(ym))

        # 평수 필터 범위 결정
        min_p = (pyeong - 2) if pyeong else 18
        max_p = (pyeong + 2) if pyeong else 26

        # 단지 데이터: aptNm 포함 + 면적 필터
        apt_items = filter_area([
            i for i in month_items if apt_name and apt_name in i["apt_nm"]
        ], min_p, max_p)

        # 동 평균: 동명 필터(있으면) + 면적 필터
        dong_items = month_items
        if dong_name:
            dong_items = [i for i in dong_items if i["umd_nm"] == dong_name]
        dong_items = filter_area(dong_items, min_p, max_p)

        complex_prices.append(avg_ppp(apt_items))
        dong_prices.append(avg_ppp(dong_items))
        # 거래량: 동 전체(면적 무관) 또는 단지 건수
        if dong_name:
            vol = len([i for i in month_items if i["umd_nm"] == dong_name])
        else:
            vol = len(apt_items)
        volume_counts.append(vol)

    complex_filled = forward_fill(complex_prices)
    dong_filled = forward_fill(dong_prices)

    latest_c = complex_filled[-1]
    latest_d = dong_filled[-1]
    vs_dong = round((latest_c / latest_d - 1) * 100, 1) if latest_d else 0.0

    return {
        "apt_name": apt_name,
        "dong_name": dong_name,
        "lawd_cd": lawd_cd,
        "months": months_display,
        "complex": complex_filled,
        "dong_avg": dong_filled,
        "volume": volume_counts,
        "stats": {
            "complex_change_pct": change_pct(complex_filled),
            "dong_change_pct": change_pct(dong_filled),
            "complex_vs_dong_pct": vs_dong,
            "latest_complex": latest_c,
            "latest_dong": latest_d,
        },
    }


@app.get("/api/apt-sizes")
async def apt_sizes(lawd_cd: str, apt_name: str) -> dict:
    """해당 아파트에서 실제 거래된 평수 목록 반환 (최근 3개월)"""
    months_ym = get_last_n_months(3)
    all_items = await asyncio.gather(*[
        fetch_month_items(lawd_cd, ym) for ym in months_ym
    ])
    sizes: set[int] = set()
    for month_items in all_items:
        for item in month_items:
            if apt_name in item["apt_nm"]:
                sizes.add(round(item["pyeong"]))
    return {"sizes": sorted(sizes)}


@app.get("/api/dong-data")
async def dong_data(lawd_cd: str, dong_name: str) -> dict:
    """특정 동의 월별 평균 평단가 (최근 6개월)"""
    months_ym = get_last_n_months(36)

    all_items = await asyncio.gather(*[
        fetch_month_items(lawd_cd, ym) for ym in months_ym
    ])

    prices: list[float | None] = []
    months_display: list[str] = []

    for ym, month_items in zip(months_ym, all_items):
        months_display.append(month_label(ym))
        dong_items = filter_area([
            i for i in month_items if i["umd_nm"] == dong_name
        ])
        prices.append(avg_ppp(dong_items))

    return {
        "dong_name": dong_name,
        "months": months_display,
        "data": forward_fill(prices),
    }


# ── 챗봇 헬퍼 ──

def build_context_str(ctx: ChartContext) -> str:
    months_str = ", ".join(ctx.months) if ctx.months else "최근 6개월"
    lines = [
        f"매물: {ctx.address} ({ctx.size_pyeong}평)",
        f"분석 기간: {months_str}",
        f"단지 평단가 추이: {ctx.complex} (만원/평)",
        f"동 평균 평단가: {ctx.dong} (만원/평)",
    ]
    if ctx.stats:
        s = ctx.stats
        lines += [
            f"단지 6개월 변화율: {s.complex_change_pct:+.1f}%",
            f"동 평균 변화율: {s.dong_change_pct:+.1f}%",
            f"단지 vs 동 평균: {s.complex_vs_dong_pct:+.1f}%",
            f"최신 단지 평단가: {s.latest_complex:,.0f}만원/평",
            f"최신 동 평균: {s.latest_dong:,.0f}만원/평",
        ]
    for d in ctx.active_dongs:
        pct = round((d.data[-1] / d.data[0] - 1) * 100, 1) if d.data and d.data[0] else 0
        lines.append(f"{d.name} 평단가: {d.data} / 6개월 변화: {pct:+.1f}%")
    return "\n".join(lines)


# ── 챗봇 엔드포인트 ──

SYSTEM_PROMPT_TEMPLATE = """\
당신은 VerifyHome의 시세 분석 AI입니다.
사용자가 매입을 고려 중인 아파트의 실거래가 차트 데이터를 분석해 궁금증에 답합니다.

## 역할
- 차트 데이터를 쉽게 해석해 주는 동네 부동산 전문가처럼 말합니다.
- "데이터를 보면 ~" 식으로 근거를 명시합니다.

## 현재 분석 대상 (이 수치만 사용)
{context_str}

## 답변 규칙
1. **할루시네이션 금지**: 위 데이터에 없는 수치는 절대 인용하지 않습니다.
2. **수치 근거 필수**: 모든 판단에 위 데이터의 숫자를 근거로 붙입니다.
3. **최대 5문장**: 간결하게.
4. **투자 권유 금지**: "사세요/파세요" 금지. "데이터상으로는 ~로 보입니다" 수준까지만.
5. **비교 동이 추가된 경우**: 추가된 동 데이터를 적극 활용해 비교 분석합니다.
6. **추세 예측 금지**: 과거·현재 데이터만 서술, 미래 전망은 하지 않습니다.
7. **이유·원인 질문** ("왜", "이유가", "원인이" 포함 시): "이유는 데이터만으로는 알 수 없지만, 추이를 말씀드리면 ~" 형식으로 자연스럽게 피봇합니다.
8. **한국어**로 답합니다.
"""


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    context_str = build_context_str(req.context)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context_str=context_str)

    messages: list[dict[str, Any]] = []
    for h in req.history[-10:]:
        if h.role in ("user", "assistant"):
            messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": req.message})

    response = await client.messages.create(
        model=os.environ.get("LLM_MODEL", "claude-sonnet-4-6"),
        max_tokens=512,
        system=system_prompt,
        messages=messages,
    )
    reply = response.content[0].text if response.content else "잠시 후 다시 시도해주세요."
    return ChatResponse(reply=reply)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
