# Kairos

*Know the right moment.*

An ML pipeline that reads Gmail, extracts **time commitments** — billing charge dates, delivery windows, deadlines, appointments — and turns them into calendar events. Built end-to-end as a personal project: data annotation standards, cost-aware model routing, ablation studies, and a mobile-first PWA calendar.

**English** · [中文]

---

## The problem

Personal inboxes are full of implicit future time points — credit-card due dates, subscription renewals, parcel ETAs, interview slots, submission deadlines. Nobody enters these into a calendar by hand, and missing an auto-charge has real monetary cost.

This is not keyword matching. The decision boundary is semantic:

- Same date pattern: "还款日 11/01" (due date) → extract; "账单余额 $2015" (balance, no date) → skip
- Same promotion: a flash-sale countdown → skip; *your membership expires on…* → extract
- "in 5 days" → compute it; "4–6 business days" is a range → skip; "soon" → skip
- Quoted historical dates inside a reply thread don't count

**Engineering goal:** not merely "gets it right", but *the cheapest architecture that satisfies recall = 1.0 as a hard constraint*. A missed deadline is a broken product (FN = grave); an extra calendar entry is a one-tap delete (FP = minor).

## Results

Held-out test set (n = 150, sealed throughout development, run exactly once):

| Metric | Score |
|---|---|
| Precision | **0.979** |
| Recall | **1.000** |
| F1 | **0.989** |
| Date accuracy | 0.979 |
| Type accuracy | 0.957 |

The single false positive was a community food-truck schedule — a case where human annotators could reasonably disagree.

### Five-way comparison (dev, n = 500, v2 gold labels)

| Approach | P | R | F1 | Full-corpus cost (31,175 emails) |
|---|---|---|---|---|
| Regex baseline | 0.672 | 0.847 | 0.749 | ~$0 |
| Haiku only | 0.711 | 0.967 | 0.819 | $73.86 |
| Sonnet only | 0.871 | 0.993 | 0.928 | $164.61 |
| Opus only | 0.872 | 1.000 | 0.932 | $399.70 |
| **Hybrid (this project)** | **0.919** | **1.000** | **0.957** | **$53.51** |

**The hybrid beats the strongest single model on every metric at 1/7.5 the cost.** Hybrid numbers are the mean of 3 independent runs (P 0.904 / 0.920 / 0.932); recall was 1.000 in all three, and even the worst run's precision (0.904) exceeded Opus (0.872).

## Architecture: four gates

Cheap, deterministic local checks bracket the LLM calls. Money is spent only where it protects recall.

```
Emails (500 in dev)
   │
   ├─ ① Rule pre-filter ──────────── hit → negative (250 emails, no LLM, $0)
   │     · Re:/Fwd: threads (22)          user already in the conversation
   │     · receipts w/o renewal date (17) v2: renewal date present → pass through
   │     · Gmail CATEGORY_PROMOTIONS (198), promo keywords (13)
   │
   ├─ ② Haiku extraction (250, with assistant prefill)
   │     ├─ "has commitment" → trusted
   │     └─ "no commitment" → gate ③
   │
   ├─ ③ Time-expression probe (local regex, $0) — recall protection
   │     · no time expression (17)      → trust the negative
   │     · all dates in the past (1)    → trust the negative
   │     · future/relative/duration expressions (77) → escalate
   │
   └─ ④ Sonnet review (no prefill) → trusted; recall recovered to 1.000
```

Design principles:

- **Only negatives get re-checked** — FN is the grave error, so the budget guards against misses, not over-extraction.
- **Only time-bearing negatives escalate** — an email with no date expression at all doesn't deserve an expensive model.
- **Gate ① is a hard negative** (a kill there is unrecoverable), so it holds only high-confidence rules, each validated corpus-wide with zero false kills.
- **Gate ③ errs toward escalation** — *today / 星期几 / within one week* all pass through; recall outranks cost.

### Why rules and LLMs are complements, not substitutes

