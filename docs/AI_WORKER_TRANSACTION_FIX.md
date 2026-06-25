# AI Worker 事务持久化修复（PR-03B 收尾）

## 背景

在 PR-03B 真实 docker 全栈联调（`AI_PROVIDER=fake`）中发现一个 PR-03A 遗留的潜在 bug：
**ai-worker 自报任务成功，但 AI 分析结果不落库**。

CI 此前的 docker E2E 只覆盖 PR-02 媒体链路（扫描/拆镜头/导出），从未真实跑过 docker AI
Worker 路径，因此该 bug 一直未被发现。

## 现象

- celery 任务返回 `{'status': 'completed', 'analyzed': 3}`；
- 但数据库里 `ai_analysis_run.status` 仍为 `queued`，`ai_shot_analysis` / `shot_tag` 全空；
- `ai_analysis_run.worker_name`（取锁**前**写入）却已落库 —— 这一不对称是定位关键。

## 根因

`services/worker/clipmind_worker/ai/tasks.py::_run` 使用 `Session(bind=conn)` 绑定一个
显式连接，并在取 PostgreSQL advisory lock **之前**调用 `session.commit()`（写 `worker_name`）：

1. 该 commit 关闭了 session 当前事务，连接回到"无事务"状态；
2. 紧接着 `conn.exec_driver_sql("SELECT pg_try_advisory_lock(...)")` 直接在连接上执行，
   **另起一个连接级事务**（session 并不拥有它）；
3. 随后 `run_asset_analysis` 内的 `session.commit()` 触发 session 自动开启事务，发现连接
   已有活动事务，于是按 SQLAlchemy 2.0 `join_transaction_mode="conditional_savepoint"`
   **以 SAVEPOINT 方式加入**；
4. 于是这些 `commit()` 只是 `RELEASE SAVEPOINT`，并非真正提交连接级事务；
5. `with engine.connect() as conn:` 退出时 `conn.close()` 把那个连接级事务**整体回滚**——
   AI 结果、run 状态全部丢失，只有取锁前那次真正 commit 的 `worker_name` 幸存。

`media-worker` 的 `analyze_shots` 用同样的 `Session(bind=conn)` + advisory lock，但 happy
path **取锁前不 commit**，session 自始至终持有连接事务、取锁也并入该事务，故 commit 均为真实提交、未受影响。

## 修复

`_run` 取锁前**不再 commit**（`worker_name` 留待取锁后由 `run_asset_analysis` 的首个 commit
一并真实提交），与 `media-worker` 的事务生命周期一致。`pg_try_advisory_lock` 为 session 级锁，
不随 commit 释放，故取锁后 commit 不影响互斥语义。

## 回归保护

`services/worker/tests/test_ai_task_persistence.py`（真实 PostgreSQL，FakeProvider）：

- `test_ai_task_persists_results_after_advisory_lock_transaction`：**经真实任务入口 `_run`**
  （engine.connect + Session(bind=conn) + advisory lock）执行，用**全新 Session / 多次重连**
  断言 run.status=completed、finished_at、worker_name、progress、`ai_shot_analysis` 数量、
  active `shot_tag` 投影均真正落库。还原旧实现时此测试失败（已验证）。
- `test_ai_task_persists_failed_run_on_provider_error`：provider 致命错误时 run 必须持久化为
  `failed` + `error_message`，绝不停留在 `queued`。

## CI 覆盖

`.github/workflows/ci.yml` 的 `docker-e2e` 新增（`AI_PROVIDER=fake`，绝不在 Actions 用真实 Key）：

1. 确认 ai-worker 在运行并消费 `ai` 队列；
2. 发起 AI 分析 → 轮询 `completed`；
3. **DB 级**断言 `ai_analysis_run(completed) / ai_shot_analysis / shot_tag(active) /
   shot_review_state` 均已持久化（不以 Celery task 自报成功为准）；
4. 有效结果 → 人工 confirm → review_state/review_event → 素材汇总 → projection-first 筛选命中；
5. 重启 api + **ai-worker** 后再跑 `--mode check-persist`，数据仍在；
6. 失败时输出 api/ai-worker/postgres 日志与各表计数（脱敏，不输出 env/key）。

驱动脚本：`scripts/ci_ai_e2e.py`（仅标准库）。

## 真实 MiMo 验证与本机限制（脱敏）

- **宿主机**真实 MiMo 能力探测（`scripts/probe_ai_provider.py`）：multi-image `HTTP 200`、
  单图 ok、延迟约 5.3s、embedding `HTTP 404`（符合"无嵌入"预期）。Provider 代码、密钥、
  视觉模型 `mimo-v2.5` 均有效可用。
- **docker 容器内**真实 MiMo 调用失败：`error_code=unavailable`、无 HTTP 响应；诊断为
  端点 `token-plan-cn.xiaomimimo.com` 解析到内网地址（`172.19.x.x`），宿主在公司网络可达、
  Docker 桥接网络 `No route to host`。**属网络拓扑限制，非代码/鉴权/模型问题**；失败 run 已正确
  持久化为 `failed`（再次印证修复）。CI 使用 `AI_PROVIDER=fake`，不受此限制影响。

> 安全：API Key 仅存本机 `.env`（git 忽略），绝不写入代码/日志/文档/提交；以上诊断均脱敏。
