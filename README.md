# Kairos

*Know the right moment.*

**English** · [中文](#kairos-中文)

---

**Your inbox knows your next month better than you do** — which day money leaves the account, which deadline lands, which parcel arrives, which table was booked. The information was always there, buried between two hundred promotions. Last month, when an $89.99 annual fee went through, the reminder email had arrived long before; the moment it was scrolled past, that money was already gone.

Kairos does the retrieving. Once an hour it reads Gmail and pulls out every time commitment hiding in there — billing dates, deadlines, deliveries, reservations — onto a calendar with two faces: schedule and bills. Deciding whether a date matters to a user is not keyword matching: the same date must be caught in a payment reminder and ignored in a flash-sale countdown. That takes an AI model reading every email — and running the strongest model on everything costs too much to be realistic. Kairos answers with a four-stage pipeline: **free checks first, expensive models only when necessary — no commitment missed, higher accuracy than running the strongest model throughout, at one-seventh the cost.**

This is not a demo. It is deployed, serves six real users, runs on its own every hour — and its first week in production delivered a full cycle of failures, diagnoses and self-healing, documented honestly in the second half of this page.

## What it does

📬 **Automatic capture** — Once connected to Gmail, Kairos reads new mail every hour and turns time commitments into calendar events: billing dates, subscription renewals, parcel deliveries, assignment deadlines, restaurant and salon bookings. No manual input, ever.

📅 **A calendar with three faces** — Switch between **All**, **Schedule** (things you do: appointments, deadlines, deliveries) and **Bills** (things that cost you: subscriptions, payments), each with its own color coding.

🔄 **Deduplication and lifecycle** — Three emails about the same renewal produce one event, not three. When a merchant reschedules, the event moves. When a booking is cancelled, the event disappears on its own.

✍️ **Manual entries** — The + button adds your own events alongside the extracted ones.

📱 **Installs like an app** — Open in Safari, "Add to Home Screen": a standalone app with its own icon, bilingual UI (EN / 中文).

## Results

Tested on 150 real emails that were sealed away throughout development and evaluated exactly once: **every commitment was caught, with a single false alarm** — one community food-truck schedule that human annotators could reasonably disagree on.

| Metric | Score |
|---|---|
| Precision | **0.979** |
| Recall | **1.000** |
| F1 | **0.989** |
| Date accuracy | 0.979 |
| Type accuracy | 0.957 |

<sub>Precision = of everything reported, how much was right. Recall = of everything that should have been caught, how much was caught. The test set holds 47 positives; for an all-hit result the Clopper–Pearson 95% lower bound is 0.025<sup>1/47</sup> ≈ 0.925 — the data supports "recall is high", not "recall is exactly 100%".</sub>

The pipeline was benchmarked against every simpler and every more expensive alternative, on a 500-email development set (v2 gold labels; hybrid figures are the mean of 3 independent runs):

| Approach | Precision | Recall | F1 | Cost @ 31,175 emails |
|---|---|---|---|---|
| Regex baseline | 0.672 | 0.847 | 0.749 | ~$0 |
| Haiku only | 0.711 | 0.967 | 0.819 | $73.86 |
| Sonnet only | 0.871 | 0.993 | 0.928 | $164.61 |
| Opus only | 0.872 | 1.000 | 0.932 | $399.70 |
| **Kairos (4-gate hybrid)** | **0.919** | **1.000** | **0.957** | **$53.51** |

**The hybrid beats the strongest single model on every metric at 1/7.5 the cost.** Even its worst run (P 0.904) stayed above Opus. Dollar amounts assume the gate-① filter rate of the author's own inbox; production data later showed that rate varies sharply by inbox type (58% vs 3%), so read them as orders of magnitude — the *relative* advantage is unaffected, since all approaches face the same distribution.

---

*The sections below are written for engineering readers. If you just wanted to know what Kairos is — you already do.*

## The problem, precisely

**Input judgment — what counts as a commitment.** An email contains a commitment when three tests pass at once and no exclusion applies:

1. **It concerns the user** — the date marks something the recipient will experience or owe. A flash sale's deadline is the merchant's business; a membership expiry is the user's.
2. **It lies in the future** — measured against the email's send time. A completed delivery or an already-charged payment carries no action value.
3. **It has an explicit time point** — an absolute date ("Sep 15"), or a precisely computable relative one ("in 3 days"). "Soon", "your next billing cycle" do not qualify — **a date the email never stated must never be invented.**

Exclusion rules handle the boundaries: cancelled or completed events don't count; dates quoted inside reply threads don't count; a receipt is not a commitment — but the *next-renewal date inside* a receipt is (content overrides form; this single distinction forced a full revision of the annotation standard, see below).

The same date pattern, opposite verdicts: *"Payment due 11/01"* → extract. *"Your statement balance: $2,015"* → skip.

**Output structure — what an event looks like.** Every extraction produces `{type, datetime, title}`:

- **type** ∈ billing (money leaves) · appointment (you show up) · deadline (you act by) · delivery (something arrives)
- **datetime** — minute precision when the email states a time, date-only otherwise; never finer than the source
- **title** — must be recognizable on a calendar with no context: billing titles carry *product + cycle + amount*, never a bare "subscription renewal" — the same day can hold three different renewals

The criteria define what is correct; the next section is the architecture that approaches it under a cost constraint.

## The four-gate pipeline

Every email raises the same question. The naive answer — send everything to the strongest model — costs $399.70 across a 31,175-email corpus. Kairos routes each email through four gates, ordered from free to expensive:

```
Email
  │
  ├─ ① Rule pre-filter ────────── hit → negative (no LLM, $0)
  │     Re:/Fwd: threads · receipts without renewal dates
  │     Gmail's own promotions label · promo keywords
  │
  ├─ ② Haiku extraction (cheap model, with prefill*)
  │     ├─ "has commitment" → trusted
  │     └─ "no commitment"  → gate ③
  │
  ├─ ③ Time-expression probe (local regex**, $0)
  │     no future-time expression in the body → trust the negative
  │     future / relative / duration expression found → escalate
  │
  └─ ④ Sonnet review (stronger model) → final verdict
```

<sub>\* prefill: pre-seeding the model's answer with `{` to force pure-JSON output — it eliminated all 21 JSON parse failures Haiku produced without it. Sonnet and Opus reject this call pattern, so gate ④ runs without it.<br>\*\* regex: mechanical matching against fixed text patterns, e.g. recognizing any string shaped like a date.</sub>

**Model selection follows traffic × unit price, not raw capability.** Gate ② must process every email the rules did not stop, so its unit price is multiplied by the largest volume and must be the cheapest available. Gate ④ handles only escalated cases (77 of 500 on dev), where an expensive model's marginal cost is acceptable. Sonnet-only (F1 0.928) and Opus-only (0.932) are nearly indistinguishable at 2.4× the price — the task saturates at the Sonnet tier, and stacking stronger models buys nothing.

Four design principles hold this together:

- **Only negatives get re-checked.** A missed deadline is a broken product; a stray extra event is a one-tap delete. The budget guards against misses.
- **Only time-bearing negatives escalate.** An email with no future date in it does not deserve an expensive model.
- **Gate ① must never wrongly kill.** A kill there is unrecoverable, so it holds only rules validated across the full corpus with zero false kills.
- **Gate ③ errs toward escalating.** "today", "next Friday", "within one week" all pass through — completeness outranks cost.

**Why rules and LLMs are complements, not substitutes.** In an ablation study (removing one component at a time and measuring the damage), stripping the rule layer cost 0.21 of precision *and* increased cost; stripping the Sonnet fallback dropped recall from 1.000 to 0.967. The reverse experiment is just as telling: Sonnet-only and Opus-only produce nearly identical false positives — reply threads, receipts, marketing — because these are not semantic questions. *"Is the user already in this conversation?"* is a subject-prefix check. *"Is this marketing?"* is answered better by Gmail's globally-trained classifier than by any LLM reading one email. **No amount of model strength fixes a problem the model was never the right tool for.**

## How this differs from existing solutions

Calendar software and email clients have existed for years, yet their automation stops at the same line: **they only handle data that has already been structured.**

**Gmail and Google Calendar's automatic entries** depend on machine-readable formats — meeting invitations with .ics attachments, standardized flight and hotel confirmations. Such emails are a small fraction of a real inbox. A human-written *"see you at the salon on the 20th"*, a renewal date embedded in an invoice body, a payment deadline inside a university notice — none are covered. Kairos targets precisely these semantic commitments in free text.

**Reminders built into mail clients** are passive: the information stays inside the email and the user must remember to go looking. Kairos consolidates time points scattered across hundreds of emails into one scannable surface.

**Manual-entry calendars** (natural-language calendar apps) extract well, but only once the user has noticed an email contains a date and copied it over. The difficulty is precisely that users do not notice: what needs automating is **discovery**, not entry.

**Positioning.** Kairos does not attempt to replace calendar applications, nor to be a mail client. It focuses on the layer from unstructured email to time commitment, and makes the quality and cost of that layer measurable. Accordingly, exporting as a subscribable calendar feed (.ics / webcal) ranks above further polishing of its own UI in the roadmap: letting extractions flow into the calendar a user already keeps beats asking them to switch.

## System architecture

The pipeline is the brain; the rest of the system exists so that six people can trust it with their inboxes:

```
Gmail ──OAuth──▶ FastAPI backend ──▶ SQLite (persistent volume)
                   │                   users · events · sync_state
                   │                   extraction_log · sessions
                   ├─ hourly scheduler: per-user incremental sync
                   └─ session auth: cookie → user, every query scoped
                                        │
                             PWA frontend (vanilla JS)
```
<sub>As of week one in production: 6 users · ~200 emails/day · under $0.5/day.</sub>

- **OAuth, minimal scope** — read-only Gmail; Kairos can never send or delete mail. The server holds a long-lived refresh token per user (the credential that lets it work while you sleep), exchanged hourly for short-lived access tokens.
- **Session login** — server-side sessions (a random token in a cookie, mapped to a user in the database — chosen over stateless signed cookies for instant revocability). Every query is scoped by the resolved user id; data isolation was verified end-to-end with two accounts before any external user joined.
- **Incremental sync** — a per-user cursor (the timestamp of the newest processed email) means each hourly run fetches only what's new. The cursor advances *only after the whole batch succeeds*: a failed run costs nothing and retries itself.
- **Idempotent writes** — a three-tier dedup key (real order number > sender domain + type + date + title fingerprint > product terms) plus a same-email guard absorb replays, so re-processing never duplicates events — which makes "rewind the cursor and replay" a safe recovery tool.
- **Event lifecycle** — reschedules move events in place; cancellation emails soft-delete them (the row stays, flagged `cancelled` — reversible, auditable). A keyword guard forces cancellation handling even when the model forgets to flag it: rules backstop models, the project's recurring theme.
- **Every verdict is logged** — email id, deciding gate, verdict, token cost, resulting event ids. This table answers "why is/isn't X on my calendar?" in one query, and doubles as a live cost monitor. It is also, quietly, a growing training set.

Deployed on Railway (HTTPS, persistent volume, auto-deploy from main).

## Data & evaluation methodology

Every number on this page traces back to one corpus and one discipline.

- **31,175 real personal emails**, pulled via Gmail OAuth. Nothing synthetic, ever — fabricated emails would validate nothing about the real distribution.
- **Stratified sampling against a 5% prior.** Randomly sampled, a 500-email set would contain ~25 positives — confidence intervals too wide to compare architectures. Sampling across six type buckets lifted the positive rate to 30%:

| Bucket | Trigger keywords (subject + first 2,000 chars) | dev | test |
|---|---|---|---|
| billing | bill / invoice / payment / subscription / renew / 账单 / 续期 | 130 | 39 |
| promotion | sale / deal / off / discount / promo / 促销 / 优惠 | 120 | 36 |
| delivery | ship / deliver / order / package / track / 发货 / 物流 | 70 | 21 |
| deadline | deadline / due / expire / reminder / submit / 截止 / 到期 | 60 | 18 |
| appointment | appointment / reservation / booking / schedule / 预约 / 预订 | 60 | 18 |
| random | unconditional random | 60 | 18 |

  The five typed buckets carry a precondition: an email must contain a date expression first, or it is skipped even on a keyword hit — otherwise a bucket fills with emails that carry billing vocabulary but no temporal information, a class that is almost always negative. **The random bucket carries no such condition; it is a probe of the true prior** — 3 of its 60 emails contain a commitment. That 5% is where the number above comes from, and it is the empirical basis for claiming a filter layer is worth having.

- **A sealed test set.** All tuning happened on the 500-email dev set. The 150-email test set stayed untouched until the design was frozen, then ran exactly once. The original test set had been looked at too many times during development to stay unbiased, so it was demoted into dev and a fresh 150 re-sampled from the untouched 30,675, using the same bucketing functions and a fixed random seed; **the new set was labeled and sealed before the final architecture was frozen**, ruling out choosing the exam after seeing the score.
- **Run hygiene.** Cache cleared before every change; failed API calls never written to cache (a silent failure once masqueraded as "no commitment" and poisoned a full round); token counts read from the API's own usage field, not character estimates (which undercount Chinese and HTML by ~66%); key configurations run three times because weak models are nondeterministic — the hybrid's false-positive count fluctuated between 11 and 16 across identical runs; one variable changed at a time.
- **Ablations via a single flag** — pure-LLM baselines run the same code path and the same prompt as the full pipeline, so every comparison is under identical conditions.

### Selected findings

- **Where a rule sits in the prompt is load-bearing.** With exclusion rules buried mid-prompt, precision was 0.503 (40+ of 71 false positives were receipts); moved to the front as a hard pre-check: 0.818, with no loss of recall. Same model, same rules, only position.
- **Truncation is not free.** Hard-cutting bodies at 3,000 characters *lowered* precision — footers and unsubscribe links are evidence of the negative class. Aggressive slicing also broke recall on a "within one week" deadline no date-regex could see; a duration-expression pattern restored it.
- **A rule that is only right under the current data distribution is a coincidence, not a rule.** The regex baseline handled English and Chinese receipts asymmetrically; the data never punished it (F1 moved 0.747 → 0.749), but it was fixed on principle.

## The annotation standard had a bug

While labeling the test set I hit a contradiction. Apple receipts often contain *"renews on 2024-05-15"* — a definite future charge, a commitment by every test in the definition. But the v1 standard said *receipts ⇒ negative*, unconditionally.

An audit showed the scale: **47 of 66 receipt emails in dev (71%) carried future renewal dates, all labeled negative** — with zero labeling drift. The standard itself was wrong: a form feature ("this is a receipt") was overriding a content feature ("it contains a future charge").

Fix: standard rewritten, 47 emails relabeled, **all experiments re-run against v2**. Cost: half a day. Result: no number on this page rests on a self-contradictory definition.

## One week in production

The pipeline scored 0.989 on the test set. Then real users arrived, and the first week found five problems no benchmark could have surfaced. Each was diagnosed through `extraction_log` — the per-email audit table — usually within minutes.

**1. The silently swallowed mail.** A user reported a missing utility bill. The log ruled out misclassification: the email was never processed at all. Root cause: Gmail's list API returns newest-first, one page at a time — the code read one page, then advanced the sync cursor past *everything*, permanently locking older mail out. It had never fired before because hourly increments fit in one page; a first-time user's 7-day backlog didn't. Fix: pagination plus a per-run cap. Recovery: rewind cursors, replay — safe because writes are idempotent. Zero data lost.

**2. The scheduler that never ran.** "Hourly sync" had in fact never fired once: APScheduler's `next_run_time=None` doesn't mean "don't run immediately" — it adds the job *paused*. Every "automatic" sync until then had been me, manually. One parameter fixed; the first genuinely autonomous heartbeat followed 90 seconds after deploy, processing all six users. Logs since confirm the hourly cycle has not missed a beat.

**3. Broken keys heal themselves.** One user's Google authorization came back without the Gmail permission (`invalid_scope` on every refresh). Under the old behavior this meant silent hourly failures behind a "connected" facade. The system now detects authorization-level errors, marks the account expired, skips it in scheduling, and surfaces a "reconnect" button — the user re-authorized herself and her data flowed the same hour, no operator involved.

**4. Same charge, two events.** For one subscription renewal the platform sent both a confirmation and an invoice; their titles differed by one word, splitting the dedup fingerprint and putting two entries for the same charge on the same day. Fix direction: introduce the amount as an identity signal alongside the title fingerprint.

**5. The model invents dates.** The most dangerous error class found so far, in two variants within one week. One email stating a plan *"will increase to $118 every 2 months from the next cycle"* produced a charge date computed as **send date + two months** — the email gave a cycle, never that date. Two "action required" notices contained **no date material whatsoever** and were each assigned one anyway. The third criterion in the commitment definition already forbids this; the next prompt revision promotes it from definition to hard instruction. **Verification plan**: regression-test on a slice containing these samples, and monitor the share of "event produced from no date material" in the audit log as an ongoing metric — a fix without a way to verify it is not a fix.

The same log that caught these bugs also reprices the architecture: my inbox is 8% commitments and gate ① filters 58% for free; a friend's university-forwarded inbox is 42% commitments and gate ① catches just 3%. **Gate ①'s savings depend on inbox type — a fact no development set could reveal.**

## In hindsight

- **The audit log should have existed from day one.** It went on to solve every production problem: locating missed mail, distinguishing "misjudged" from "never processed", correcting the cost model. It arrived mid-project, which made every earlier investigation far more expensive.
- **"Observe a heartbeat after deploying" belongs in the acceptance routine.** The scheduler lay dormant for days because of one parameter's semantics; the transferable lesson is broader: **any feature claiming to be automatic needs observable evidence that it has actually run automatically**, or "automatic" is merely a belief.
- **A sender's plain-text alternative cannot be trusted.** Body extraction originally preferred `text/plain`, until a utility bill's plain-text version was found to have dropped a decimal point ($103.24 rendered as $10324) while its HTML was correct; separately, institutional emails without a plain-text part caused the old implementation to swallow 70,614 characters of raw HTML. Extraction now prefers HTML with structured conversion, with plain text as fallback.

## Known limitations

- **Gmail only.** Gate ① leans on Gmail's own promotions label (58% of its filtering on a typical personal inbox); Outlook/IMAP would need a substitute, and institutional mailboxes join via forwarding. Effectively unavailable in mainland China (Gmail, Google OAuth and the hosting domain are all blocked).
- **Calendar subscription and export are not implemented.** The frontend keeps an entry point for adding external .ics feeds, but the backend endpoints don't exist; the reverse — exporting extractions as a webcal/.ics feed subscribable by a system calendar — is likewise planned but unbuilt. Kairos is currently a standalone view that does not interoperate with system calendars.
- **Trust boundary on cancellation.** Cancellation currently matches on sender-domain-agnostic signals (falling back to type + date), so a crafted email could soft-delete an event a user has, if the attacker knows it exists. Mitigation planned: require sender-domain match with the original event; cross-domain cancellations downgrade to a prompt rather than an automatic delete. Low-risk within a trusted beta; a hard requirement before any public release.
- **Benchmark precision is not production precision.** Experiment sets run at 30% positives against a ~5% wild rate; production precision is expected to fall visibly below 0.979 — the audit log exists to measure exactly that.
- **First-sync window.** A new user's first sync reaches back 7 days; older commitments don't appear. A "backfill further" option is planned.
- **Chinese-first titles, by design.** Annotation and evaluation were conducted in Chinese, so extraction titles are Chinese-first. Language-aware output is deliberately deferred: titles feed the dedup fingerprint, so changing output language invalidates existing merge keys — it ships with the next prompt revision, batched with a full re-evaluation.
- **Cancellation matching can be fuzzy.** When the exact fingerprint misses, cancellation falls back to same-type-same-day matching — ambiguous if a day holds two events of one type.
- **Relative dates near midnight.** Event dates anchor on the email's UTC arrival; when a body says "tomorrow" and the mail lands near the user's local midnight, the computed date can be off by one day. Absolute dates — the vast majority — are unaffected.

## Project structure

```
kairos/
├── scripts/     ML pipeline & evaluation: sampling, labeling tools,
│                the four-gate extractor, ablations, dedup tests
├── server/      FastAPI backend: OAuth, sessions, hourly scheduler,
│                ingest & dedup, SQLite layer
└── web/         PWA frontend: vanilla JS, no build step
```

Private data — the email corpus, annotations, credentials, databases — is excluded by design.

| Layer | Stack |
|---|---|
| ML pipeline | Anthropic API (Claude Haiku 4.5 extraction · Sonnet 5 fallback) · hand-written regex rule layer · prompt engineering (assistant prefill, body slicing) |
| Data & evaluation | Python · stratified sampling and annotation tooling · single-flag ablation framework · true token accounting |
| Backend | FastAPI · SQLite (WAL) · APScheduler · Google OAuth 2.0 (authorization-code flow) · server-side session auth · html2text |
| Frontend | Vanilla-JS PWA (no framework, no build step) · custom spring animations · version-query cache busting · EN/中文 i18n |
| Infrastructure | Railway (container deploy · persistent volume · HTTPS · auto-deploy from main) · Gmail API |

## Roadmap

- **Prompt v3** — enforce "no date invented" as a hard instruction; language-aware titles; re-run full evaluation.
- **Calendar export** — .ics / webcal feed, so extractions flow into the calendar users already keep (ranked above further work on the built-in UI).
- **Dedup v2** — amount as an identity signal; sender-domain validation on cancellations.
- **Calendar admission policy** — some extractions are correct but don't deserve a calendar slot (a gym's power-outage notice); a separate layer with its own labels.
- **Multi-mailbox** — one user, several inboxes, one calendar.
- **Distill gate ②** — the extraction log accumulates (email features → verdict) pairs; enough of them become training data for a small local classifier to replace the Haiku call. The pipeline was built API-first to validate the task — **and the data it generates is how it eventually stops paying for itself.**