Sonnet-only and Opus-only produce almost identical false positives (22 each): reply threads, receipts, statement notices. Scaling the model didn't touch these — because they aren't semantic questions. *"Is the user already in this conversation?"* is a subject-prefix check. *"Is this marketing?"* is answered better by Gmail's globally-trained classifier than by any LLM reading one email. After the rule layer removes them, the hybrid's precision exceeds both pure models.

Model cost knee: Sonnet (0.928) vs Opus (0.932) is a wash at 2.4× the price — the task saturates at the Sonnet tier, which is what makes the routing decision principled rather than thrifty.

## Data & evaluation methodology

- **Corpus:** 31,175 real personal emails via Gmail OAuth. Nothing synthetic — a hard constraint throughout.
- **Stratified sampling, not random.** True positive rate is ~5% (probed by an unconditioned random bucket: 3/60); pure random sampling of 500 would yield ~25 positives with confidence intervals too wide to compare architectures. Six type buckets (billing / promotion / delivery / deadline / appointment / random) lift the positive rate to 30%.
- **dev/test discipline.** All tuning on dev (500). Test (150) sealed until final sign-off, run once. When the v1 test set was burned by evaluation, it was demoted into dev and a fresh 150 re-sampled from the untouched 30,675 — with the *same* bucketing functions and a fixed seed, keeping the two batches comparable (positive rate 31.3% vs 30.0%).
- **Run hygiene:** cache cleared before every change; API failures never written to cache (a silent failure once masqueraded as "no commitment" and polluted a full round); token counts from `resp.usage`, not char estimates (which under-count Chinese/HTML by ~66%); key configs run 3× because weak models are nondeterministic (hybrid FP fluctuated 11–16); one variable changed at a time.
- **Ablation via a single flag** (`ABLATION_PURE_LLM`) — same code path, same prompt, so comparisons stay fair.

## The v1 → v2 annotation revision

While labeling the new test set, a conflict surfaced: Apple receipt emails often contain "续期 on 2024-05-15" — a definite future auto-charge, positive under the three positive criteria, yet v1's blanket exclusion "receipts ⇒ negative" killed them all. An audit found 47 of 66 receipts in dev (71%) carried future renewal dates, all labeled negative — with *zero labeling drift*. The flaw was in the standard itself: a form feature ("this is a receipt") had been allowed to override a content feature ("it contains a future charge date").

Product judgment settled it: auto-charges are exactly what users forget and exactly where losses are real. The standard was revised, 47 emails relabeled, and **every experiment re-run against v2** — half a day's cost, and the reason none of the numbers above are contaminated by a self-contradictory standard. Nine boundary rules (bills vs deadlines, delivery ranges, multi-event schedules, collection notices…) were accumulated case-by-case during annotation and are documented alongside the labels.

## Selected findings

- **Prompt rule placement is load-bearing.** With exclusion rules buried mid-prompt, Opus precision was 0.503 (40+ receipt FPs); moved to the front as a hard pre-check: 0.818, no recall loss. Same model, same rules.
- **Assistant prefill fixed weak-model JSON.** Haiku had 21 parse failures from prose wrapped around JSON; prefilling `{` forced pure JSON — failures dropped to 0. Sonnet/Opus rejected the prefill call pattern (400s), so the fallback runs without it — a reminder that tricks don't transfer silently between models.
- **Truncation is not free.** Hard-truncating bodies to 3,000 chars *lowered* precision — footers and unsubscribe boilerplate are negative-class evidence. Aggressive slicing broke recall on a "within one week" deadline that no date regex could see; a duration-expression regex restored it. Once rules filter the input, the LLM's ceiling is capped by the rules' recall.
- **A rule that is only right under the current data distribution is a coincidence, not a rule.** The regex baseline handled English/Chinese receipts asymmetrically; the data never exposed it (F1 moved 0.747 → 0.749 on the fix), but it was fixed on principle.

## Frontend

