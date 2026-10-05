"""Read public Stock Analysis history without executing third-party page code."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

import httpx
import pandas as pd

from app.services.market_data import MarketDataError, _clean_frame


class PublicHistoryProvider:
    name = "stockanalysis-spglobal"
    # Read the page's numeric history records only. Never evaluate its JavaScript.
    record = re.compile(
        r"\{a:([^,{}]+),c:([^,{}]+),h:([^,{}]+),l:([^,{}]+),o:([^,{}]+),"
        r't:"(\d{4}-\d{2}-\d{2})",v:([^,{}]+),ch:[^{}]+\}'
    )

    def history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        url = f"https://stockanalysis.com/etf/{quote(symbol.lower(), safe='')}/history/"
        try:
            response = httpx.get(url, timeout=25, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MarketDataError(f"公开行情页无法获取 {symbol}: {exc}") from exc
        identity = re.search(r'data:\{id:\d+,symbol:"([^\"]+)",source:"([^\"]+)"', response.text)
        if not identity or identity.group(1).upper() != symbol.upper():
            raise MarketDataError(f"公开行情页的品种身份与 {symbol} 不符")
        frame = self.parse(response.text, start, end)
        frame.attrs["source_url"] = url
        frame.attrs["provider"] = self.name
        return frame

    @classmethod
    def parse(cls, html: str, start: date, end: date) -> pd.DataFrame:
        rows = []
        for adjusted, close, high, low, opening, day, volume in cls.record.findall(html):
            try:
                stamp = date.fromisoformat(day)
                if start <= stamp <= end:
                    rows.append(
                        {
                            "date": stamp,
                            "open": float(opening),
                            "high": float(high),
                            "low": float(low),
                            "close": float(close),
                            "adjusted_close": float(adjusted),
                            "volume": float(volume),
                            "split_factor": 1.0,
                        }
                    )
            except ValueError as exc:
                raise MarketDataError("公开行情页包含无效数字") from exc
        if not rows:
            raise MarketDataError("公开行情页没有所需区间的完整日线，不会使用页面现价替代")
        frame = pd.DataFrame(rows).set_index("date")
        if frame.index.has_duplicates:
            raise MarketDataError("公开行情页包含重复日期")
        return _clean_frame(frame)
