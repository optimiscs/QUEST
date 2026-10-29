# QUEST 轨迹视图

此目录为轨迹工作区的中文入口；两个入口共用脚本、样式和静态资源，保留各自 HTML 和数据路径。

从仓库根目录运行 `workspace/env/bin/python web/serve.py`，通过 `http://127.0.0.1:6080/` 或 `http://127.0.0.1:6080/trace-viewer-zh/` 访问。工作区每 5 秒检查数据更新，任务不会由页面自动启动。

数据集清单和运行轨迹位于 `web/trace-viewer/datasets/`，不提交到 Git。格式说明见 `SCHEMA.md`；标准启动、五秒刷新及从已有 GAIA 事件重建新视图的说明见上级 `web/README.md`。旧运行的历史日志、结果和评分保留在 `workspace/strict-reproduction/`。
