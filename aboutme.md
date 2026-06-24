# SMC Trading Bot — Project Overview

## Mục tiêu
Bot scalping tự động cặp XAUUSDm trên sàn Exness, sử dụng Smart Money Concepts (SMC) làm chiến lược phân tích. Chỉ vào lệnh thuận chiều xu hướng khung lớn (HTF), không đánh ngược trend.

## Chiến lược giao dịch

### Nguyên tắc cốt lõi
- **Luôn thuận chiều HTF**: H4/D1 xác định bias → chỉ trade theo hướng đó
- **Multi-timeframe**: H4 (bias) → H1 (structure + OB) → M15/M5 (entry)
- **SMC-based**: Order Blocks, FVG, BOS/CHoCH, Liquidity Sweeps

### Flow vào lệnh
```
H4 Bias (Bullish/Bearish)
    ↓
H1: Tìm Order Block + BOS cùng chiều
    ↓
M15: Tìm FVG trong vùng OB
    ↓
M5: CHoCH xác nhận → VÀO LỆNH
    ↓
SL dưới/trên OB | TP = swing high/low H1 (RR ≥ 1:2)
```

## Tech Stack

| Thành phần | Công nghệ |
|---|---|
| Ngôn ngữ | Python 3.11+ |
| Kết nối broker | MetaTrader5 Python API |
| Data processing | pandas, numpy |
| Scheduling | asyncio / schedule |
| Logging | loguru |
| Backtesting | backtesting.py hoặc vectorbt |

## Cấu trúc project

```
SMC_Trading_Bot/
├── aboutme.md
├── requirements.txt
├── main.py
├── connectors/
│   └── mt5_connector.py       # Kết nối MT5, lấy OHLCV, đặt lệnh
├── analysis/
│   ├── structure.py            # Swing points, BOS, CHoCH
│   ├── order_blocks.py         # Bullish/Bearish OB detection
│   ├── fvg.py                  # Fair Value Gap
│   └── liquidity.py            # Equal highs/lows, sweeps
├── strategy/
│   ├── htf_bias.py             # H4/D1 trend direction
│   └── entry_manager.py        # Entry logic kết hợp 3 khung
├── risk/
│   └── risk_manager.py         # Lot size, SL/TP, max drawdown
└── tests/
    └── backtest.py
```

## Thông số giao dịch

- **Cặp tiền**: XAUUSDm
- **Broker**: Exness (tài khoản Raw Spread hoặc Zero)
- **Session**: London + NY overlap (13:00–17:00 UTC)
- **Risk/trade**: 1% tài khoản
- **Max daily loss**: 3%
- **RR tối thiểu**: 1:2
- **Tránh**: FOMC, NFP, CPI news

## SMC Concepts được sử dụng

| Khái niệm | Khung | Mục đích |
|---|---|---|
| Swing High/Low | H4, H1, M5 | Nền tảng phân tích structure |
| BOS (Break of Structure) | H4, H1 | Xác nhận xu hướng |
| CHoCH (Change of Character) | M5 | Tín hiệu vào lệnh |
| Order Block (OB) | H1 | Vùng vào lệnh |
| FVG (Fair Value Gap) | M15 | Vùng vào lệnh phụ |
| Liquidity Sweep | H1 | Xác nhận manipulation trước entry |

## Số nến cần thiết

| Bước | Khung | Số nến |
|---|---|---|
| Swing Points | H4 | 100–200 nến |
| HTF Bias | H4 | 2 SH + 2 SL |
| Order Block | H1 | 50 nến lookback |
| FVG | M15 | 3 nến |
| CHoCH Entry | M5 | 10–20 nến |