Dependency-free vanilla-JS PWA (no framework, no build step):

- Three-face segmented calendar: **All / Agenda / Bills**
- Mobile-first three-snap bottom sheet, swipeable month grid, bilingual UI (EN / 中文)
- Installable to the home screen; icon set in Petit Formal Script on warm paper, matching the app's editorial typography
- Data layer isolated behind `store.js` — switching `MODE = "demo"` to `"api"` is the only change needed to go live

## Known limitations

- **Timezones.** Send-date baseline is `internal_date` (UTC); the corpus spans CN/US-East/US-West/SG/AU and local event times aren't recoverable from metadata, so cross-midnight cases can disagree with lived experience.
- **Platform dependence.** `CATEGORY_PROMOTIONS` contributes 79% of gate ①'s filtering and is Gmail-specific; Outlook/IMAP migration needs a substitute (the `List-Unsubscribe` header is a candidate).
- **Positive-rate distortion.** Experiment sets run at 30% positives vs ~5% in the wild — production precision will be visibly lower than benchmark precision.
- **Keyword-list ceiling.** The promo lexicon was built from dev error analysis; test surfaced unseen phrasings ("Buy 2 Get 1 Free"). An inherent ceiling of lexicon methods, and the reason Gmail's label signal is in the loop.

## Project structure

```
kairos/
├── scripts/                 # ML pipeline
│   ├── fetch_emails.py         # Gmail OAuth ingestion
│   ├── annotate.py             # stratified sampling + labeling tool
│   ├── annotate_test.py        # sealed test-set labeling
│   ├── baseline.py             # regex baseline
│   ├── extract_llm.py          # four-gate hybrid cascade
│   ├── audit.py                # FP/FN root-cause analysis
│   ├── cost_curve.py           # cost/quality ablations
│   ├── dedup_test.py           # deterministic dedup tests
│   └── ...
└── web/                     # PWA frontend
    ├── index.html · manifest.json
    ├── scripts/                # i18n → store → app → calendar → onboarding
    └── styles/
```

Private data (email corpus, annotations, credentials) is excluded by design.

## Roadmap

- FastAPI backend: OAuth flow, SQLite persistence, APScheduler incremental extraction
- Calendar-layer policy (which extractions deserve a calendar slot) as a separate module with its own gold labels
- Calendar subscription feed (`.ics` / `webcal://`)

---

<a name="kairos-中文"></a>

# Kairos(中文)

*识其时。*

从 Gmail 中自动识别**时间承诺**——账单扣款、快递送达、截止日期、预约——抽取时间点与事件类型,生成日历事件。端到端个人项目:标注规范设计、成本感知的模型路由、消融实验、移动优先的 PWA 日历。

## 问题

个人邮箱里散落着大量隐含的未来时间点——信用卡还款日、订阅续费日、快递预计送达、面试预约、材料提交截止。不手动录入就容易错过,而自动扣款类的遗漏有真实金钱损失。

这不是关键词匹配,判断边界高度依赖语义:

- 同样有日期:"还款日 11/01" 要抽,"账单余额 $2015" 无扣款日不抽
- 同样是促销:限时优惠截止不抽,会员权益过期要抽
- "in 5 days" 要推算,"4–6 business days" 是区间不抽,"soon" 模糊不抽
- 邮件线程里被引用的历史日期不能算

**工程目标:**不只是"能做对",而是在 **recall = 1.0 为硬约束**下找到成本最低的方案。漏抓是重罪(用户错过 deadline 有实际损失),多抓是轻罪(日历多一条,删掉即可)。

## 结果

留出测试集(n = 150,开发全程封存,仅运行一次):

| 指标 | 分数 |
|---|---|
| 精确率 | **0.979** |
| 召回率 | **1.000** |
| F1 | **0.989** |
| 日期准确率 | 0.979 |
| 类型准确率 | 0.957 |

唯一的假阳性是一份社区餐车排班表——人工判断也存在争议的边界样本。

