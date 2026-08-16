# Emby Clean 专业 Review 与查重规则研究

> 状态：Review 基线已落地，代码按阶段实施中（未部署生产）
> 日期：2026-08-16
> 数据来源：本地代码、FNOS 只读检查、当前 Emby Clean SQLite 缓存、GitHub 开源项目资料

## 1. 结论先行

### 1.1 欧美查重失效的直接原因

当前 `app/scanner.py` 的 `normalize_variant_key()` 使用：

```python
os.path.splitext(os.path.basename(text or ""))[0]
```

这对普通文件名有效，但对欧美资料库常见的多段编号不适用。它会把最后一个点号后的内容当成扩展名，导致：

```text
DorcelClub.15.01.01  ->  dorcelclub 15 01
1000Facials.17.05.22 ->  1000facials 17 05
Blacked.20.01.01     ->  blacked 20 01
```

因此同一站点、同一年月的不同场景被错误合并，既会漏掉真正的精确查重，也会制造高风险误合并。

同时，欧美库的 `av` 模式只支持少量通用编号正则，无法覆盖：

- `站点.年份.月份.场景号`：如 `DorcelClub.15.01.01`
- `站点/连续编号`：如 `DudCast.com/02`
- `站点目录/编号 + 演员或标题`：如 `FellatioJapan/040-...`
- 不同站点各自的日期、批次、场景编号组合

### 1.2 FNOS 当前数据限制

本次只读盘点得到：

| 项目 | 欧美库现状 | 对查重的影响 |
|---|---:|---|
| Emby API 缓存媒体条目 | 7,969 | 有基础索引，但需关注缓存新鲜度 |
| `.strm` 媒体条目 | 7,891 | 主要是远程引用，不是本地视频文件 |
| Provider ID | 0 | 不能依赖 Emby Provider ID |
| 有效大小/时长/分辨率 | 约 78/79/72 | 不能依赖媒体质量字段选优 |
| 有海报的媒体条目 | 约 6,742 | 只能做“缺海报”检查，尚不能代表内容相似 |
| `.strm` 精确内容重复 | 0 组 | 当前指向 URL 没有发现完全相同的重复引用 |

所有 `.strm` 当前都指向同一 CMS 网关地址。对 `.strm` 文件本身做哈希只能发现“引用文本完全相同”，不能证明远程视频内容相同；远程内容查重需要额外的内容指纹或 CMS/文件源元数据。

### 1.3 当前扫描结果

对当前缓存运行现有规则：

| 资料库 | `av` 模式 | `smart` 模式 | 判断 |
|---|---:|---:|---|
| 欧美 | 0 组 | 1,277 组 / 5,384 条 | `smart` 有结果，但包含明显误合并风险 |
| 日本系列 | 有结果 | 有结果 | 现有日本编号规则较适配 |
| Running man | 有结果 | — | 通用正则会把 `TMDBID-33238`、`MAN-365`、`VS-100` 等误当作重复编号 |

欧美 `smart` 的结果不能直接用于删除。当前 `size`、`duration`、`resolution` 对 `.strm` 基本不可用，推荐保留项实际可能只是按稳定排序选出的第一项，而不是按真实质量选出的最佳项。

## 2. 建议的欧美查重规则

不要继续扩大一个全局正则，而应改成“资料库配置 + 多匹配器 + 置信度”的规则管线。

### 2.1 查重优先级

1. **精确引用重复**：规范化后的完整源 URL、完整 STRM 内容、源文件 inode/哈希一致。
2. **明确场景编号重复**：同一站点上下文内，完整编号一致。
3. **站点 + 标题 + 演员/目录上下文重复**：用于没有稳定编号的条目。
4. **媒体内容指纹相似**：视频采样指纹、音频指纹、图片感知哈希。
5. **弱候选**：仅标题相似、仅演员相似、仅短数字相同，只进入人工复核，不自动处理。

每个候选组应保存：

```text
matcher       使用的匹配器
group_key     规范化后的查重键
confidence    exact / high / medium / low
evidence      命中的字段和原始值
source_type   local_file / strm / remote_reference
recommended   keep / review / delete_candidate
```

### 2.2 欧美匹配器建议

#### Matcher A：站点 + 完整多段编号

适用于：

```text
DorcelClub.15.01.01
1000Facials.17.05.22
18Eighteen.15.12.09
Blacked.20.01.01
```

规则：

- 先识别站点/制作方前缀。
- 保留完整编号 `15.01.01`，不能把最后一段当作文件扩展名删除。
- 生成 `site + full_scene_code`。
- 编号中的年份、月份、场景号必须作为整体参与匹配。
- 只有完整编号一致时才进入高置信度组。

