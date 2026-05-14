"""
market_api.py — FastAPI 백엔드 for VerifyHome 시세 AI 챗봇 + 실거래 파이프라인

실행:
    uvicorn src.market_api:app --reload --port 8000
"""

import asyncio
import json
import math
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import anthropic

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

app = FastAPI(title="VerifyHome Market API")

_REPORT_DIR = Path(__file__).resolve().parent.parent / "realestate-report"

@app.get("/")
async def index():
    return FileResponse(_REPORT_DIR / "page0-web.html")

@app.get("/market")
async def market():
    return FileResponse(_REPORT_DIR / "market-web.html")

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

# 정적 JSON 파일 경로 (API 호출 불필요 — 하드코딩)
_SRC = os.path.dirname(__file__)
_APT_DB_PATH = os.path.join(_SRC, "apartment.db")
_SUBWAY_JSON           = os.path.join(_SRC, "subway_stations.json")
_SCHOOL_JSON           = os.path.join(_SRC, "elementary_schools.json")
_SECONDARY_SCHOOL_JSON = os.path.join(_SRC, "secondary_schools.json")
_HOSPITAL_JSON         = os.path.join(_SRC, "hospitals.json")
_PARK_JSON             = os.path.join(_SRC, "parks.json")
_HIGHWAY_IC_JSON       = os.path.join(_SRC, "highway_ics.json")
_DISAMENITY_JSON       = os.path.join(_SRC, "disamenities.json")
_LARGE_STORE_JSON      = os.path.join(_SRC, "large_stores.json")
_subway_coords_cache: list[tuple[float, float]] | None = None

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
    build_year: str | None = None
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
    amenity_summary: str = ""
    dong_amenities: dict[str, str] = {}  # 비교 동별 입지 요약

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
    lawd_cd = LAWD_CD_MAP["강남구"]  # gu 미인식 시 강남구 기본값
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
    """단일 월 실거래 데이터 fetch → 정제된 항목 리스트 반환.
    네트워크 오류 / API 응답 이상 시 빈 리스트 반환 (호출자 asyncio.gather가 실패하지 않도록).
    """
    if not DATA_GO_KR_API_KEY:
        return []

    params = {
        "serviceKey": DATA_GO_KR_API_KEY,
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "numOfRows": "1000",
        "pageNo": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as hclient:
            res = await hclient.get(APT_TRADE_URL, params=params)
    except Exception:
        return []  # 타임아웃 / 네트워크 오류 — 해당 월은 빈 결과로 처리

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
            build_year = item.findtext("buildYear", "").strip()
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
            "build_year": build_year,
        })

    return result


def normalize_apt_name(name: str) -> str:
    """아파트명 정규화: 공통 접미사 제거 후 핵심 명칭만 추출"""
    suffixes = ["아파트", "빌라", "단지", "APT", "apt", "주상복합", "오피스텔"]
    result = name.strip()
    for s in suffixes:
        if result.endswith(s):
            result = result[: -len(s)].strip()
            break
    return result


def filter_apt(items: list[dict], apt_name: str) -> list[dict]:
    """단지명 매칭 (정규화된 이름으로 부분 일치)"""
    core = normalize_apt_name(apt_name)
    if not core:  # 빈 문자열이면 전체 매칭을 막음 (e.g. "아파트"만 입력 시 방지)
        return []
    return [i for i in items if core in i["apt_nm"]]


def filter_area(items: list[dict], min_p: float = 18, max_p: float = 26) -> list[dict]:
    return [i for i in items if min_p <= i["pyeong"] <= max_p]


def avg_ppp(items: list[dict]) -> float | None:
    """평균 평단가 (만원/평), 데이터 없으면 None"""
    if not items:
        return None
    return round(sum(i["price_per_pyeong"] for i in items) / len(items))


def calc_ma(prices: list[float | None], counts: list[int], window: int = 3, min_count: int = 2) -> list[float | None]:
    """3개월 이동평균. min_count 미만 거래 월은 계산에서 제외 → None 반환"""
    filtered = [
        p if (c >= min_count and p is not None) else None
        for p, c in zip(prices, counts)
    ]
    result: list[float | None] = []
    for i in range(len(filtered)):
        window_vals = [v for v in filtered[max(0, i - window + 1): i + 1] if v is not None]
        result.append(round(sum(window_vals) / len(window_vals)) if window_vals else None)
    return result


