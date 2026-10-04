# 历史控制器请求间隔

新启动的 `python -m scripts.history_worker` 默认请求间隔为 `0.2` 秒。控制器将此值传给每一批现有 `scripts.pipeline history`，仍串行执行，每批默认保留 400 次请求和 900 秒预算。

需要降速时可显式指定，例如：

```powershell
python -m scripts.history_worker --min-interval 1
```

间隔参数接受有限非负秒数。每日任务预留窗口、来源 Retry-After 和持久失败退避沿用现有行为；直接运行采集 CLI 的默认间隔仍为 1 秒。

2026-10-04 首次真实有限快批使用 `0.2` 秒，200 次请求用时 76.125 秒，平均约 2.627 次/秒，新增 133 条单局记录；该批响应均为 HTTP200，没有 HTTP429。这是一批实际观察，不是固定吞吐量承诺。

已经驻留的旧控制器继续使用它启动时加载的代码；新默认值在下一次正常启动控制器时生效。历史顺序、缺口与串行补采取舍见 [历史顺序与吞吐决策](adr/0002-history-order-and-throughput.md)。