### 五方对照(dev, n = 500, v2 gold)

| 方案 | P | R | F1 | 全量成本(31,175 封) |
|---|---|---|---|---|
| 正则 baseline | 0.672 | 0.847 | 0.749 | ~$0 |
| 纯 Haiku | 0.711 | 0.967 | 0.819 | $73.86 |
| 纯 Sonnet | 0.871 | 0.993 | 0.928 | $164.61 |
| 纯 Opus | 0.872 | 1.000 | 0.932 | $399.70 |
| **混合架构(本项目)** | **0.919** | **1.000** | **0.957** | **$53.51** |

**混合架构在所有指标上超过最强单模型,成本为其 1/7.5。**混合结果为 3 次独立运行均值(P 0.904 / 0.920 / 0.932);三次 recall 均为 1.000,最差一次的 precision(0.904)仍高于 Opus(0.872)。

## 架构:四道门

廉价、确定性的本地检查夹住 LLM 调用,钱只花在保护召回的地方。

```
邮件(dev 500 封)
   │
   ├─ ① 规则前置过滤 ─────────── 命中 → 判负(250 封,不调 LLM,0 成本)
   │     · Re:/Fwd: 往返对话(22)        用户已亲自参与
   │     · 收据且无续期日(17)           v2:有续期日则放行
   │     · Gmail CATEGORY_PROMOTIONS(198)、促销词表(13)
   │
   ├─ ② Haiku 抽取(250 封,带 assistant prefill)
   │     ├─ 判"有承诺" → 采信
   │     └─ 判"无承诺" → 进门③
   │
   ├─ ③ 时间表达探测(本地正则,0 成本)—— 召回保护
   │     · 无任何时间表达(17)      → 采信负
   │     · 绝对日期全在过去(1)     → 采信负
   │     · 有未来/相对/时长表达(77)→ 升级
   │
   └─ ④ Sonnet 兜底复核(无 prefill)→ 采信;recall 兜回 1.000
```

设计原则:

- **只复核"判负"的**——漏抓是重罪,预算用于防漏而非防多抓。
- **只复核"有时间表达"的**——连日期都没有的邮件不配昂贵模型。
- **门①是 hard negative**(误杀无法挽回),因此只放高置信度规则,每条经全量验证零误杀。
- **门③宁可多升级**——today / 星期几 / within one week 一律放行,recall 优先于省钱。

### 为什么规则与 LLM 是互补而非替代

纯 Sonnet 与纯 Opus 的假阳性几乎完全相同(各 22 个):往返对话、收据、账单通知。堆模型一个都没解决——因为这些不是语义问题。"用户是否已参与此对话"是主题前缀的形式判断;"这是否营销邮件",Gmail 用全球邮件训练的分类器远胜任何 LLM 的临场判断。规则层清掉这两类后,混合架构的 precision 高于两个纯模型。

模型成本拐点:Sonnet(0.928)与 Opus(0.932)几乎无差异,成本差 2.4 倍——任务在 Sonnet 一档已饱和,这使路由决策有原则依据而非单纯省钱。

## 数据与评估方法

- **语料:**Gmail OAuth 全量拉取 31,175 封真实个人邮件;任何环节不生成、不臆造内容,是全程硬约束。
- **分层抽样而非随机。**真实正样本率仅约 5%(无条件 random 桶探针:60 封中 3 封);纯随机抽 500 只能得约 25 个正样本,置信区间宽到无法比较方案。六个类型桶(billing / promotion / delivery / deadline / appointment / random)把正样本率拉到 30%。
- **dev/test 纪律。**所有调优在 dev(500)上;test(150)全程封存,定稿后仅运行一次。v1 的 test 被评估"烧掉"后降级并入 dev,从未触碰的 30,675 封中重抽 150 封——复用同一分桶函数、固定随机种子,保证两批可比(正样本率 31.3% vs 30.0%)。
- **运行纪律:**每次改动前清缓存;API 失败不写缓存(曾有故障静默伪装成"无承诺"污染整轮评估);token 从 `resp.usage` 读取而非字符估算(后者对中文/HTML 低估约 66%);关键配置跑 3 次(弱模型非确定性,混合 FP 在 11–16 间波动);一次只改一个变量。
- **消融用单一开关**(`ABLATION_PURE_LLM`)——同一份代码、同一份 prompt,保证对照公平。