def _last_valid(series: list[float | None]) -> float:
    for v in reversed(series):
        if v is not None:
            return v
    return 0.0


def change_pct(data: list[float]) -> float:
    valid = [x for x in data if x is not None]
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
                "entX": j.get("entX", ""),  # 건물 입구 X좌표 (UTM-K)
                "entY": j.get("entY", ""),  # 건물 입구 Y좌표 (UTM-K)
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

    complex_raw: list[dict] = []  # 건별 원시 거래 {mi: month_index, v: price_per_pyeong}
    dong_raw: list[dict] = []     # 동 전체 건별 거래 (scatter용)
    dong_count_map: dict[str, int] = {}  # 동별 거래 건수 (칩 필터링용)
    complex_prices: list[float | None] = []
    dong_prices: list[float | None] = []
    complex_counts: list[int] = []
    dong_counts: list[int] = []
    months_display: list[str] = []

    for ym_idx, (ym, month_items) in enumerate(zip(months_ym, all_items)):
        months_display.append(month_label(ym))

        min_p = (pyeong - 2) if pyeong else 18
        max_p = (pyeong + 2) if pyeong else 26

        candidates = filter_apt(month_items, apt_name) if apt_name else month_items
        if dong_name:
            candidates = [i for i in candidates if i["umd_nm"] == dong_name]
        apt_items = filter_area(candidates, min_p, max_p)

        dong_items = month_items
        if dong_name:
            dong_items = [i for i in dong_items if i["umd_nm"] == dong_name]
        dong_items = filter_area(dong_items, min_p, max_p)

        complex_prices.append(avg_ppp(apt_items))
        dong_prices.append(avg_ppp(dong_items))
        complex_counts.append(len(apt_items))
        dong_counts.append(len(dong_items))

        for item in apt_items:
            complex_raw.append({"mi": ym_idx, "v": item["price_per_pyeong"]})
        for item in dong_items:
            dong_raw.append({"mi": ym_idx, "v": item["price_per_pyeong"]})

        # 동별 거래 건수 집계 (칩 필터링용 — 전 동, 평형 필터 적용)
        for item in filter_area(month_items, min_p, max_p):
            dn = item["umd_nm"]
            dong_count_map[dn] = dong_count_map.get(dn, 0) + 1

    complex_ma = calc_ma(complex_prices, complex_counts)
    dong_ma = calc_ma(dong_prices, dong_counts)

    latest_c = _last_valid(complex_ma)
    latest_d = _last_valid(dong_ma)
    vs_dong = round((latest_c / latest_d - 1) * 100, 1) if latest_d else 0.0

    all_complex_items = [
        i for month_items in all_items
        for i in filter_area(
            [j for j in (filter_apt(month_items, apt_name) if apt_name else month_items)
             if dong_name is None or j["umd_nm"] == dong_name],
            (pyeong - 2) if pyeong else 18,
            (pyeong + 2) if pyeong else 26,
        )
    ]
    build_years = [i["build_year"] for i in all_complex_items if i.get("build_year")]
    build_year = max(set(build_years), key=build_years.count) if build_years else None

    return {
        "apt_name": apt_name,
        "dong_name": dong_name,
        "lawd_cd": lawd_cd,
        "build_year": build_year,
        "months": months_display,
        "complex_raw": complex_raw,
        "complex_ma": complex_ma,
        "dong_raw": dong_raw,
        "dong_ma": dong_ma,
        "dong_counts": dong_count_map,
        "stats": {
            "complex_change_pct": change_pct(complex_ma),
            "dong_change_pct": change_pct(dong_ma),
            "complex_vs_dong_pct": vs_dong,
            "latest_complex": latest_c,
            "latest_dong": latest_d,
        },
    }


