# Emby Clean 分阶段实施与审查记录

## 总体状态

- 目标：保留日本/FC2 旧查重规则，完成欧美及其他资料库的通用查重、媒体/图片检查、筛选、任务、审计和安全执行。
- 当前阶段：阶段一至阶段四已完成；前端视觉刷新已完成，进入 FNOS 真实数据观察前的交接状态。
- FNOS 边界：本轮只读检查；不执行远程删除、写入或部署。

## 阶段一：规则安全化 ✅

### 已实现

- 新增非日本/FC2 资料库匹配器链。
- 修复多点号场景编号被 `splitext()` 截断的问题。
- 支持站点 + 完整多段编号。
- 支持站点目录上下文 + 数字编号。
- 禁止 `TMDBID-33238`、`MAN-365` 等无上下文通用短码进入欧美场景编号匹配。
- 查重结果增加匹配器、置信度、证据、来源类型。
- STRM 缺少大小/时长/分辨率时，现代规则只给出人工复核，不静默选择删除项。
- 日本系列和 FC2 保持旧 `av`/`smart` 路径。

### 验证

```text
python3 -m unittest discover -s tests -v  # 6 tests passed
python3 -m compileall -q app              # passed
git diff --check                           # passed
```

### 阶段审查结论

- 通过：欧美当前失效的直接 Bug 已覆盖测试并修复。
- 通过：日本/FC2 有回归测试，继续使用旧匹配器。
- 保留风险：FNOS `.strm` 远程内容仍无法仅凭本地 stub 判断，需要后续源引用/指纹适配器；当前没有对生产数据执行删除。

## 阶段二：媒体、图片与 STRM 完整性检查 ✅

### 已实现

- 新增只读源盘点：本地文件、STRM、路径不可用、非法 STRM 分开表示。
- 新增 `image` 模式：缺失封面和相同 Emby 图片标签进入人工复核。
- 新增 `media_health` 模式：检查路径、大小、时长、分辨率等媒体字段。
- 新增 `strm_health` 模式：挂载/路径不可用明确显示为 unavailable，不推导为可删除。
- 新增 `source_dupe` 模式：同一可读 STRM 源引用进入精确候选组。
- 新增 `fingerprints` 缓存表和媒体源状态字段，为后续增量扫描提供基础。

### 验证

```text
python3 -m unittest discover -s tests -v  # 10 tests passed
python3 -m compileall -q app              # passed
git diff --check                           # passed
```

### 阶段审查结论

- 通过：完整性结果与删除动作分离，暂时不可访问的 FNOS/FUSE 路径不会被误报为缺失资源。
- 通过：图片和源引用结果默认是 review，不直接生成删除动作。
- 保留风险：当前 Emby 图片标签是精确重复线索，不等于感知相似度；真正的图片/视频内容指纹需要后续适配器。

## 阶段三：任务、审计、鉴权与安全删除 ✅

### 已实现

- `jobs` 表记录扫描/同步任务状态、参数、结果和错误；服务重启后 queued/running 任务可恢复执行。
- `audit_log` 记录配置、忽略、删除计划、删除成功/失败、刷新等动作。
- `EMBY_CLEAN_API_KEY` 可保护 API 和图片代理；前端支持本地保存并自动携带 Key。
- 配置备份/导出移除密码、Access Token、User ID。
- 删除默认生成 dry-run 计划，必须 `confirm=true&dry_run=false` 才能进入队列。
- STRM/远程源不会进入实际删除队列；定时自动删除默认关闭，必须单独打开高风险开关。

### 验证

```text
python3 -m unittest discover -s tests -v                 # 18 tests passed
/tmp/emby-clean-venv/bin/python -m unittest discover ... # 18 tests passed
FastAPI TestClient: health/job/audit/export/API-Key       # passed
```

### 阶段审查结论

- 通过：未确认删除不会触发 Emby DELETE 请求。
- 通过：服务端配置 API Key 时无 Key 返回 401，有效 Key 返回 200。
- 通过：配置导出不包含密码、Access Token、User ID。
- 保留风险：当前“回滚”边界是 Emby 条目删除前的计划和审计，未实现文件系统回收站；STRM/远程源默认禁止删除。

## 阶段四：架构、UI、部署与可观测性 ✅

### 已实现

- 将规则、源盘点、内容指纹和安全策略拆为独立模块，降低 `scanner.py` 的职责耦合。
- 增加图片/媒体/STRM/内容指纹检查入口和前端模式。
- 前端展示匹配器、置信度和证据，删除动作携带显式确认参数。
- 增加 Docker healthcheck、Python 3.12 CI、单测/编译/空白检查。
- 增加部署文档和 FNOS 只读职责说明。

### 验证与未决

- 前端 JavaScript：`node --check` 通过。
- Docker 构建：已通过 `docker build -t emby-clean:review .`，本地镜像已生成；此前 Docker daemon 未运行的阻断已解除。
- FNOS 生产观察：本轮未部署镜像、未触发同步、未执行删除；需用户确认发布窗口后单独进行。

### 前端视觉刷新补充 ✅

- 重做为“深色媒体档案控制室”视觉：深色靛蓝背景、暖橙操作色、青色状态色和编辑风标题层级。
- 增加首屏任务说明、资料库范围、检测信号两个分段标签，降低扫描入口的认知负担。
- 重做品牌区、侧栏统计、扫描模式卡片、结果组、证据标签、操作按钮和移动端响应式布局。
- 保留原有扫描、结果、任务、配置、存储、日志导航及删除安全流程，视觉改版不改变业务接口。
- 统一前端页脚和服务启动日志版本号为 `2.1.0`。

### 前端验收

- 本地浏览器首屏检查：通过；资料库未配置时能明确显示“请先保存 Emby 配置”。
- 导航交互检查：通过；配置页可正常打开并展示 API Key、自动删除安全开关等既有能力。
- 浏览器控制台错误/警告：0 条。
- 前端结构测试：通过；JavaScript 语法检查：通过。
