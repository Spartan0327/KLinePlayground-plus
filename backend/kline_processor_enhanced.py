from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class KLineProcessorEnhanced:
    """负责训练视图中的 K 线、复权、指标与筹码分布计算。"""

    def __init__(
        self,
        data_manager,
        stock_code: str,
        start_date: str,
        source: str = "akshare",
        interval: str = "daily",
        end_date: Optional[str] = None,
    ):
        self.data_manager = data_manager
        self.stock_code = stock_code
        self.source = source
        self.interval = interval
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date) if end_date else None
        self.adjustment_mode = "forward"
        self.factor_changed = False

        self.raw_data = data_manager.get_stock_data(stock_code, source=source, interval=interval)
        self.factor_data = data_manager.get_factor_data(stock_code, source=source, interval=interval)
        self.dividend_data = data_manager.get_dividend_data(stock_code)

        if self.raw_data is None or self.raw_data.empty:
            raise ValueError(f"无法获取股票 {stock_code} 的数据")

        self.raw_data = self.raw_data.sort_values("date").reset_index(drop=True)
        start_mask = self.raw_data["date"] >= self.start_date
        if not start_mask.any():
            raise ValueError(f"起始日期 {start_date} 之后没有数据")

        self.start_index = int(start_mask.idxmax())
        self.preview_start_index = max(0, self.start_index - 80)
        self.full_data = self.raw_data.iloc[self.preview_start_index :].copy().reset_index(drop=True)
        if self.full_data.empty:
            raise ValueError(f"起始日期 {start_date} 之后没有数据")

        self.preview_bars = min(80, self.start_index - self.preview_start_index)

        # 结束日期：训练只走到这一天为止，不再把之后的行情喂进来
        if self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError(f"结束日期 {end_date} 早于起始日期 {start_date}")
            trimmed = self.full_data[self.full_data["date"] <= self.end_date].reset_index(drop=True)
            if trimmed.empty:
                raise ValueError(f"起始日期 {start_date} 到结束日期 {end_date} 之间没有交易日数据")
            if len(trimmed) <= self.preview_bars:
                raise ValueError(
                    f"起始日期 {start_date} 到结束日期 {end_date} 之间的交易日不足，请把区间拉长一些"
                )
            self.full_data = trimmed

        self.current_index = self.preview_bars
        self.max_index = len(self.full_data) - 1
        self.bar_id_offset = -self.preview_bars + 1
        self.trade_markers: List[Dict] = []
        self.cooldown_markers: List[Dict] = []
        self.cooldown_bars: int = 0
        self.cooldown_start_index: int = -1
        self.cooldown_end_index: int = -1

        self._prepare_adjustment_data()

    def _prepare_adjustment_data(self):
        if self.factor_data is not None and not self.factor_data.empty:
            factor_df = self.factor_data[["date", "factor"]].copy()
            factor_df["date"] = pd.to_datetime(factor_df["date"])
            self.full_data = pd.merge(self.full_data, factor_df, on="date", how="left")
            self.full_data["factor"] = self.full_data["factor"].ffill().fillna(1.0)
        else:
            self.full_data["factor"] = 1.0

    def _calculate_adjusted_prices(self, data: pd.DataFrame, mode: str) -> pd.DataFrame:
        if data is None or data.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        result = data.copy()
        if mode == "none":
            return result[[col for col in ["date", "open", "high", "low", "close", "volume", "amount"] if col in result.columns]].copy()

        if mode == "forward":
            latest_factor = self.full_data.iloc[-1]["factor"]
            result["adj_ratio"] = result["factor"] / latest_factor
        elif mode == "backward":
            base_factor = result.iloc[0]["factor"]
            result["adj_ratio"] = result["factor"] / base_factor
        elif mode == "dynamic_forward":
            current_factor = self.full_data.iloc[self.current_index]["factor"]
            result["adj_ratio"] = result["factor"] / current_factor
        else:
            raise ValueError(f"无效的复权模式: {mode}")

        for col in ["open", "high", "low", "close"]:
            result[col] = (result[col] * result["adj_ratio"]).round(2)

        keep_cols = [col for col in ["date", "open", "high", "low", "close", "volume", "amount"] if col in result.columns]
        return result[keep_cols].copy()

    def set_adjustment(self, mode: str):
        if mode not in {"none", "forward", "backward", "dynamic_forward"}:
            raise ValueError(f"无效的复权模式: {mode}")
        self.adjustment_mode = mode

    def get_current_bar_id(self) -> int:
        return self.current_index + self.bar_id_offset

    def _resample_view_frame(self, data: pd.DataFrame, view_period: str = "daily") -> pd.DataFrame:
        if data is None or data.empty or view_period != "weekly":
            return data.reset_index(drop=True) if data is not None else pd.DataFrame()

        frame = data.copy().sort_values("date").set_index("date")
        aggregations = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        if "amount" in frame.columns:
            aggregations["amount"] = "sum"

        weekly = frame.resample("W-FRI").agg(aggregations)
        weekly = weekly.dropna(subset=["open", "high", "low", "close"])
        return weekly.reset_index()

    def _build_bar_meta(self, data: pd.DataFrame) -> List[Dict]:
        if data is None or data.empty:
            return []

        dates = pd.to_datetime(data["date"])
        preview_count = int((dates < self.start_date).sum())
        meta: List[Dict] = []
        for index, current_date in enumerate(dates):
            bar_id = index - preview_count + 1
            meta.append(
                {
                    "time": int(pd.Timestamp(current_date).timestamp()),
                    "bar_id": bar_id,
                    "is_preview": bar_id <= 0,
                }
            )
        return meta

    def _get_adjusted_frame(self, view_period: str = "daily", full: bool = False) -> pd.DataFrame:
        source_frame = self.full_data.copy() if full else self.full_data.iloc[: self.current_index + 1].copy()
        adjusted = self._calculate_adjusted_prices(source_frame, self.adjustment_mode)
        return self._resample_view_frame(adjusted, view_period=view_period)

    def _to_chart_rows(self, data: pd.DataFrame) -> List[Dict]:
        meta = self._build_bar_meta(data)
        chart_data = []
        for index, (_, row) in enumerate(data.iterrows()):
            current_meta = meta[index]
            chart_data.append(
                {
                    "time": current_meta["time"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "bar_id": current_meta["bar_id"],
                    "is_preview": current_meta["is_preview"],
                }
            )
        return chart_data

    def get_visible_data(self, view_period: str = "daily") -> List[Dict]:
        adjusted = self._get_adjusted_frame(view_period=view_period, full=False)
        return self._to_chart_rows(adjusted)

    def get_volume_data(self, view_period: str = "daily") -> List[Dict]:
        adjusted = self._get_adjusted_frame(view_period=view_period, full=False)
        meta = self._build_bar_meta(adjusted)
        volume_data = []
        for index, (_, row) in enumerate(adjusted.iterrows()):
            current_meta = meta[index]
            if row["close"] > row["open"]:
                color = "#ff4d4f"
            elif row["close"] < row["open"]:
                color = "#008000"
            else:
                color = "#000000"
            volume_data.append(
                {
                    "time": current_meta["time"],
                    "value": float(row["volume"]),
                    "color": color,
                    "bar_id": current_meta["bar_id"],
                    "is_preview": current_meta["is_preview"],
                }
            )
        return volume_data

    def get_ma_data(self, periods: List[int] = [5, 10, 20], view_period: str = "daily") -> Dict[int, List[Dict]]:
        adjusted = self._get_adjusted_frame(view_period=view_period, full=False)
        meta = self._build_bar_meta(adjusted)
        result = {}
        for period in periods:
            series = []
            ma_values = adjusted["close"].rolling(window=period).mean()
            for index, value in enumerate(ma_values):
                if pd.isna(value):
                    continue
                current_meta = meta[index]
                series.append(
                    {
                        "time": current_meta["time"],
                        "value": float(value),
                        "bar_id": current_meta["bar_id"],
                        "is_preview": current_meta["is_preview"],
                    }
                )
            result[period] = series
        return result

    def get_current_bar(self) -> Optional[Dict]:
        if self.current_index >= len(self.full_data):
            return None
        current_row = self.full_data.iloc[self.current_index]
        adjusted = self._calculate_adjusted_prices(self.full_data.iloc[[self.current_index]].copy(), self.adjustment_mode)
        adjusted_row = adjusted.iloc[0]
        return {
            "time": int(current_row["date"].timestamp()),
            "open": float(adjusted_row["open"]),
            "high": float(adjusted_row["high"]),
            "low": float(adjusted_row["low"]),
            "close": float(adjusted_row["close"]),
            "volume": float(current_row["volume"]),
            "bar_id": self.get_current_bar_id(),
            "is_preview": self.get_current_bar_id() <= 0,
        }

    def get_current_volume(self) -> Optional[Dict]:
        if self.current_index >= len(self.full_data):
            return None
        current_row = self.full_data.iloc[self.current_index]
        return {
            "time": int(current_row["date"].timestamp()),
            "value": float(current_row["volume"]),
            "bar_id": self.get_current_bar_id(),
            "is_preview": self.get_current_bar_id() <= 0,
        }

    def get_current_date(self) -> Optional[str]:
        if self.current_index >= len(self.full_data):
            return None
        return self.full_data.iloc[self.current_index]["date"].strftime("%Y-%m-%d")

    def get_previous_close(self) -> Optional[float]:
        if self.current_index <= 0:
            return None
        prev = self._calculate_adjusted_prices(self.full_data.iloc[[self.current_index - 1]].copy(), self.adjustment_mode)
        if prev.empty:
            return None
        return float(prev.iloc[0]["close"])

    def add_trade_marker(self, action: str, price: float):
        self.trade_markers.append(
            {
                "bar_id": self.get_current_bar_id(),
                "type": "B" if action == "buy" else "S",
                "price": price,
                "time": int(self.full_data.iloc[self.current_index]["date"].timestamp()),
            }
        )

    def get_trade_markers(self) -> List[Dict]:
        return self.trade_markers.copy()

    def start_cooldown(self, bars: int):
        """清仓后开启 N 个交易日的禁买期（到第 N 根 K 线为止）"""
        if bars is None:
            return
        bars = int(bars)
        if bars <= 0:
            self.cooldown_end_index = -1
            self.cooldown_bars = 0
            return
        self.cooldown_bars = bars
        self.cooldown_start_index = self.current_index
        self.cooldown_end_index = self.current_index + bars

    def _record_cooldown_marker(self):
        """当前 K 线落在禁买期内时记一个标记"""
        if self.cooldown_end_index < 0 or self.current_index > self.cooldown_end_index:
            return
        if self.current_index >= len(self.full_data):
            return
        remaining = self.cooldown_end_index - self.current_index + 1
        self.cooldown_markers.append(
            {
                "bar_id": self.get_current_bar_id(),
                "time": int(self.full_data.iloc[self.current_index]["date"].timestamp()),
                "remaining": remaining,
                "cooldown_bars": self.cooldown_bars,
            }
        )

    def get_cooldown_markers(self) -> List[Dict]:
        return self.cooldown_markers.copy()

    def is_in_cooldown(self) -> bool:
        if self.cooldown_end_index < 0:
            return False
        return self.current_index <= self.cooldown_end_index

    def get_cooldown_remaining(self) -> int:
        if not self.is_in_cooldown():
            return 0
        # 卖出当根不算禁买日，从下一根开始计
        first_blocked = self.cooldown_start_index + 1
        return max(0, self.cooldown_end_index - max(self.current_index, first_blocked) + 1)

    def get_divergence_signals(self, view_period: str = "daily", pivot: int = 3, window: int = 60) -> List[Dict]:
        """顶背离 / 底背离信号，返回可直接作为图表标记的列表

        判定逻辑（只用当前已可见的K线，不含未来数据）：
        - 拐点：某根K线的高点高于左右各 pivot 根的 High（低点同理取最低）
        - 顶背离：后一个高点价格更高，但同一根K线的 DIF 更低 → 卖出信号
        - 底背离：后一个低点价格更低，但同一根K线的 DIF 更高 → 买入信号
        - 两个拐点间隔需在 5 ~ window 根之间，避免把同一段行情拆成多对
        只有拐点右侧 pivot 根K线走完才会被确认，所以信号天然滞后 pivot 根出现。
        """
        try:
            adjusted = self._get_adjusted_frame(view_period=view_period, full=False)
            if adjusted is None or len(adjusted) < max(30, pivot * 2 + 10):
                return []

            macd = self._calculate_macd(adjusted)
            dif_by_bar = {item["bar_id"]: item["dif"] for item in macd.get("data", [])}
            rows = self._to_chart_rows(adjusted)
            n = len(rows)

            pivot_highs = []
            pivot_lows = []
            for i in range(pivot, n - pivot):
                left = rows[i - pivot:i]
                right = rows[i + 1:i + pivot + 1]
                high = rows[i]["high"]
                low = rows[i]["low"]
                if all(high > r["high"] for r in left) and all(high > r["high"] for r in right):
                    pivot_highs.append(i)
                if all(low < r["low"] for r in left) and all(low < r["low"] for r in right):
                    pivot_lows.append(i)

            markers = []

            def add_marker(index, kind):
                row = rows[index]
                if kind == "top":
                    markers.append({
                        "time": row["time"],
                        "bar_id": row["bar_id"],
                        "position": "aboveBar",
                        "color": "#ff4d4f",
                        "shape": "arrowDown",
                        "text": "顶背离",
                        "type": "top_divergence",
                    })
                else:
                    markers.append({
                        "time": row["time"],
                        "bar_id": row["bar_id"],
                        "position": "belowBar",
                        "color": "#16a34a",
                        "shape": "arrowUp",
                        "text": "底背离",
                        "type": "bottom_divergence",
                    })

            prev = None
            for index in pivot_highs:
                if prev is not None and 5 <= index - prev <= window:
                    dif_prev = dif_by_bar.get(rows[prev]["bar_id"])
                    dif_cur = dif_by_bar.get(rows[index]["bar_id"])
                    if (dif_prev is not None and dif_cur is not None
                            and rows[index]["high"] > rows[prev]["high"]
                            and dif_cur < dif_prev):
                        add_marker(index, "top")
                prev = index

            prev = None
            for index in pivot_lows:
                if prev is not None and 5 <= index - prev <= window:
                    dif_prev = dif_by_bar.get(rows[prev]["bar_id"])
                    dif_cur = dif_by_bar.get(rows[index]["bar_id"])
                    if (dif_prev is not None and dif_cur is not None
                            and rows[index]["low"] < rows[prev]["low"]
                            and dif_cur > dif_prev):
                        add_marker(index, "bottom")
                prev = index

            markers.sort(key=lambda item: item["time"])
            return markers
        except Exception as e:
            print(f"计算背离信号失败: {e}")
            return []

    def next_bar(self) -> bool:
        self.factor_changed = False
        if self.current_index >= self.max_index:
            return False

        old_factor = self.full_data.iloc[self.current_index]["factor"]
        self.current_index += 1
        new_factor = self.full_data.iloc[self.current_index]["factor"]
        if self.adjustment_mode == "dynamic_forward" and old_factor != new_factor:
            self.factor_changed = True
        self._record_cooldown_marker()
        return True

    def has_next(self) -> bool:
        return self.current_index < self.max_index

    def get_planned_end_date(self) -> Optional[str]:
        """本次训练计划走到的最后一天"""
        try:
            if self.end_date is not None and self.full_data.iloc[-1]["date"] is not None:
                return self.end_date.strftime("%Y-%m-%d")
            return self.full_data.iloc[-1]["date"].strftime("%Y-%m-%d")
        except Exception:
            return None

    def reset(self):
        self.current_index = self.preview_bars
        self.trade_markers = []
        self.cooldown_markers = []
        self.cooldown_bars = 0
        self.cooldown_start_index = -1
        self.cooldown_end_index = -1
        self.factor_changed = False

    def jump_to_date(self, target_date: str) -> bool:
        try:
            target_dt = pd.to_datetime(target_date)
            mask = self.full_data["date"] <= target_dt
            if not mask.any():
                return False
            self.current_index = int(mask.sum() - 1)
            return True
        except Exception:
            return False

    def get_progress(self) -> Dict:
        training_current = max(0, self.current_index - self.preview_bars)
        training_total = max(1, self.max_index - self.preview_bars)
        return {
            "current_bar_id": self.get_current_bar_id(),
            "current_index": self.current_index,
            "total_bars": len(self.full_data),
            "training_progress": (training_current / training_total) * 100,
            "current_date": self.get_current_date(),
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.full_data.iloc[-1]["date"].strftime("%Y-%m-%d"),
            "preview_bars": self.preview_bars,
            "is_in_preview": self.get_current_bar_id() <= 0,
            "period": self.interval,
        }

    def get_full_data(self, view_period: str = "daily") -> List[Dict]:
        adjusted = self._get_adjusted_frame(view_period=view_period, full=True)
        return self._to_chart_rows(adjusted)

    def get_technical_indicators(self, indicator_type: str = "MACD", view_period: str = "daily", **kwargs) -> Dict:
        adjusted = self._get_adjusted_frame(view_period=view_period, full=False)
        if adjusted is None or adjusted.empty:
            return {"type": indicator_type, "data": []}

        if indicator_type == "MACD":
            return self._calculate_macd(adjusted, **kwargs)
        if indicator_type == "KDJ":
            return self._calculate_kdj(adjusted, **kwargs)
        if indicator_type == "RSI":
            return self._calculate_rsi(adjusted, **kwargs)
        if indicator_type == "BOLL":
            return self._calculate_boll(adjusted, **kwargs)
        return {}

    def _calculate_macd(self, frame: pd.DataFrame, fast=12, slow=26, signal=9) -> Dict:
        try:
            close_prices = frame["close"]
            meta = self._build_bar_meta(frame)
            ema_fast = close_prices.ewm(span=fast).mean()
            ema_slow = close_prices.ewm(span=slow).mean()
            dif = ema_fast - ema_slow
            dea = dif.ewm(span=signal).mean()
            histogram = (dif - dea) * 2

            result_data = []
            for index, (dif_val, dea_val, hist_val) in enumerate(zip(dif, dea, histogram)):
                if pd.isna(dif_val) or pd.isna(dea_val) or pd.isna(hist_val):
                    continue
                current_meta = meta[index]
                result_data.append(
                    {
                        "time": current_meta["time"],
                        "dif": float(dif_val),
                        "dea": float(dea_val),
                        "histogram": float(hist_val),
                        "bar_id": current_meta["bar_id"],
                        "is_preview": current_meta["is_preview"],
                    }
                )
            return {"type": "MACD", "data": result_data}
        except Exception as e:
            print(f"计算 MACD 失败: {e}")
            return {"type": "MACD", "data": []}

    def _calculate_kdj(self, frame: pd.DataFrame, n=9, m1=3, m2=3) -> Dict:
        try:
            high_prices = frame["high"]
            low_prices = frame["low"]
            close_prices = frame["close"]
            meta = self._build_bar_meta(frame)
            lowest_low = low_prices.rolling(window=n).min()
            highest_high = high_prices.rolling(window=n).max()
            rsv = ((close_prices - lowest_low) / (highest_high - lowest_low) * 100).fillna(50)
            k = rsv.rolling(window=m1).mean()
            d = k.rolling(window=m2).mean()
            j = 3 * k - 2 * d

            result_data = []
            for index in range(len(close_prices)):
                current_meta = meta[index]
                item = {
                    "time": current_meta["time"],
                    "bar_id": current_meta["bar_id"],
                    "is_preview": current_meta["is_preview"],
                }
                if not pd.isna(k.iloc[index]):
                    item["k"] = float(k.iloc[index])
                if not pd.isna(d.iloc[index]):
                    item["d"] = float(d.iloc[index])
                if not pd.isna(j.iloc[index]):
                    item["j"] = float(j.iloc[index])
                result_data.append(item)
            return {"type": "KDJ", "data": result_data}
        except Exception as e:
            print(f"计算 KDJ 失败: {e}")
            return {"type": "KDJ", "data": []}

    def _calculate_rsi(self, frame: pd.DataFrame, periods=(6, 12, 24)) -> Dict:
        try:
            close_prices = frame["close"]
            meta = self._build_bar_meta(frame)
            rsi_values = {}
            for period in periods:
                delta = close_prices.diff()
                gain = delta.where(delta > 0, 0).ewm(alpha=1 / period, adjust=False).mean()
                loss = -delta.where(delta < 0, 0).ewm(alpha=1 / period, adjust=False).mean()
                rs = gain / loss
                rsi_values[f"rsi{period}"] = 100 - (100 / (1 + rs))

            result_data = []
            for index in range(len(close_prices)):
                current_meta = meta[index]
                item = {
                    "time": current_meta["time"],
                    "bar_id": current_meta["bar_id"],
                    "is_preview": current_meta["is_preview"],
                }
                for period in periods:
                    value = rsi_values[f"rsi{period}"].iloc[index]
                    if not pd.isna(value):
                        item[f"rsi{period}"] = float(value)
                result_data.append(item)
            return {"type": "RSI", "periods": periods, "data": result_data}
        except Exception as e:
            print(f"计算 RSI 失败: {e}")
            return {"type": "RSI", "data": []}

    def _calculate_boll(self, frame: pd.DataFrame, period=20, std_dev=2) -> Dict:
        try:
            close_prices = frame["close"]
            meta = self._build_bar_meta(frame)
            middle = close_prices.rolling(window=period).mean()
            std = close_prices.rolling(window=period).std()
            upper = middle + std * std_dev
            lower = middle - std * std_dev

            result_data = []
            for index in range(len(close_prices)):
                current_meta = meta[index]
                item = {
                    "time": current_meta["time"],
                    "bar_id": current_meta["bar_id"],
                    "is_preview": current_meta["is_preview"],
                }
                if not pd.isna(middle.iloc[index]):
                    item["middle"] = float(middle.iloc[index])
                if not pd.isna(upper.iloc[index]):
                    item["upper"] = float(upper.iloc[index])
                if not pd.isna(lower.iloc[index]):
                    item["lower"] = float(lower.iloc[index])
                result_data.append(item)
            return {"type": "BOLL", "data": result_data}
        except Exception as e:
            print(f"计算 BOLL 失败: {e}")
            return {"type": "BOLL", "data": []}

    def get_volume_profile(self, bins=80, view_period: str = "daily") -> Dict:
        try:
            adjusted = self._get_adjusted_frame(view_period=view_period, full=False)
            if adjusted is None or adjusted.empty:
                return {"type": "CHIP", "data": []}
            avg_vol = adjusted["volume"].mean()
            virtual_total_shares = avg_vol * 120 if avg_vol > 0 else 1
            chip_map = {}

            for _, row in adjusted.iterrows():
                vol = float(row["volume"])
                high = float(row["high"])
                low = float(row["low"])
                turnover_ratio = min(vol / virtual_total_shares, 1.0)

                stale_prices = []
                for price in chip_map:
                    chip_map[price] *= 1 - turnover_ratio
                    if chip_map[price] < 1e-5:
                        stale_prices.append(price)
                for price in stale_prices:
                    del chip_map[price]

                if high == low:
                    chip_map[high] = chip_map.get(high, 0) + vol
                else:
                    prices = np.linspace(low, high, num=10)
                    volume_per_price = vol / 10
                    for price in prices:
                        chip_map[price] = chip_map.get(price, 0) + volume_per_price

            if not chip_map:
                return {"type": "CHIP", "data": []}

            min_price = min(chip_map.keys())
            max_price = max(chip_map.keys())
            if min_price == max_price:
                return {"type": "CHIP", "data": [{"price": round(min_price, 2), "volume": round(sum(chip_map.values()), 2)}]}

            step = (max_price - min_price) / bins if bins else (max_price - min_price)
            binned = {}
            for price, volume in chip_map.items():
                bin_idx = int((price - min_price) / step) if step else 0
                if bin_idx >= bins:
                    bin_idx = bins - 1
                bin_price = min_price + (bin_idx + 0.5) * step if step else min_price
                binned[bin_price] = binned.get(bin_price, 0) + volume

            result = [{"price": round(price, 2), "volume": round(volume, 2)} for price, volume in binned.items() if volume > 0]
            result.sort(key=lambda item: item["price"])
            return {"type": "CHIP", "data": result}
        except Exception as e:
            print(f"计算筹码分布失败: {e}")
            return {"type": "CHIP", "data": []}