@app.get("/api/apt-match")
async def apt_match(bd_nm: str, sgg_cd: str, dong: str | None = None) -> dict:
    """
    JUSO bdNm + admCd(앞 5자리) + dong(선택) → apartment.db 매칭 → WGS84 lat/lng 반환.
    DB가 없거나 매칭 실패 시 빈 dict 반환 (프론트가 dong centroid fallback 처리).
    매칭 우선순위: 구+동+이름 > 구+이름 > 이름만
    """
    if not os.path.exists(_APT_DB_PATH):
        return {}

    core = normalize_apt_name(bd_nm)
    if not core:
        return {}

    def _query() -> dict:
        con = sqlite3.connect(_APT_DB_PATH)
        try:
            cur = con.cursor()
            # 1순위: 구 + 동 + 이름 (가장 정확)
            if dong:
                cur.execute(
                    """
                    SELECT apt_seq, apt_nm, umd_nm, lat, lng
                    FROM apartment_complexes
                    WHERE sgg_cd = ?
                      AND umd_nm = ?
                      AND geocoded = 1
                      AND apt_nm LIKE ?
                    ORDER BY length(apt_nm) ASC
                    LIMIT 1
                    """,
                    (sgg_cd, dong, f"%{core}%"),
                )
                row = cur.fetchone()
                if row:
                    return {"apt_seq": row[0], "apt_nm": row[1], "umd_nm": row[2], "lat": row[3], "lng": row[4]}

            # 2순위: 구 + 이름
            cur.execute(
                """
                SELECT apt_seq, apt_nm, umd_nm, lat, lng
                FROM apartment_complexes
                WHERE sgg_cd = ?
                  AND geocoded = 1
                  AND apt_nm LIKE ?
                ORDER BY length(apt_nm) ASC
                LIMIT 1
                """,
                (sgg_cd, f"%{core}%"),
            )
            row = cur.fetchone()
            if row:
                return {"apt_seq": row[0], "apt_nm": row[1], "umd_nm": row[2], "lat": row[3], "lng": row[4]}

            # 3순위: 이름만 (구 코드 오류 등 대비)
            cur.execute(
                """
                SELECT apt_seq, apt_nm, umd_nm, lat, lng
                FROM apartment_complexes
                WHERE geocoded = 1
                  AND apt_nm LIKE ?
                ORDER BY length(apt_nm) ASC
                LIMIT 1
                """,
                (f"%{core}%",),
            )
            row = cur.fetchone()
            if row:
                return {"apt_seq": row[0], "apt_nm": row[1], "umd_nm": row[2], "lat": row[3], "lng": row[4]}
        finally:
            con.close()
        return {}

    # sqlite3는 동기 I/O → 스레드풀로 분리
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _query)


@app.get("/api/apt-sizes")
async def apt_sizes(lawd_cd: str, apt_name: str, dong: str | None = None) -> dict:
    """해당 아파트에서 실제 거래된 평수 목록 반환 (최근 3개월)"""
    months_ym = get_last_n_months(3)
    all_items = await asyncio.gather(*[
        fetch_month_items(lawd_cd, ym) for ym in months_ym
    ])
    sizes: set[int] = set()
    for month_items in all_items:
        candidates = filter_apt(month_items, apt_name)
        if dong:
            candidates = [i for i in candidates if i["umd_nm"] == dong]
        for item in candidates:
            sizes.add(round(item["pyeong"]))
    return {"sizes": sorted(sizes)}


@app.get("/api/dong-data")
async def dong_data(lawd_cd: str, dong_name: str, pyeong: int | None = None) -> dict:
    """특정 동의 월별 평균 평단가 (최근 36개월). pyeong 지정 시 ±2평 필터 적용."""
    months_ym = get_last_n_months(36)

    all_items = await asyncio.gather(*[
        fetch_month_items(lawd_cd, ym) for ym in months_ym
    ])

    raw: list[dict] = []
    prices: list[float | None] = []
    counts: list[int] = []
    months_display: list[str] = []

    for ym_idx, (ym, month_items) in enumerate(zip(months_ym, all_items)):
        months_display.append(month_label(ym))
        min_p = (pyeong - 2) if pyeong else 18
        max_p = (pyeong + 2) if pyeong else 26
        dong_items = filter_area([
            i for i in month_items if i["umd_nm"] == dong_name
        ], min_p=min_p, max_p=max_p)
        prices.append(avg_ppp(dong_items))
        counts.append(len(dong_items))
        for item in dong_items:
            raw.append({"mi": ym_idx, "v": item["price_per_pyeong"]})

    return {
        "dong_name": dong_name,
        "months": months_display,
        "ma": calc_ma(prices, counts),
        "raw": raw,
        "total_count": sum(counts),
    }


# ── 생활편의 헬퍼 ──

