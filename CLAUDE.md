# CLAUDE.md — Horizon 二次开发规范

> 本文件约束在本仓库中进行开发的所有会话（AI 与人）。它是**强制纪律**，不是建议。
> 本项目 fork 自上游 [Thysrael/Horizon](https://github.com/Thysrael/Horizon)，在其基础上做二次开发（下称"二开"）。
> 正文用中文，代码标记 / 命令 / 路径保持英文原样。

---

## 0. 核心哲学（先读这一条）

本项目的最高目标是：**持续吸收上游更新，同时让二开代码的同步成本最小**。

由此推导出一条铁律：

> **二开代码物理隔离在 `src/custom/`；对上游文件的侵入压到最少，且必须带标记。**

在动手写任何代码前，先问自己三个问题：

1. **能用配置解决吗？** → 能，就不要写代码（见 §4 LLM Endpoint 案例）。
2. **能放进 `src/custom/` 吗？** → 能，就绝不放进上游文件。
3. **非改上游不可吗？** → 那就只留一行薄 hook，逻辑本体放 `src/custom/`，并加 `HORIZON-CUSTOM` 标记（见 §3）。

---

## 1. 分支纪律

| 分支 | 用途 | 规则 |
|---|---|---|
| `main` | 二开正式分支 | 所有二开成果最终落这里 |
| `upstream-sync` | 上游纯镜像 | **禁止任何二开内容**；用 `git reset --hard upstream/main` 维护 |
| `feat/YYYYMMDDHH-xxx` | 功能开发 | 新分支**必须带时间戳** |
| `sync/YYYYMMDDHH-xxx` | 同步上游 | 同步验证专用，验证通过后再进 `main` |

- **新建分支必须带时间戳**，格式 `<type>/YYYYMMDDHH-<slug>`（沿用全局规范，精确到小时），例：`feat/2026082615-add-image`。
- **commit message / 分支命名等通用 git 规范以全局 `~/.claude/CLAUDE.md` 为准**（Conventional Commits + Emoji + 中文描述），本文件不重复，仅补充本仓库特有的分支角色（见上表）与同步流程（§2）。
- remotes：`origin` = 自己的 fork，`upstream` = Thysrael/Horizon。

---

## 2. 上游同步流程（低频按需 · merge 流 · 非 rebase）

同步节奏：**低频按需**（几个月一次，或上游有重大功能时）。不追求实时跟进。

标准步骤：

```bash
# 1. 把 upstream-sync 更新为上游最新镜像（该分支不含二开，允许覆盖式更新）
git fetch upstream
git checkout upstream-sync
git reset --hard upstream/main
git push origin upstream-sync --force-with-lease   # 可选

# 2. 开带时间戳的同步分支，从 main 出发
git checkout main
git checkout -b sync/YYYYMMDDHH-upstream

# 3. 合并上游（merge，不 rebase）
git merge upstream-sync

# 4. 解冲突：先跑审计清单，冲突基本只会出现在带标记的 hook 处
grep -rn "HORIZON-CUSTOM" src/

# 5. 验证：跑测试 + 手动跑一次任务，确认二开功能未被上游破坏
uv run pytest

# 6. 验证通过后再进 main
git checkout main
git merge sync/YYYYMMDDHH-upstream
```

- **禁止直接在 `main` 上 merge 上游**——必须经 `sync/` 分支验证缓冲。
- 冲突处理原则：`src/custom/` 里的代码几乎不会冲突；冲突点集中在 §3 的三行 hook 与 config 相关处，逐一比对标记即可。

---

## 3. 侵入标记规范（`HORIZON-CUSTOM`）—— 最重要的一条

任何对**上游文件**（`src/` 下 **非** `src/custom/` 的文件）的侵入式改动，**必须**用成对标记包裹：

```python
# >>> HORIZON-CUSTOM(场景名): 一句话说明 —— 二开代码，同步上游时勿删
custom_hook_call(...)          # 只留一行薄 hook，逻辑本体在 src/custom/
# <<< HORIZON-CUSTOM
```

规则：

1. **成对出现**：`# >>> HORIZON-CUSTOM(...)` 开，`# <<< HORIZON-CUSTOM` 闭。
2. **括号内写场景名**：`source` / `image` / `publish`，便于辨认属于哪个二开功能。
3. **hook 必须薄**：标记区内只放一行调用，真正的逻辑一律在 `src/custom/`。hook 越薄，同步冲突越小。
4. **审计清单**：每次同步上游后，运行

   ```bash
   grep -rn "HORIZON-CUSTOM" src/
   ```

   这就是**全部侵入点的检查清单**。逐一确认 merge 后仍然存在且正确。

> ⚠️ 为什么必须遵守：上游文件会被 merge 反复覆盖。没有标记，二开 hook 会在某次同步中被静默删除、或你无法辨认哪些是自己的改动。**不认识标记、不加标记、加错标记，都会导致二开功能悄悄失效。**

---

## 4. 二开配置约定（`data/custom.json` + 环境变量）

上游 `Config` 是 `extra="forbid"`，**禁止**往 `data/config.json` 塞自定义字段（会报错）。二开配置独立存放：

- **结构化配置** → `data/custom.json`，pydantic 模型定义在 `src/custom/config.py`，由 `src/custom/` 自己的加载器读取。
- **密钥类** → **环境变量**（`.env` / 容器注入），配置里只写**环境变量名**（沿用上游 `api_key_env` 惯例）。
- 上游 `data/config.json` 与 `src/models.py::Config` **保持原样，一律不动**。

---

## 5. 具体功能的实现细节

各二开功能（自定义源、文章配图、文章上传、LLM Endpoint 配置）的落点、数据流、hook 位置等**实现细节**，见：

> 📄 [`docs/二开实现细节.md`](docs/二开实现细节.md)

CLAUDE.md 只承载跨任务恒定的纪律；实现细节按需查阅 docs，避免每次会话都加载大量与当前任务无关的内容。

---

## 6. 开发工作流约束（约束 AI 会话）

1. **新功能一律进 `src/custom/`**。除非物理上无法（必须 hook 进上游），否则不碰上游文件。
2. **碰上游文件 → 必加 `HORIZON-CUSTOM` 标记**（§3），且只留薄 hook。
3. **能配置解决的绝不写代码**（§0 三问）。
4. 二开配置进 `data/custom.json` / 环境变量，**不碰上游 `config.json` 与 `Config` 模型**（§4）。
5. 每日任务健壮性优先：二开功能失败应**静默降级**，不拖垮主流程。
6. 同步上游后，运行 `grep -rn "HORIZON-CUSTOM" src/` 审计所有侵入点，并跑 `uv run pytest` + 手动跑一次任务验证。
7. 二开代码应有对应测试，放在 `tests/`（可用 `tests/custom/` 子目录归拢）。