示例：

```text
site=dorcelclub, scene=15.01.01
key=western:dorcelclub:15.01.01
```

#### Matcher B：目录/站点上下文 + 数字编号

适用于：

```text
DudCast.com/02
FellatioJapan/040-...
```

规则：

- 不能把 `02` 或 `040` 单独作为全局查重键。
- 必须带上站点目录、父目录、系列名或标题上下文。
- `DudCast.com/02` 与其他目录下的 `02` 默认不重复。
- 对只有数字且缺少上下文的条目，最多标记为 `low`，不自动删除。

#### Matcher C：规范化标题 + 站点 + 演员上下文

适用于没有稳定编号的条目：

- 去除已知质量标签：`2160p`、`1080p`、`WEB-DL`、编码格式等。
- 去除语言、字幕、发布组等可配置后缀。
- 不删除点号分隔的主体字段，除非确认它是扩展名或质量后缀。
- 组合站点、标题、演员/目录上下文。
- 标题相同但站点不同，默认不合并。

#### Matcher D：STRM 源引用

对 `.strm` 单独建模：

- `exact_target`：完整 URL 解码、去除无意义参数后完全一致，`exact`。
- `same_origin_path`：同协议、主机、路径一致但参数不同，`high` 或 `review`，取决于参数是否影响内容。
- 文件内容哈希一致但 URL 不同，仍需标记为“相同引用文本”，不能直接等同于相同媒体。
- URL 不同、内容实际相同的情况，必须由 CMS API、源文件元数据或视频指纹确认。

#### Matcher E：图片完整性与图片查重

拆成两个功能：

- 图片完整性：无海报、海报请求失败、图片过小、图片损坏、图片与条目不匹配。
- 图片重复：图片二进制哈希、感知哈希、相似度阈值；相同海报不能直接推断视频重复。

### 2.3 分库策略

每个 Emby Library 使用独立配置：

```yaml
library_profile:
  library_id: 23628
  name: 欧美
  matchers:
    - western_scene_code
    - site_context_number
    - normalized_title_context
    - strm_exact_target
  cross_library_match: false
  auto_delete_confidence: exact
  quality_policy: path_and_source
```

默认不跨库查重。日本、欧美、FC2、Running man 的编号语义不同，不能共用一个通用正则。

## 3. 项目功能层面 Review

### P0：必须先处理

1. 修复 `normalize_variant_key()` 的多点号截断问题，并补充欧美真实样本测试。
2. 将 `av_key` 从通用正则改为“站点配置的匹配器链”，禁止短数字和通用短码单独成组。
3. 扫描结果增加匹配器、置信度、证据字段；没有证据的结果不得进入自动删除。
4. `smart` 不得在大小、时长、分辨率均为 0 时假装完成质量选优；应显示“质量信息缺失”。
5. `/api/scan`、同步和删除改为持久化 Job，支持进度、取消、重试和服务重启后恢复。
6. 删除必须默认 dry-run，并区分 Emby 条目、STRM 文件、远程源文件；禁止隐式删除云端源文件。
7. 配置导出/备份不能包含明文密码、访问令牌等敏感字段；当前 `_BACKUP_CONFIG_KEYS` 包含这类字段，需立即整改。
8. 所有修改、删除、忽略、恢复操作记录审计日志，并支持回滚或回收站策略。
9. 管理 API 增加认证和权限控制。当前包括删除、重试、刷新、配置导入等接口，不应仅依赖网络隔离。

### P1：影响可用性和可维护性

1. 将 `app/main.py` 拆分为 API、任务编排、同步、删除、图片、通知等模块。
2. 增加正式数据库迁移机制，替代运行时零散 `ensure_column`。
3. 引入统一的 `MediaItem`、`SourceRef`、`DuplicateGroup`、`Evidence`、`ActionPlan` 数据模型。
4. 增加扫描缓存：按路径、大小、mtime、ETag 或源版本增量更新，避免每次重复计算。
5. 增加路径映射配置，明确 FNOS 宿主机、Emby 容器、Emby Clean 容器、CMS 容器之间的路径边界。
6. 增加分页、筛选、按置信度/站点/匹配器查看，避免一次性把全部结果放入内存。
7. 增加图片检查、视频元数据检查、STRM 可达性检查和资源源状态检查。
8. 让 MDC 继续作为 NFO/图片写入方；查重服务只读 Emby/CMS/媒体源，避免多个服务争抢元数据写入权。

### P2：增强能力