def _utm_k_to_wgs84(ent_x: float, ent_y: float) -> tuple[float, float]:
    """UTM-K (EPSG:5179) → 근사 WGS84 (lat, lon). 서울 기준 오차 < 200m."""
    lon = (ent_x - 200_000) / 88_128 + 127.0
    lat = (ent_y - 600_000) / 111_320 + 38.0
    return lat, lon


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 WGS84 좌표 간 거리 (미터)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _count_within(coords: list[tuple[float, float]], lat: float, lon: float, radius_m: float) -> int:
    return sum(1 for plat, plon in coords if _haversine_m(lat, lon, plat, plon) <= radius_m)


def _get_subway_coords() -> list[tuple[float, float]]:
    """서울 지하철역 좌표 — 정적 JSON 파일에서 로드 (API 불필요)."""
    global _subway_coords_cache
    if _subway_coords_cache is not None:
        return _subway_coords_cache
    try:
        with open(_SUBWAY_JSON, encoding="utf-8") as f:
            stations = json.load(f)
        _subway_coords_cache = [(s["lat"], s["lon"]) for s in stations]
    except Exception:
        _subway_coords_cache = []
    return _subway_coords_cache


# 모듈 로드 시 한 번만 읽는 정적 JSON 캐시 (요청마다 파일 재읽기 방지)
_static_coord_cache: dict[str, list[tuple[float, float]]] = {}
_static_json_cache: dict[str, list[dict]] = {}


def _load_static_json(path: str) -> list[dict]:
    if path not in _static_json_cache:
        try:
            with open(path, encoding="utf-8") as f:
                _static_json_cache[path] = json.load(f)
        except Exception:
            _static_json_cache[path] = []
    return _static_json_cache[path]


def _count_type_within(items: list[dict], lat: float, lon: float, type_val: str, radius_m: float) -> int:
    return sum(
        1 for item in items
        if item.get("type") == type_val
        and _haversine_m(lat, lon, item["lat"], item["lon"]) <= radius_m
    )


def _load_static_coords(path: str) -> list[tuple[float, float]]:
    """정적 JSON 파일에서 좌표 로드 (모듈 레벨 캐시 사용)."""
    if path not in _static_coord_cache:
        try:
            with open(path, encoding="utf-8") as f:
                _static_coord_cache[path] = [(s["lat"], s["lon"]) for s in json.load(f)]
        except Exception:
            _static_coord_cache[path] = []
    return _static_coord_cache[path]


# 동 이름 → 중심 좌표 fallback (entX/entY 없을 때)
# seoul-amenity 패키지에서 로드 (dong_centroids.json 있으면 ~467개, 없으면 42개 하드코드)
try:
    from seoul_amenity.lookup import _get_dong_centroids as _sa_get_centroids
    _DONG_CENTROIDS: dict[str, tuple[float, float]] = _sa_get_centroids()
except ImportError:
    # seoul-amenity 미설치 시 빈 dict → entX/entY fallback만 동작
    _DONG_CENTROIDS = {}


