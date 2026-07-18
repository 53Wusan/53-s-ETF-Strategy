# Money Back

个人 A 股 ETF 策略研究系统。项目把策略定义、数据闸门、执行回测、验证指标和每日信号分离，目标不是调出漂亮曲线，而是判断策略是否值得进入纸面跟踪。

## 当前结论（V0.2）

**STOP / BLOCKED_DATA。** V0.1 截图策略仍可精确回归，但免费数据没有同时满足：

- 2013 年以来含退市 ETF 的时点一致名册；
- 可审计的历史成交额；
- 独立第二行情源。

因此 V0.2 只能叫“固定池探索”，不能叫全市场严格回测。修正原始价格跳变被误计为经济损失的问题后，固定池 T5 的滚动三年中位数约 2.76 倍、最大回撤约 28.1%；波动控制版回撤约 24.2%，但滚动三年中位数约 2.31 倍，均未达到 4 倍收益门槛。预注册邻域中的 Top1 收益最高，但它属于稳定性检验，不能在看过结果后直接升级为正式策略。

主报告：`outputs/v0_2/strict_validation_report.md`
已执行笔记：`notebooks/02_t5_strict_validation.ipynb`

## 新电脑接手

```powershell
git clone https://github.com/53Wusan/ETF-0718-Strategy.git
cd ETF-0718-Strategy
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# 首次抓取/刷新免费行情并运行冻结研究
.\.venv\Scripts\money-back.exe strict-research --refresh
# 精确复现 V0.1 基线，再运行全部离线测试
.\.venv\Scripts\python.exe -m pytest tests\test_regression_v0_1.py
.\.venv\Scripts\python.exe -m pytest
# 当前会明确提示闸门未通过；通过后同一命令启动本地页
.\.venv\Scripts\money-back.exe web
```

研究命令会把行情缓存写入 `data/cache/`；缓存、密钥和个人成交记录不会进入 Git。

## 三个入口

```powershell
# 运行预注册严格研究
.\.venv\Scripts\money-back.exe strict-research

# 生成带 RESEARCH ONLY 警告的信号预览
.\.venv\Scripts\money-back.exe signal

# 仅当数据与性能门槛同时通过后才会解锁
.\.venv\Scripts\money-back.exe web
```

网页和 12 周纸面跟踪目前均未解锁。项目不包含券商接口或自动下单。

## 版本锚点

- `v0.1-t5-reconstruction`：截图策略还原与严格次日开盘基线。
- `configs/t5_v0_2.json`：V0.2 预注册研究规格。
- `docs/STRICT_VALIDATION.md`：指标、数据和执行口径。
- `docs/PROJECT_ARCHITECTURE.md`：系统边界与后续路线。

## 收益计价边界

- 原始 OHLC、成交量和涨跌停状态只用于判断能否成交与估算执行价格。
- 持有期收益使用与信号一致的复权 OHLC，避免分红、份额拆分或行情供应商拼接造成虚假亏损。
- `tests/test_backtest.py` 包含原始价格减半但复权价值连续的回归用例。