---

*Built by Tiansheng Chen · [github.com/tiansheng-chen](https://github.com/tiansheng-chen)*

---

<a name="kairos-中文"></a>

# Kairos(中文)

*识其时。*

**多数人的邮箱比他们本人更清楚下一个月会发生什么**——哪天扣款、哪天截止、哪天有快递、哪天订了餐厅。这些信息一直存在,只是埋在两百封促销邮件中间。上个月某笔 $89.99 的年费被划走时,提醒邮件其实早就来过;它被划过去的那一刻,这笔钱就已经注定要丢。

Kairos 替用户打捞。它每小时读取一次 Gmail,把每一个藏在邮件里的时间承诺——扣款日、截止日、送达日、预约——自动挖出来,放上一份"日程 + 账单"双面日历。判断"这个日期与用户是否相关"没法靠关键词:同一个日期,在还款提醒里必须抓住,在促销倒计时里必须忽略——这需要 AI 逐封阅读;而全程使用最强模型,贵到不现实。Kairos 的答案是一条四级流水线:**免费的检查在前,昂贵的模型只在必要时出手——没有漏掉任何一条承诺,准确率反超全程最强模型的方案,成本只有它的七分之一。**

它不是一个演示。它已部署上线,服务六名真实用户,每小时自主运行——并在上线第一周经历了完整的故障、定位与自愈,本文后半部分如实记录了这一切。

## 它能做什么

📬 **自动抓取** —— 连上 Gmail 后,每小时读取一次新邮件,把时间承诺变成日历事件:账单扣款、订阅续费、快递送达、作业截止、餐厅与门店预约。永远不需要手动录入。

📅 **三面日历** —— 顶部切换**全部**、**日程**(要去做的事)与**账单**(要花钱的事),各有配色。

🔄 **去重与生命周期** —— 同一笔续费的三封邮件只产生一条事件。商家改期,事件跟着移动;预约取消,事件自动消失。

✍️ **手动添加** —— ＋ 按钮加入自己的事件,与自动抽取的混排。

📱 **像 App 一样安装** —— Safari"添加到主屏幕",带独立图标,中英双语。

## 结果

在 150 封开发全程封存、仅评估一次的真实邮件上:**所有承诺全部命中,误报仅一例**——一份社区餐车排班表,人工标注者也会分歧的边界样本。

| 指标 | 分数 |
|---|---|
| 精确率 | **0.979** |
| 召回率 | **1.000** |
| F1 | **0.989** |
| 日期准确率 | 0.979 |
| 类型准确率 | 0.957 |

<sub>精确率 = 报出来的里面多少是对的;召回率 = 该抓的里面抓住了多少。测试集含 47 个正样本,全中情形下 Clopper–Pearson 95% 置信下界 = 0.025<sup>1/47</sup> ≈ 0.925——数据支持"召回率很高",而非"恰为 100%"。</sub>

与每一个更简单、以及每一个更昂贵的替代方案对照(500 封开发集,v2 标注;混合架构为 3 次独立运行均值):

| 方案 | 精确率 | 召回率 | F1 | 全量成本(31,175 封) |
|---|---|---|---|---|
| 正则基线 | 0.672 | 0.847 | 0.749 | ~$0 |
| 纯 Haiku | 0.711 | 0.967 | 0.819 | $73.86 |
| 纯 Sonnet | 0.871 | 0.993 | 0.928 | $164.61 |
| 纯 Opus | 0.872 | 1.000 | 0.932 | $399.70 |
| **Kairos(四道门混合)** | **0.919** | **1.000** | **0.957** | **$53.51** |

**混合架构在所有指标上超过最强单模型,成本为其 1/7.5。**最差的一次运行(精确率 0.904)仍高于 Opus。美元金额基于作者本人邮箱的门①过滤率;生产数据显示该比率随邮箱类型显著变化(58% 与 3%),故应视为量级参考——**相对优势不受影响**,所有方案面对同一分布。

---

*以下面向工程读者。如果你只想知道 Kairos 是什么——你已经知道了。*

## 精确地定义问题

**输入侧判据——什么算承诺。**三条判据同时成立,且不触发排除规则:

1. **与用户相关**——日期标记的是收件人将经历或承担的事。限时促销的截止日是商家的事;会员到期日才是用户的事。
2. **在未来**——以邮件发送时刻为基准。已完成的送达、已扣的款,没有行动价值。
3. **有明确时间点**——绝对日期("9 月 15 日"),或可精确推算的相对表达("3 天后")。"尽快""下个账单周期"不算——**邮件没有写出的日期,永远不许被编造出来。**

排除规则处理边界:已取消/已完成的不算;回复串中引用的历史日期不算;收据本身不是承诺,但收据**里面**的"下次续期日"是(内容压过形式;仅这一条区分就迫使标注规范做了全量修订)。

同样的日期形态,相反的裁决:*"还款日 11/01"* → 抽取;*"账单余额 $2,015"* → 忽略。

**输出侧结构——一条事件长什么样。**每次抽取产出 `{类型, 时间, 标题}`:

- **类型** ∈ billing(要扣钱)· appointment(要到场)· deadline(要在此前完成)· delivery(有东西到达)
- **时间**——邮件写明时刻则精确到分,否则只到日;永不比原文更精细
- **标题**——无需上下文即可认出:billing 必含*商品+周期+金额*("芒果TV 连续包月 ¥18"),绝不允许裸写"订阅续期"——同一天可能有三笔不同续费

判据定义了"对错";下一节是在成本约束下逼近它的架构。

## 四道门流水线

每封邮件要回答的问题相同。最朴素的答案——每封都交给最强模型——在 31,175 封语料上要花 $399.70。Kairos 让每封邮件依次通过四道门,从免费到昂贵:

```
邮件
  │
  ├─ ① 规则前置过滤 ────────── 命中 → 判无承诺(不调模型,0 成本)
  │     Re:/Fwd: 往返对话 · 无续期日期的收据
  │     Gmail 自带的促销标签 · 促销关键词
  │
  ├─ ② Haiku 抽取(便宜模型,带预填*)
  │     ├─ 判"有承诺" → 采信
  │     └─ 判"无承诺" → 进入门③
  │
  ├─ ③ 时间表达探测(本地正则**,0 成本)
  │     正文无任何未来时间表达 → 采信"无承诺"
  │     发现未来 / 相对 / 时长表达 → 升级复核
  │
  └─ ④ Sonnet 复核(更强模型)→ 最终裁决
```

<sub>\* 预填(prefill):预先替模型写下答案的第一个字符 `{`,强迫它输出纯 JSON——此前 Haiku 有 21 次在 JSON 外附加解释文字导致解析失败,预填后归零;Sonnet 与 Opus 不支持该调用形态,故门④不使用。<br>\*\* 正则:按固定文本模式做的机械匹配,如识别任何"X月X日"形态的字符串。</sub>

**模型选型由流量乘以单价决定,而非能力排序。**门②须处理全部未被规则拦下的邮件,单价乘以最大流量,因此必须取最便宜者;门④仅处理被升级的样本(开发集 77/500),昂贵模型的边际成本可接受。此外纯 Sonnet(F1 0.928)与纯 Opus(0.932)差异甚微而成本相差 2.4 倍——任务在 Sonnet 一档已饱和,继续堆模型无收益。

四条设计原则:**只复核判"无"的**(漏抓是重罪,多抓删一下就好);**只复核含时间表达的**(连未来日期都没有的邮件不配昂贵模型);**门①绝不误杀**(此处误杀无法挽回,只放全量验证零误杀的规则);**门③宁可多升级**("今天""下周五""一周内"一律放行)。

**规则与 LLM 是互补,不是替代。**消融实验(每次拆除一个部件、度量性能损失)中:拆掉规则层,精确率掉 0.21 且成本反升;拆掉 Sonnet 兜底,召回率从 1.000 跌到 0.967。反向实验同样说明问题:纯 Sonnet 与纯 Opus 的误报几乎完全相同——回复串、收据、营销邮件——因为这些根本不是语义问题。*"用户是否已在这场对话中"*是主题前缀检查;*"这是不是营销"*,Gmail 用全球邮件训练的分类器远胜任何 LLM 的单封阅读。**模型再强,也修不好一个本就不该由模型解决的问题。**

## 与现有方案的区别

日历软件与邮件客户端已存在多年,其自动化程度却停在同一条线上:**只处理已被结构化的数据**。

**Gmail 与 Google Calendar 的自动添加**依赖机器可读的格式——带 .ics 附件的会议邀请、航班与酒店的标准化确认信。此类邮件在真实收件箱中占比很小。一封人写的"记得 20 号来店里"、一封账单正文中夹带的续期日、一封校方通知中的缴费截止,均不在其覆盖范围内。Kairos 处理的正是这部分自由文本中的语义承诺。

**邮件客户端的内置提醒**是被动的:信息仍留在邮件里,用户须自行想起并翻找。Kairos 将分散于数百封邮件中的时间点汇聚为一个可扫视的时间面。

**手动录入型日历**(自然语言日历应用)抽取质量很高,但前提是用户先意识到"这封邮件里有一个日期"并主动复制过去。而问题恰恰在于用户意识不到:需要被自动化的是**发现**,而非录入。

**定位取舍**:Kairos 不试图取代日历应用,也不做邮件客户端,而专注于"从非结构化邮件到时间承诺"这一层,并把这一层的质量与成本做到可测量。因此路线图中,导出为可订阅日历源(.ics / webcal)的优先级高于继续打磨自有界面——让抽取结果流入用户已在使用的日历,比要求用户更换日历更合理。

## 系统架构

流水线是大脑;系统的其余部分,是为了让六个人放心把邮箱交给它:

```
Gmail ──OAuth──▶ FastAPI 后端 ──▶ SQLite(持久卷)
                   │                users · events · sync_state
                   │                extraction_log · sessions
                   ├─ 每小时调度:按用户增量同步
                   └─ 会话鉴权:cookie → 用户,每条查询按用户隔离
                                        │
                              PWA 前端(原生 JS)
```
<sub>生产第一周快照:6 名用户 · 约 200 封/天 · 每日成本 < $0.5。</sub>

- **OAuth 最小权限** —— 只读 Gmail,永远不能发送或删除。服务器为每位用户保管一把长期刷新令牌(让它能在你睡觉时工作的凭证),每小时兑换短期访问令牌。
- **会话登录** —— 服务端会话(cookie 存随机令牌,数据库映射到用户;弃用无状态签名方案,换取即时吊销能力)。每条查询以用户 id 为界;数据隔离在任何外部用户加入前已用双账号端到端实测。
- **增量同步** —— 每用户一个游标(已处理最新邮件的时间戳),每小时只拉新增。游标**仅在整批成功后推进**:失败轮次零代价,自动重试。
- **幂等写入** —— 三级去重键(真实单号 > 发件域+类型+日期+标题指纹 > 商品词)配合同邮件守卫吸收重放,重复处理永不产生重复事件——"回拨游标重放"因此成为安全的恢复手段。
- **事件生命周期** —— 改期就地移动;取消邮件将事件软删除(数据行保留、标记 `cancelled`,可撤销、可审计)。关键词护栏在模型忘记打标时强制走取消路径:**规则为模型兜底,本项目反复出现的主题。**
- **每个裁决都有账** —— 邮件 id、哪道门裁的、结论、token 成本、生成的事件 id。这张表让"为什么 X 在/不在我的日历上"一条查询即有答案,兼任实时成本监控——同时,它也在悄悄长成一份训练集。

部署于 Railway(HTTPS、持久卷、main 分支自动部署)。

## 数据与评估方法

本页每一个数字,都能追溯到同一份语料和同一套纪律。

- **31,175 封真实个人邮件**,经 Gmail OAuth 拉取。全程零合成数据——编造的邮件验证不了任何关于真实分布的事。
- **对抗 5% 先验的分层抽样。**纯随机抽 500 封只含约 25 个正样本,置信区间宽到无法比较方案。按六个类型桶抽样把正样本率提到 30%:

| 桶 | 判定关键词(主题 + 正文前 2000 字) | dev | test |
|---|---|---|---|
| billing | bill / invoice / payment / subscription / renew / 账单 / 续期 | 130 | 39 |
| promotion | sale / deal / off / discount / promo / 促销 / 优惠 | 120 | 36 |
| delivery | ship / deliver / order / package / track / 发货 / 物流 | 70 | 21 |
| deadline | deadline / due / expire / reminder / submit / 截止 / 到期 | 60 | 18 |
| appointment | appointment / reservation / booking / schedule / 预约 / 预订 | 60 | 18 |
| random | 无条件随机 | 60 | 18 |

  五个类型桶设有前置条件:邮件须先含日期表达,否则即便命中关键词亦跳过——避免桶被"含 billing 词却毫无时间信息"的邮件填满,该类几乎必然为负样本。**random 桶不设此条件,它是真实先验的探针**:60 封中仅 3 封含承诺,上文 5% 即由此得出,也是"过滤层有价值"这一判断的实证依据。

- **封存的测试集。**所有调优只在 500 封开发集上;150 封测试集直到设计冻结才运行,且仅一次。原测试集在开发期间被反复查看、不再具备"从未见过"的公正性,遂降级并入开发集,并从未触碰的 30,675 封中以同一分桶函数、固定随机种子重抽 150 封;**新集在架构冻结前即完成标注并封存**,排除"按结果选考卷"的可能。
- **运行纪律。**每次改动前清缓存;失败的 API 调用绝不写入缓存(一次静默故障曾伪装成"无承诺"污染整轮评估);token 用量从 API 官方字段读取而非字符估算(后者对中文与 HTML 低估约 66%);关键配置跑三次——混合架构的误报数在完全相同的运行间于 11–16 波动;一次只改一个变量。
- **单开关消融**——纯 LLM 基线与完整流水线共用同一代码路径、同一提示词,所有对照在完全相同的条件下进行。

### 若干发现

- **规则在提示词中的位置是承重结构。**排除规则埋在中段时精确率 0.503(71 个误报中 40+ 为收据);提到最前作为硬性前置检查后 0.818,召回率无损。同模型、同规则,只改位置。
- **截断不是免费的。**硬截断到 3,000 字符反而**降低**精确率——页脚和退订链接是判"无"的证据。激进切片还击穿了一条"一周内"的截止(任何日期正则都看不见它),补入时长表达模式后恢复。
- **只在当前数据分布下正确的规则,不是规则,是巧合。**正则基线曾对中英文收据非对称处理,数据恰好从未惩罚它(F1 从 0.747 到 0.749),但仍按原则修正。

## 标注规范自己也有 bug

标注测试集时撞上一处矛盾:Apple 收据常含 *"2024 年 5 月 15 日续期"*——明确的未来扣款,按定义每条判据都是承诺;但 v1 规范写着*收据一律判无*。

审计量出规模:**开发集 66 封收据中 47 封(71%)含未来续期日,全部被标为无**——且标注零漂移,每个标签都忠实执行了规范。错的是规范本身:形式特征("这是收据")压过了内容特征("里面有未来扣款日")。

修复:规范重写,47 封重标,**全部实验对照 v2 重跑**。代价:半天。结果:本页没有任何数字建立在自相矛盾的定义上。

## 生产第一周

流水线在测试集上拿了 0.989。然后真实用户来了,第一周暴露出五个任何基准测试都测不出的问题。每一个都靠 `extraction_log`(逐邮件审计表)定位,通常只需几分钟。

**1. 被静默吞掉的邮件。**一位用户报告水电账单缺失。日志排除了误判:那封邮件根本没被处理过。根因:Gmail 列表接口按最新在前、一次一页返回——代码只读一页,却把同步游标推过了*全部*邮件,更老的邮件被永久锁在门外。此前从未发作,因为每小时增量一页装得下;新用户 7 天的积压装不下。修复:翻页 + 单轮上限。恢复:回拨游标重放——因写入幂等而安全。零数据丢失。

**2. 从未跑过的定时器。**"每小时自动同步"其实一次都没触发过:APScheduler 的 `next_run_time=None` 不是"不要立即跑",而是把任务*以暂停状态*加入。此前每一次"自动"同步都是我手动执行的。改一个参数;部署 90 秒后,系统迎来第一次真正自主的心跳,六名用户全部处理。此后的日志确认:每小时一轮,再未缺席。

**3. 坏钥匙自愈。**一位用户的 Google 授权缺少 Gmail 权限(每次刷新都报 `invalid_scope`)。在旧行为下,这意味着"已连接"假象背后每小时静默失败。系统现在能识别授权级错误、标记账户过期、调度时跳过、并在前端亮出"重新连接"按钮——她自己重新授权,当小时数据恢复,全程无人介入。

**4. 同一笔扣款,两条事件。**同一次订阅续费,平台发来确认信与发票两封,标题措辞相差一词,去重指纹因此错开,日历同日出现两条同一笔钱。修法已定向:标题指纹之外引入金额作为同一性信号。

**5. 模型会编日期。**迄今最危险的错误类型,一周内出现两种形态:一封说"*套餐将从下个周期起涨至每两月 $118*"的邮件,模型拿**发件日期 + 两个月**推算出一个具体扣款日——邮件只给了周期,从未给出这个日期;另两封"需要行动"的通知**完全没有任何日期素材**,模型仍各安了一个。承诺定义第三条本就禁止此事;下一版提示词将把它从定义升级为硬性指令。**验证方案**:修复后在含该类样本的切片上回归验证,并以审计日志中"无日期素材却产出事件"的比例作为持续监控指标——有修法而无验法,等同未修。

抓出这些 bug 的同一张日志表,还顺手修正了成本模型:我的邮箱 8% 是承诺、门①免费拦掉 58%;一位朋友的学校转发邮箱 42% 是承诺、门①只拦得住 3%。**门①的省钱能力取决于邮箱类型——这是任何开发集都测不出的事实。**

## 回顾:若重新设计

- **审计日志应在第一天就建立。**它后来解决了每一个生产问题:定位漏抓、区分"误判"与"未处理"、修正成本模型。它在项目中段才加入,此前的故障排查因此昂贵得多。
- **"部署后必须观察到心跳"应是验收习惯。**调度器瘫痪数日而无人察觉,根源是一个参数的语义陷阱;但真正的教训更宽:**凡声称"自动"的功能,都必须有可观测的证据证明它确实自动运行过**,否则"自动"只是一个信念。
- **发送方的纯文本版本不可信任。**正文提取最初以 text/plain 优先,直至发现某电力账单的纯文本版丢失了金额小数点($103.24 写作 $10324),而其 HTML 版正确;另有机构邮件无纯文本版,旧实现直接吞下 70,614 字符的原始 HTML。现改为 HTML 优先并经结构化转换,纯文本降为备选。

## 已知限制

- **仅支持 Gmail。**门①依赖 Gmail 自带的促销标签(典型个人邮箱中占其过滤量 58%);Outlook/IMAP 需要替代信号,机构邮箱经转发接入。中国大陆实际不可用(Gmail、Google 授权与托管域名均被阻断)。
- **外部日历订阅与导出尚未实现。**前端保留了添加外部 .ics 订阅源的入口,后端接口未实现;反向的日历导出(webcal / .ics,使抽取结果可被系统日历订阅)同样在计划中而未落地。当前 Kairos 是一个独立视图,不与系统日历互通。
- **取消操作的信任边界。**取消当前基于与发件域无关的信号匹配(退化为类型+日期),因此一封构造的邮件可能软删用户已有的事件——前提是攻击者知道它存在。计划修复:要求取消邮件的发件域与原事件来源一致,跨域取消降级为提示而非自动删除。内测熟人环境下低风险;任何公开发布前的硬性前提。
- **基准精度 ≠ 生产精度。**实验集正样本率 30%,真实约 5%;生产精度预计明显低于 0.979——审计日志的存在正是为了度量它。
- **首次同步窗口。**新用户首拉回溯 7 天,更早的承诺不会出现。"回溯更早"选项在计划中。
- **中文优先的标题,是决策而非疏漏。**标注与评估以中文进行,故标题中文优先。语言自适应被刻意推迟:标题参与去重指纹,更换输出语言会使既有合并键失效——它将随下一版提示词一起交付,并附带全量重评估。
- **取消匹配可能模糊。**精确指纹未命中时退化为同类型同日匹配——若当天有两条同类型事件则存在歧义。
- **日界附近的相对日期。**事件日期以邮件的 UTC 到达时间为锚;当正文使用"明天/今晚"这类相对表达、且邮件恰在用户时区的日界附近到达时,推算日期可能偏差一天。绝对日期——绝大多数情形——不受影响。

## 项目结构

```
kairos/
├── scripts/     ML 管线与评估:抽样、标注工具、四道门抽取器、消融、去重测试
├── server/      FastAPI 后端:OAuth、会话、每小时调度、落库与去重、SQLite 层
└── web/         PWA 前端:原生 JS,无构建步骤
```

私有数据——邮件语料、标注、凭证、数据库——按设计不在仓库中。

| 层 | 技术 |
|---|---|
| ML 管线 | Anthropic API(Claude Haiku 4.5 抽取 · Sonnet 5 兜底)· 手写正则规则层 · 提示词工程(assistant prefill、正文切片) |
| 数据与评估 | Python · 分层抽样与标注工具 · 单开关消融框架 · 真实 token 计价 |
| 后端 | FastAPI · SQLite(WAL)· APScheduler · Google OAuth 2.0(授权码流)· 服务端会话鉴权 · html2text |
| 前端 | 原生 JS PWA(无框架、无构建步骤)· 自定义弹簧动画 · 版本号缓存击破 · 中英 i18n |
| 基础设施 | Railway(容器部署 · 持久卷 · HTTPS · main 分支自动部署)· Gmail API |

## 路线图

- **提示词 v3** —— 将"禁止编造日期"升级为硬性指令;语言自适应标题;全量重评估。
- **日历导出** —— .ics / webcal 订阅源,使抽取结果流入用户既有日历(优先级高于自有界面打磨)。
- **去重 v2** —— 金额作为同一性信号;取消匹配加入发件域校验。
- **日历准入层** —— 有些抽取正确却不配占一格日历(健身房停电通知);独立一层,配独立标注。
- **多邮箱聚合** —— 一人多邮箱,一份日历。
- **蒸馏门②** —— 审计日志持续积累(邮件特征 → 裁决)数据对;攒够即是训练集,可训练小型本地分类器替代 Haiku 调用。整条流水线以 API 先行验证任务——**而它产生的数据,正是它最终不再花钱的方式。**

---

*Built by Tiansheng Chen · [github.com/tiansheng-chen](https://github.com/tiansheng-chen)*