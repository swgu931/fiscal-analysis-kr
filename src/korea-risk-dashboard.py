# korea_risk_dashboard.py
# pip install requests pandas yfinance python-dotenv

import os
import datetime as dt
import requests
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
BOK_API_KEY = os.getenv("BOK_API_KEY", "")
TRADING_ECONOMICS_KEY = os.getenv("TRADING_ECONOMICS_KEY", "")

TODAY = dt.date.today().isoformat()


def latest_yfinance(ticker: str):
    data = yf.download(ticker, period="10d", interval="1d", progress=False)
    if data.empty:
        return None
    return float(data["Close"].dropna().iloc[-1])


def latest_fred(series_id: str):
    if not FRED_API_KEY:
        return None

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5,
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()

    for obs in r.json()["observations"]:
        if obs["value"] != ".":
            return float(obs["value"])
    return None


def ecos_latest(stat_code, item_code, cycle="D"):
    """
    한국은행 ECOS용 함수.
    stat_code, item_code는 ECOS에서 직접 확인 후 넣어야 함.
    """
    if not BOK_API_KEY:
        return None

    end = dt.date.today()
    start = end - dt.timedelta(days=30)

    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/"
        f"{BOK_API_KEY}/json/kr/1/100/"
        f"{stat_code}/{cycle}/{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}/{item_code}"
    )

    r = requests.get(url, timeout=10)
    r.raise_for_status()
    rows = r.json().get("StatisticSearch", {}).get("row", [])

    if not rows:
        return None

    return float(rows[-1]["DATA_VALUE"])


def get_korea_cds():
    """
    Trading Economics API Key 필요.
    없으면 None 반환.
    """
    if not TRADING_ECONOMICS_KEY:
        return None

    url = (
        "https://api.tradingeconomics.com/markets/cds/country/south%20korea"
        f"?c={TRADING_ECONOMICS_KEY}"
    )

    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    if not data:
        return None

    return float(data[0].get("Last", 0))


def score_dashboard(values):
    score = 100
    warnings = []

    usdkrw = values.get("USD/KRW")
    if usdkrw:
        if usdkrw > 1450:
            score -= 15
            warnings.append("원달러 환율 1450원 초과")
        elif usdkrw > 1350:
            score -= 7
            warnings.append("원달러 환율 1350원 초과")

    us10y = values.get("US 10Y")
    if us10y:
        if us10y > 5.0:
            score -= 10
            warnings.append("미국 10년물 금리 5% 초과")
        elif us10y > 4.5:
            score -= 5
            warnings.append("미국 10년물 금리 4.5% 초과")

    dxy = values.get("DXY")
    if dxy:
        if dxy > 110:
            score -= 10
            warnings.append("달러지수 DXY 110 초과")
        elif dxy > 105:
            score -= 5
            warnings.append("달러 강세 구간")

    kr3y = values.get("Korea 3Y Bond")
    if kr3y:
        if kr3y > 4.0:
            score -= 10
            warnings.append("한국 3년 국채금리 4% 초과")
        elif kr3y > 3.5:
            score -= 5
            warnings.append("한국 3년 국채금리 상승 구간")

    cds = values.get("Korea CDS")
    if cds:
        if cds > 80:
            score -= 15
            warnings.append("한국 CDS 80bp 초과")
        elif cds > 50:
            score -= 7
            warnings.append("한국 CDS 50bp 초과")

    short_debt_ratio = values.get("Short Debt / FX Reserves")
    if short_debt_ratio:
        if short_debt_ratio > 60:
            score -= 15
            warnings.append("단기외채/외환보유액 60% 초과")
        elif short_debt_ratio > 40:
            score -= 7
            warnings.append("단기외채/외환보유액 40% 초과")

    foreign_flow = values.get("Foreign Net Buy")
    if foreign_flow is not None:
        if foreign_flow < -5000:
            score -= 10
            warnings.append("외국인 대규모 순매도")
        elif foreign_flow < 0:
            score -= 5
            warnings.append("외국인 순매도")

    score = max(score, 0)

    if score >= 80:
        level = "안전"
    elif score >= 60:
        level = "주의"
    elif score >= 40:
        level = "경계"
    else:
        level = "위험"

    return score, level, warnings


def main():
    values = {}

    # 1. USD/KRW
    values["USD/KRW"] = latest_yfinance("KRW=X")

    # 2. 한국 CDS
    values["Korea CDS"] = get_korea_cds()

    # 3. 미국 10년물 금리
    values["US 10Y"] = latest_fred("DGS10") or latest_yfinance("^TNX") / 10

    # 4. DXY 달러지수
    values["DXY"] = latest_yfinance("DX-Y.NYB")

    # 5. 외국인 순매수
    # KRX API 또는 pykrx로 추후 구현 추천
    values["Foreign Net Buy"] = None

    # 6. 한국 3년 국채금리
    # ECOS 코드 확인 후 입력 필요
    # 예: values["Korea 3Y Bond"] = ecos_latest("817Y002", "010200000", "D")
    values["Korea 3Y Bond"] = None

    # 7. 단기외채 / 외환보유액 비율
    # ECOS 또는 기재부 외채 통계 코드 확인 후 구현
    values["Short Debt / FX Reserves"] = None

    score, level, warnings = score_dashboard(values)

    df = pd.DataFrame(
        [
            {
                "date": TODAY,
                "indicator": k,
                "value": v,
            }
            for k, v in values.items()
        ]
    )

    df.to_csv("korea_risk_daily.csv", index=False, encoding="utf-8-sig")

    print("\n🇰🇷 한국 국가위험도 Daily Dashboard")
    print("=" * 40)

    for k, v in values.items():
        print(f"{k:30s}: {v}")

    print("=" * 40)
    print(f"Risk Score : {score}/100")
    print(f"Risk Level : {level}")

    if warnings:
        print("\n주의 신호:")
        for w in warnings:
            print(f"- {w}")
    else:
        print("\n특별한 위험 신호 없음")

    print("\nCSV 저장 완료: korea_risk_daily.csv")


if __name__ == "__main__":
    main()
