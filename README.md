# Money Back

个人 ETF 策略研究项目。第一阶段逆向验证 `T5_15D2P_60I1_5S`：主题 ETF 15 日动量排名、2 个百分点替换防抖、四指数 60 日状态过滤，以及组合级 5% hard stop。

当前结论以 `notebooks/01_t5_reconstruction.ipynb` 的已执行输出为准。市场数据由脚本按需下载到 `data/cache/`，缓存不进入版本控制。

## 当前基线

- 固定策略配置：`configs/t5_v0_1.json`
- 项目架构与版本路线：`docs/PROJECT_ARCHITECTURE.md`
- 研究记录：`research_log/2026-07-18_t5_v0_1.md`
- 新增结构探索：`outputs/exploration_topk_gate.csv`

后续研究创建新的配置、笔记和研究记录，不覆盖 V0.1。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\build_notebook.py
.\.venv\Scripts\python.exe scripts\execute_notebook.py
```

这不是自动交易系统，也不包含券商下单接口。