## v1 → v2:标注规范的一次重构

标注新 test 时发现冲突:Apple 收据正文常含"2024年05月15日续期"——明确的未来自动扣款日,按正样本三判据应为正,但 v1 排除条款"收据一律判负"把它们全砍了。核查发现 dev 中 66 封收据类里 47 封(71%)含未来续期日,全部标为负——且**零标注漂移**。问题在规范本身:形式特征("这是收据")压过了内容特征("里面有未来扣款日")。

产品判断决定取舍:自动扣款正是用户最容易忘、损失最实在的一类,必须进日历。规范修订、47 封重标、**全部实验对照 v2 重跑**——代价约半天,换来上面所有数字不被自相矛盾的规范污染。标注 150 封过程中逐条积累的九条边界规则(账单 vs 截止、送达区间、多事件排班表、催收类……)与标签一同存档。

## 关键发现

- **Prompt 中规则的位置是承重结构。**排除规则埋在长指令中间时,Opus precision 仅 0.503(71 个 FP 中 40+ 为收据);提到最前作为硬性前置检查后 0.818,recall 无损。同一模型、同一规则,仅改位置。
- **Assistant prefill 治好弱模型的 JSON。**Haiku 曾 21 次在 JSON 外附加解释文字导致解析失败;预填 `{` 逼其从 JSON 开头续写,失败归零。Sonnet/Opus 对该调用模式返回 400,兜底层因此不带 prefill——对 A 模型有效的技巧套到 B 模型会静默失败。
- **截断不是免费的。**硬截断到 3000 字符反而**降低** precision——页脚、退订链接是判负证据。激进切片击穿 recall:漏掉的样本("within one week")不含任何日期正则可命中的表达;补入时长正则后恢复。一旦规则做输入侧筛选,LLM 的上限就被规则的召回上限封顶。
- **只在特定数据分布下正确的规则不是规则,是巧合。**正则 baseline 曾对中英文收据非对称处理;数据恰好从未暴露(修正后 F1 0.747 → 0.749 几乎不变),但按原则修正。

## 前端

无依赖原生 JS PWA(无框架、无构建步骤):三面分段日历(**全部 / 日程 / 账单**)、移动优先三档抽屉、可滑动月历、双语界面、可安装到主屏。图标为暖纸上的 Petit Formal Script 花体 K,与应用的编辑排印气质同源。数据层收口于 `store.js`,`MODE = "demo"` 改 `"api"` 即接入后端。

## 已知限制

- **时区:**发送日基准为 `internal_date`(UTC);语料横跨中/美东/美西/新/澳,事件本地时间无法从元数据恢复,跨日界样本可能与用户实际体验不符。
- **平台依赖:**`CATEGORY_PROMOTIONS` 贡献门① 过滤量的 79%,是 Gmail 特有信号;迁移 Outlook/IMAP 需替代方案(`List-Unsubscribe` 头是候选)。
- **正样本率失真:**实验集 30% vs 真实约 5%,生产环境 precision 会显著低于实验值。
- **词表天花板:**促销词表基于 dev 错误分析构建,test 中出现未覆盖的新表述("Buy 2 Get 1 Free")。这是词表方法的固有上限,也是引入 Gmail 标签信号的原因。

## 目录结构与路线图

(同英文版。)私有数据(邮件语料、标注、凭证)按设计排除在仓库之外。下一步:FastAPI 后端(OAuth、SQLite、APScheduler 增量抽取)、日历层准入策略(独立模块、独立 gold)、`.ics` / `webcal://` 订阅源。