@app.get("/api/nearby-amenities")
async def nearby_amenities(
    entX: str = "",
    entY: str = "",
    lat: float | None = None,
    lng: float | None = None,
    dong_name: str = "",
    radius_m: float = 1000,
) -> dict:
    """
    건물 좌표 기준 반경 내 생활편의 카운트.
    우선순위: lat/lng (apartment.db WGS84) > entX/entY (UTM-K 변환) > dong_name centroid.
    """
    lat_v, lon = None, None
    if lat is not None and lng is not None:
        lat_v, lon = lat, lng
    else:
        try:
            lat_v, lon = _utm_k_to_wgs84(float(entX), float(entY))
        except (ValueError, TypeError):
            pass
    if lat_v is None and dong_name and dong_name in _DONG_CENTROIDS:
        lat_v, lon = _DONG_CENTROIDS[dong_name]

    if lat_v is None:
        return {"error": "no_coords", "subway_10min": 0, "school_1km": 0,
                "secondary_school_1km": 0, "hospital_2km": 0, "park_1km": 0,
                "highway_ic_3km": 0, "crematorium_3km": 0, "waste_plant_2km": 0,
                "highvoltage_500m": 0, "industrial_1km": 0, "prison_1km": 0,
                "military_1km": 0, "emart_2km": 0, "dept_store_3km": 0}

    # 모두 정적 JSON — API 키 불필요
    subway_count           = _count_within(_get_subway_coords(),                          lat_v, lon, 800)       # 도보 10분=800m
    school_count           = _count_within(_load_static_coords(_SCHOOL_JSON),            lat_v, lon, radius_m)
    secondary_school_count = _count_within(_load_static_coords(_SECONDARY_SCHOOL_JSON),  lat_v, lon, radius_m)
    hospital_count         = _count_within(_load_static_coords(_HOSPITAL_JSON),          lat_v, lon, 2000)       # 병원은 2km
    park_count             = _count_within(_load_static_coords(_PARK_JSON),              lat_v, lon, radius_m)
    ic_count               = _count_within(_load_static_coords(_HIGHWAY_IC_JSON),        lat_v, lon, 3000)       # IC는 3km

    stores = _load_static_json(_LARGE_STORE_JSON)
    emart_count  = _count_type_within(stores, lat_v, lon, "이마트", 2000)   # 2km (생활마트)
    dept_count   = _count_type_within(stores, lat_v, lon, "백화점", 3000)   # 3km (목적 쇼핑)

    disam = _load_static_json(_DISAMENITY_JSON)
    crematorium_count  = _count_type_within(disam, lat_v, lon, "화장장",      3000)  # 심리적 영향 3km
    waste_count        = _count_type_within(disam, lat_v, lon, "쓰레기처리장", 2000)  # 냄새 2km
    highvoltage_count  = _count_type_within(disam, lat_v, lon, "고압시설",     500)   # 전자파·경관 500m
    industrial_count   = _count_type_within(disam, lat_v, lon, "공장지역",    1000)  # 소음·냄새 1km
    prison_count       = _count_type_within(disam, lat_v, lon, "교도소",      1000)  # 기피 1km
    military_count     = _count_type_within(disam, lat_v, lon, "군부대",      1000)  # 소음·개발제한 1km

    return {
        "lat": lat_v,
        "lon": lon,
        "radius_m": int(radius_m),
        "subway_10min":         subway_count,
        "school_1km":           school_count,
        "secondary_school_1km": secondary_school_count,
        "hospital_2km":         hospital_count,
        "park_1km":             park_count,
        "highway_ic_3km":       ic_count,
        "crematorium_3km":      crematorium_count,
        "waste_plant_2km":      waste_count,
        "highvoltage_500m":     highvoltage_count,
        "industrial_1km":       industrial_count,
        "prison_1km":           prison_count,
        "military_1km":         military_count,
        "emart_2km":            emart_count,
        "dept_store_3km":       dept_count,
    }


# ── 챗봇 헬퍼 ──

def build_context_str(ctx: ChartContext) -> str:
    build_info = f" · {ctx.build_year}년 준공" if ctx.build_year else ""
    lines = [f"## 분석 대상: {ctx.address} ({ctx.size_pyeong}평형{build_info})"]

    if ctx.stats:
        s = ctx.stats
        lc = s.latest_complex
        ld = s.latest_dong
        diff_pct = s.complex_vs_dong_pct

        if lc > 0:
            premium = "높음" if diff_pct > 10 else ("낮음" if diff_pct < -5 else "비슷함")
            lines.append(
                f"현재 단지 평단가 {lc:,.0f}만원/평 — 동 평균({ld:,.0f}만원/평) 대비 {diff_pct:+.1f}% ({premium})"
            )
            if abs(s.complex_change_pct) > 1:
                lines.append(f"단지 36개월 변화: {s.complex_change_pct:+.1f}% · 동 평균: {s.dong_change_pct:+.1f}%")
        else:
            lines.append(f"동 평균 평단가: {ld:,.0f}만원/평 (단지 거래 없음)")

    for d in ctx.active_dongs:
        vals = [v for v in d.data if v > 0]
        if vals:
            latest = vals[-1]
            pct = round((vals[-1] / vals[0] - 1) * 100, 1) if len(vals) > 1 else 0
            lines.append(f"비교 동 [{d.name}]: {latest:,.0f}만원/평 (변화 {pct:+.1f}%)")

    return "\n".join(lines)


# ── 챗봇 엔드포인트 ──