1. 本地视频抽样指纹和音频指纹，支持转码、分辨率变化、水印场景。
2. 远程 STRM 的内容级指纹适配器：仅在源端可安全读取时启用，设置带宽、超时和并发上限。
3. 多版本管理：正片、删减版、字幕版、不同清晰度应支持“合并展示”或“保留多个版本”，不全部视为重复。
4. 规则模拟器：修改规则后先对当前缓存生成差异报告，展示新增组、拆分组、合并组和风险变化。
5. 规则插件化，允许为日本、欧美、FC2、综艺等资料库分别维护匹配器和质量策略。

## 4. 架构层面建议

建议从当前“单体 API + 扫描器”演进为以下边界：

```text
Connectors
  Emby API / CMS API / MDC read-only / filesystem / STRM parser
        ↓
Indexer
  media inventory / path mapping / freshness / incremental cache
        ↓
Fingerprint Services
  exact hash / filename key / metadata / image pHash / video sample hash
        ↓
Rule Engine
  library profile / matcher chain / confidence / evidence / quality policy
        ↓
Review & Action
  dry-run / candidate review / keep selection / delete plan / audit / rollback
        ↓
Web API & UI
  jobs / progress / filters / reports / configuration / permissions
```

FNOS 部署边界建议：

- Emby Clean 使用 Emby API 和只读媒体挂载，不读取 Emby 内部数据库。
- `cloud-media-sync`、MDC、Emby 各自保持职责，不由查重服务代写 NFO/图片。
- 对 115/FUSE/远程挂载做健康检查和新鲜度标记；挂载恢复后不要把暂时不可见误判为已删除。
- 所有源路径、容器路径和 URL 统一转换成 `SourceRef`，避免用字符串猜测路径关系。
- 大任务必须落库，不能只依赖进程内全局锁或内存状态。

## 5. 值得借鉴的开源项目

### 5.1 最值得优先研究