SYSTEM_PROMPT_TEMPLATE = """\
당신은 VerifyHome의 시세 분석 AI입니다. 사용자가 매입 검토 중인 아파트의 실거래·입지 데이터를 해석해 팩트 기반 답변을 드립니다.

## 현재 분석 데이터
{context_str}

## 입지 데이터 해석 기준 (입지 데이터가 제공된 경우에만 적용)
- 지하철역(도보 10분/800m 내): 0개=교통 불편, 1개=보통, 2개+=교통 우수
- 초등학교(1km 내): 0개=학군 취약, 1개=보통, 2개+=학군 양호
- 중고등학교(1km 내): 2개+=학군 수요 지역
- 병원(2km 내): 3개+=의료 인프라 양호
- 공원(1km 내): 2개+=자연환경 양호
- 혐오시설: 화장장·쓰레기처리장=심리적 기피, 고압시설=전자기파 우려, 공장=소음·매연, 교도소·군부대=이미지 요인 — "관련이 있을 수 있다" 수준으로만 언급

## 답변 원칙
1. 수치 근거 필수: 위 데이터의 숫자를 반드시 인용. 데이터에 없는 수치는 절대 만들지 않는다.
2. 팩트 먼저, 해석 뒤: "단지 평단가 X만원/평으로 동 평균(Y만원)보다 Z% 높음 → 이는 ~와 관련이 있을 수 있습니다"
3. 3~4문장: 핵심만 간결하게.
4. 투자 권유·미래 예측 금지: "데이터상으로는 ~로 보입니다" 수준까지만.
5. 비교 동 데이터가 있으면 반드시 비교 수치를 인용한다.
6. 마크다운 볼드(**)는 절대 사용하지 않는다.

## 답변 예시 (이 수준의 수치 밀도와 해석 방식을 유지하세요)

Q: 왜 주변보다 비싸요?
A: 논현동 신동아아파트(10평형)는 현재 4,200만원/평으로 논현동 평균(3,900만원)보다 +7.7% 높게 형성되어 있습니다. 입지를 보면 도보 10분 내 지하철역이 2개로 교통 접근성이 우수하고, 초등학교 2개·중고등학교 1개가 위치해 학군 수요가 있는 지역입니다. 1997년 준공으로 건물은 오래됐지만 교통·학군 프리미엄이 가격을 받쳐주고 있는 것으로 볼 수 있습니다.

Q: 교통은 어때요?
A: 입지 데이터 기준으로 도보 10분(800m) 내 지하철역이 2개 있어 교통 접근성이 양호한 편입니다. 고속도로IC는 3km 내 1개로 자차 이용도 가능합니다. 강남권 일반 주거지역의 평균(1~2개)과 비슷한 수준입니다.

Q: 학군은 어때요?
A: 1km 내 초등학교 2개, 중고등학교 1개가 있어 기본적인 학군 수요가 있는 지역입니다. 중고등학교 1개는 대치동(3개)·역삼동(2개) 대비 학원가 밀집도나 입시 수요 측면에서 다소 제한적일 수 있습니다. 정확한 학업 성취도는 이 데이터로는 알 수 없으니 실거주 전 직접 확인을 권장합니다.

Q: 가격 차이 이유가 뭔가요?
A: 차트를 보면 삼성동(현재 6,000만원/평)이 논현동 신동아(4,200만원/평)보다 +43% 높습니다. 삼성동 입지는 지하철역 3개, 백화점 2개로 생활 인프라가 풍부한 반면 논현동은 지하철역 2개, 백화점 0개입니다. 코엑스·테헤란로 상업지구 인접이라는 삼성동 고유의 수요가 가격 차이의 주요 요인 중 하나로 볼 수 있습니다.

---

한국어로 답합니다.
"""


def _sanitize_data_field(text: str, max_len: int = 500) -> str:
    """클라이언트 데이터 필드를 시스템 프롬프트에 삽입하기 전에 정제.
    - 길이 제한: 프롬프트 인젝션용 긴 텍스트 차단
    - '##' 제거: 마크다운 헤더로 시스템 프롬프트 구조를 주입하는 시도 차단
    """
    sanitized = text.replace("##", "").replace("\x00", "").strip()
    return sanitized[:max_len]


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    context_str = build_context_str(req.context)
    if req.amenity_summary:
        safe_summary = _sanitize_data_field(req.amenity_summary)
        context_str += f"\n\n## 분석 대상 입지\n{safe_summary}"
    if req.dong_amenities:
        parts = [
            f"[{_sanitize_data_field(dong, 30)}] {_sanitize_data_field(summary)}"
            for dong, summary in list(req.dong_amenities.items())[:5]  # 최대 5개 동
        ]
        context_str += "\n\n## 비교 동 입지\n" + "\n".join(parts)
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