| 项目 | 适合借鉴的部分 | 备注 |
|---|---|---|
| [MediaDedupe](https://github.com/parcival42/MediaDedupe) | 图片/视频重复、SQLite 缓存、扫描 Job、进度、删除历史、Web UI | 与本项目“媒体库查重”最接近，优先看数据模型和任务生命周期 |
| [Czkawka](https://github.com/qarmin/czkawka) | 文件精确哈希、相似图片、视频帧指纹、缓存、CLI/JSON | 适合借鉴扫描分层和指纹引擎边界，不建议直接复制整套 UI |
| [fclones](https://github.com/pkolaczk/fclones) | 预哈希、持久化缓存、路径过滤、保留优先级、dry-run、JSON/CSV | 适合借鉴大规模文件扫描和保留策略 |
| [VideoDuplicateFinder](https://github.com/0x90d/videoduplicatefinder) | 相似视频、不同分辨率/帧率/水印、部分片段 | 适合验证视频内容指纹能力；注意 AGPL 许可边界 |
| [videohash](https://github.com/akamhy/videohash) | Python 视频感知哈希、采样帧、缩放/水印鲁棒性 | 适合作为实验性 Python 适配器，不解决部分视频重复 |
| [imagededup](https://github.com/idealo/imagededup) | 图片精确/近似查重、PHash/DHash/Whash/CNN、评估 | 适合海报相似度和图片完整性模块 |
| [imagehash](https://github.com/JohannesBuchner/imagehash) | 多种图片感知哈希算法 | 适合做轻量依赖或算法对比基线 |

### 5.2 Emby/Jellyfin 规则和版本管理

| 项目 | 适合借鉴的部分 | 风险/边界 |
|---|---|---|
| [emby-duplicate-finder-plugin](https://github.com/theoneakta/emby-duplicate-finder-plugin) | 电影标题+年份、TVDB、同目录、混合目录、Radarr/Sonarr 状态 | 直接访问 Emby 内部服务/数据库，强耦合，不建议照搬 |
| [emby-tvdb-dupe-finder](https://github.com/theoneakta/emby-tvdb-dupe-finder) | 浏览器端按电影、剧集、TVDB、季集、目录查重 | 适合借鉴规则和复核交互，删除前必须增加本项目的 dry-run/审计 |
| [jellyfin-plugin-mergeversions](https://github.com/danieladov/jellyfin-plugin-mergeversions) | 多版本合并、拆分、手动/定时处理 | 适合借鉴“重复”和“多版本”的区分 |
| [Shokofin](https://github.com/ShokoAnime/Shokofin) | Provider ID、组映射、多版本剧集/电影合并 | 适合借鉴结构化身份，不适合直接用于欧美无 Provider ID 数据 |
| [jellyfin-plugin-media-cleaner](https://github.com/shemanaev/jellyfin-plugin-media-cleaner) | 保护规则、用户/收藏/标签过滤、定时清理 | 适合借鉴删除前保护策略 |
| [quality-gate](https://github.com/GeiserX/quality-gate) | 路径/正则质量策略、每用户策略、多版本、审计 | 适合借鉴“质量门禁”而非直接复制插件实现 |

### 5.3 文件、图片和媒体管理参考

| 项目 | 适合借鉴的部分 |
|---|---|
| [rmlint](https://github.com/sahib/rmlint) | 快速文件/目录重复、缓存、回放、输出格式、保守模式 |
| [jdupes](https://github.com/Asureus/jdupes) | 文件重复、哈希、硬链接和命令行安全选项 |
| [dupeGuru](https://github.com/arsenetar/dupeguru) | 文件名模糊匹配、内容匹配和人工复核 UI |
| [dedup-videos](https://github.com/lyager/dedup-videos) | 五点采样、时长容差、分辨率/码率/大小质量排序、JSON 缓存和恢复 |
| [AtlasPilotPuppy/dedup](https://github.com/AtlasPilotPuppy/dedup) | 多哈希、媒体模式、缓存、选择策略、dry-run、JSON/TOML |
| [MediaLens](https://github.com/G1enB1and/MediaLens) | 可解释的相似图片结果、操作历史、可撤销体验 |
| [Stash](https://github.com/stashapp/stash) | 媒体模型、GraphQL、扫描/刮削/过滤/标签/统计、插件化 |
| [Stash-Box](https://github.com/stashapp/stash-box) | 视频索引、感知哈希距离、鉴权、审计思路 |
| [Backblaze video hash example](https://github.com/backblaze-b2-samples/videohash-deduplication) | 增量哈希索引、Union-Find 聚类、报告和 Dashboard 思路 |
| [Nextcloud duplicatefinder](https://github.com/eldertek/duplicatefinder) | 后台扫描、受保护目录、外部挂载处理、数据库清理与真实文件删除分离 |

### 5.4 许可建议

优先借鉴算法、数据模型和交互设计，谨慎直接复制实现代码。部分项目采用 GPL/AGPL，尤其是文件管理、视频查重和 Emby/Jellyfin 插件项目；正式引入前应逐项确认许可证、动态链接/服务调用方式和发布义务。当前更适合的策略是：

1. 自己保留 Emby Clean 的业务规则和数据模型。
2. 通过独立适配器调用或参考 Apache/MIT 许可的算法库。
3. 对 GPL/AGPL 项目只做隔离研究，先完成许可证审查再决定是否集成。

## 6. 建议的实施顺序

### Phase 1：规则安全化

- 修复扩展名处理。
- 建立欧美真实文件名 fixture。
- 实现站点上下文和完整多段编号匹配器。
- 输出 `confidence + evidence + matcher`。
- `smart` 在质量字段缺失时只生成候选，不自动选优删除。
- 生成规则变更前后差异报告。

### Phase 2：任务和删除安全

- 持久化扫描 Job。
- dry-run、审批/确认、审计、回滚或回收站。
- API 鉴权和敏感配置脱敏。
- STRM、Emby 项目、远程源文件分级处理。

### Phase 3：内容级查重

- 本地视频元数据和采样指纹。
- 海报精确/感知哈希。
- CMS/源端可用时再增加远程内容指纹。
- 质量策略从“大小优先”升级为可配置的来源、清晰度、码率、音轨、字幕和版本策略。

## 7. 当前验收标准草案

- `DorcelClub.15.01.01`、`.02`、`.03` 不再被合并成同一组；完整编号相同才可进入高置信度。
- `DudCast.com/02` 不会与其他站点目录下的 `02` 合并。
- `TMDBID-33238`、`MAN-365`、`VS-100` 等 Running man 元数据不会被通用短码规则当成重复。
- 欧美库的查重结果能展示命中的匹配器、规范化键、证据和置信度。
- `.strm` 质量字段缺失时，界面明确显示“无法按媒体质量选优”，不得静默按 0 大小决策。
- 规则扫描、删除计划和实际删除均可追溯；服务重启不会丢失任务状态。
- 配置导出不包含密码、访问令牌等敏感值。
- 在 FNOS 挂载暂时不可见、恢复或延迟时，不会把媒体误判为可删除。

## 8. 本轮结论

当前最应该做的不是直接增加更多正则，而是先把查重结果从“一个字符串分组”升级为“匹配器 + 证据 + 置信度 + 动作建议”。欧美规则可以先修复并覆盖命名场景，但真正可靠的跨来源查重还需要 STRM 源元数据和内容指纹能力。

本轮只读审查已完成；下一步应先确认规则模型和删除安全边界，再进入代码重构。
