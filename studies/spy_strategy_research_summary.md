# SPY Strategy Research — Consolidated Findings

Research completed through **2026-07-30**  
Tradable asset: **SPY only**  
Primary recurring-contribution benchmark: **$25 invested in SPY every week**  
Longest ETF validation period: **1994-01-03 through 2026-07-30**, with indicator history from SPY's 1993 inception

## Executive conclusion

The research has **not identified a validated strategy that reliably beats weekly SPY buy-and-hold after realistic costs and without look-ahead bias**.

Some exploratory strategies produced higher ending values in the historical sample. Those apparent winners were driven primarily by one or more of the following:

- Additional market exposure from leverage.
- Favorable assumptions about financing and execution.
- Correctly avoiding part of the 2008 or 2020 crashes.
- Selection from hundreds of configurations using the same SPY history.
- Raw account-value drawdowns that were understated by continuing contributions.

When the strongest candidates were frozen and subjected to earlier-period testing, chronological folds, crisis attribution, parameter-neighborhood checks, realistic financing, matched-exposure controls, bootstrap analysis and multiple-testing penalties, they did not establish a durable edge.

**Current default decision: continue using weekly SPY buy-and-hold as the benchmark and default implementation.** Trend and volatility rules may still be useful for an investor who deliberately accepts lower expected wealth in exchange for reduced drawdown, but that is risk management rather than demonstrated alpha.

## How to interpret the evidence

The reports were produced in stages. Later reports contain more conservative mechanics and should receive more weight than earlier exploratory rankings.

### Highest-quality evidence

1. `spy_hedge_edge_validation.md`
2. `spy_conditional_leverage_validation.md`
3. `spy_realistic_leverage_study.md`
4. Development/validation/holdout sections of the adaptive, short and directional studies

These reports use frozen rules, chronological tests, next-open execution, explicit costs or financing, and stronger benchmark comparisons.

### Exploratory evidence

The bankroll, weekly timing, market timing and combined timing reports were useful for discovering hypotheses. Their best full-sample results should not be interpreted as independently confirmed performance.

## Master study summary

| Study | Main comparison | Best historical observation | Stronger validation result | Final assessment |
|---|---|---|---|---|
| Bankroll and contribution timing | Equal annual contributions, 2005–2024 | Actionable timing differences were only a few basis points of IRR | Even hindsight purchase timing added only about 0.29 percentage point in the monthly study and 0.09 point in the weekly study | No contribution-calendar edge |
| Weekly strategy study | $25 weekly, 2005–2024 | Above-SMA contribution gates slightly improved drawdown with nearly unchanged return | Monday, Wednesday, Friday and equal-dollar monthly contributions were effectively tied | Useful only as mild risk control |
| Frozen SMA75 contribution validation | $42,500 each, 1994–2026 | SMA75 ended at $343,399 versus B&H at $342,730 | Won 2/7 segments, had lower TWR CAGR than B&H, and bootstrap interval crossed zero | Rejected as proven edge: 4/13 gates passed |
| Weekly status check | Equal $28,150 owner capital, 2005–2026 | Leveraged strategies produced larger weekly-account balances | Time-weighted analysis showed the improvement came mainly from leverage; corrected drawdowns were materially deeper than raw account drawdowns | Deposits were not profit, but early leverage conclusions were incomplete |
| Adaptive weekly sizing | $28,150 each, 2005–2026 | Trend-confirmed dip buyer ended at $139,242 versus B&H at $139,150 | It lost by $19 in the 2022–2026 holdout; no adaptive rule beat B&H there | $92 full-sample lead was noise, not a durable edge |
| Lump-sum timing | $10,000 each, 2004–2026 | 1.5x above SMA200 / 1x otherwise ended at $128,020 versus B&H at $100,713 | No unleveraged timing strategy beat B&H; leveraged winner had a −59.36% drawdown | Extra return was compensated leverage risk |
| Timing plus weekly contributions | $28,150 each, 2005–2026 | Optimistic 1.5x/1x version ended at $183,664 versus weekly B&H near $139,190 | Later realistic leverage testing reversed the result | Exploratory winner invalidated by realistic financing and execution |
| Realistic leverage retest | $28,150 each, next-open execution, 10% financing | B&H ended at $139,150 | Original 1.5x/1x fell to $135,501; original 2x/cash fell to $82,151 | No leverage edge at realistic financing |
| Short during declines | $28,150 each, 2005–2026 | Best short rule ended at $83,850 | B&H ended at $139,150; no short rule won the 2022–2026 holdout | Direct crash shorting rejected |
| Bidirectional timing and take profits | 156 configurations, $28,150 each | Best configuration ended at $106,732 | B&H ended at $139,150; 0/156 beat it and no selected family won both later periods | Long/short timing and fixed take profits rejected |
| Temporary hedge exploration | 144 short overlays and 144 matched partial-sale controls | Best short overlay ended at $144,267; best partial sale at $145,282; B&H at $139,150 | Explicit short beat matched partial sale in 0/144 pairs; no development-selected hedge won both validation and holdout | Partial sale dominated explicit short, but edge unconfirmed |
| Frozen hedge validation | $42,500 each, 1994–2026 | Partial-sale rule ended at $360,578 versus B&H at $342,730 | Lost by $778 in 1994–2004, won 4/8 folds, bootstrap interval crossed zero, and most benefit came from 2008/2020 | Rejected as proven edge: 2/10 gates passed |
| Conditional-leverage validation | $42,500 each, 1994–2026 | Hybrid reduced drawdown to −45.57% versus B&H at −55.21% | Hybrid ended at $297,613 versus B&H at $342,730; 0/9 neighbors and 0/18 stress cases beat the required controls | Rejected as proven edge: 2/14 gates passed |

## Findings by research question

### 1. Can contribution timing beat weekly buy-and-hold?

No meaningful edge was found.

- Monday, Wednesday and Friday purchases produced nearly identical IRRs.
- Equal-dollar weekly and monthly contributions were effectively tied.
- The impossible hindsight rule that purchased the cheapest day of each week improved IRR by only about 0.09 percentage point.
- Moving-average gates on new contributions changed drawdown more than return.
- Holding dry powder usually created an opportunity cost that its later deployment did not recover.

The timing of a fixed $25 contribution is too small a lever compared with SPY's long-term market return.

The dedicated frozen SMA75 validation reinforced this conclusion. It finished **$669 above B&H** in ending dollars, but won only **2/7** chronological segments, produced a slightly lower time-weighted CAGR, and had a **−0.13% to 0.08%** bootstrap interval for annualized active return. The small dollar advantage was not sufficient evidence of a durable return edge.

### 2. Can adaptive trade sizing create an edge?

Not based on the tested rules.

The trend-confirmed dip buyer produced the only full-period adaptive win, and it was just **$92** on **$28,150** of contributions. It then lost to B&H in both the 2017–2021 validation period and the 2022–2026 holdout.

Reserve, RSI, drawdown-ladder, volatility and composite sizing rules generally held cash during periods when continued buying was beneficial. Their primary effect was changing the path of drawdown, not increasing long-run wealth.

### 3. Can ordinary market timing beat SPY?

Unleveraged timing did not beat lump-sum B&H on final wealth or CAGR.

Moving-average, momentum, seasonal and volatility rules frequently reduced drawdown, sometimes substantially. They also spent less time invested and therefore captured less of SPY's equity premium and rebound days.

Examples from the lump-sum study:

- B&H: **$100,713**, 10.78% CAGR, −55.22% maximum drawdown.
- Volatility target 15%: **$92,535**, 10.36% CAGR, −33.23% drawdown.
- Monthly 10-month moving average: **$89,429**, 10.19% CAGR, −23.17% drawdown.
- Conditional Sell in May: **$49,929**, 7.38% CAGR, −17.59% drawdown.

This is a consistent risk/return tradeoff, not a free improvement.

### 4. Did leverage provide an edge?

The early answer looked like yes; the realistic answer was no.

The exploratory 1.5x/1x SMA200 strategy produced the highest ending wealth under relatively cheap financing and optimistic execution. After adding next-open execution, 10% daily financing, realistic margin rules, transaction costs, opening gaps and forced-liquidation mechanics:

- Weekly B&H: **$139,150**.
- Original 1.5x/1x strategy: **$135,501**.
- Original 2x/cash strategy: **$82,151**.

The 1.5x strategy could beat B&H around an 8% borrowing assumption, but not at 10% or 12%, and its drawdown remained approximately as deep as B&H. That is sensitivity to the cost of borrowed capital, not reliable timing alpha.

The later conditional-leverage validation was even clearer:

- Frozen hybrid: **$297,613**.
- Constant matched 1.09x exposure: **$334,597**.
- Weekly B&H: **$342,730**.
- Financing cost for the hybrid: **$40,636**.
- Hybrid chronological wins: **3/8**.
- Hybrid parameter neighbors beating B&H: **0/9**.
- Stress cases beating both B&H and matched exposure: **0/18**.

### 5. Can we short market declines and rebuy lower?

The idea is mechanically possible, but the tested signals could not identify the profitable portion of declines reliably enough.

The practical problems were:

- Trend signals entered after part of the decline had already occurred.
- Short positions were vulnerable to violent bear-market rebounds.
- Long/short flips created trading drag and whipsaw.
- Short exposure paid borrow and the economic equivalent of SPY distributions.
- Staying short or in cash missed some of the market's strongest recovery sessions.
- Fixed take profits often exited a correct position but left the portfolio uninvested until the next scheduled review.

In the direct short study, B&H ended at **$139,150** while the best short-enabled rule ended at **$83,850**. In the broader 156-configuration bidirectional study, the best result was **$106,732**, still **$32,418 behind B&H**.

### 6. Did temporary crash hedges work better?

They were more promising than switching the entire portfolio short, but they did not validate as an edge.

The best exploratory hedge kept the 1x long core and added a temporary 50% short below SMA200. It captured part of the early 2008 and 2020 declines and restored the full long position afterward.

However, the matched implementation test revealed the key economic fact:

> A 1x SPY long plus a 0.5x SPY short is approximately 0.5x net SPY exposure. Selling half the long position reaches the same net exposure without maintaining two opposing books.

The explicit short overlay beat its paired partial-sale implementation in **0 of 144 comparisons**. The partial-sale approach avoided borrow fees and some execution complexity.

The frozen partial-sale rule did finish **$17,848 above B&H** over 1994–2026, but the confirmation evidence was insufficient:

- It lost by **$778** in the earlier 1994–2004 segment.
- It won only **4/8** chronological folds.
- Its annualized active return was approximately **0.04%**.
- Its block-bootstrap 95% interval was **−0.65% to 0.84%**.
- Its Deflated Sharpe probability was approximately **0.15%** after the known multiple-testing history.
- The 2008 and 2020 windows contributed +13.35% of active log return, while every other date contributed **−11.96%**.

The result was therefore classified **rejected as a proven edge**, not accepted based on its higher full-period ending value.

### 7. Did take-profit exits improve long/short timing?

No.

Across 13 signal families, three review schedules and four take-profit choices, **0 of 156 configurations beat B&H**. The development-selected versions also failed to beat B&H in both validation and holdout.

Fixed take profits frequently reduced the size of an individual loss or locked in part of a decline, but they also:

- Truncated sustained favorable trends.
- Increased turnover.
- Created time in cash after an exit.
- Required a second timing decision for re-entry.

## What the studies did establish

Although no return edge was validated, the research produced several reliable practical conclusions.

### Weekly B&H is a difficult benchmark

SPY's long-run equity premium, dividends and rapid recoveries make continuous exposure difficult to beat using SPY-derived price signals alone.

### Drawdown can be reduced, but usually by accepting less return

Moving-average and volatility rules can materially reduce historical drawdowns. That may be worthwhile for an investor who is more likely to remain invested with a smoother portfolio, but it should be described as a risk preference rather than a return edge.

### Same-asset short overlays are inefficient de-risking tools

When the portfolio is already long SPY, selling part of that position is generally simpler and historically superior to adding a SPY short that produces the same net exposure.

### Financing must be modeled explicitly

Leverage conclusions changed when the assumed borrowing rate rose from the earlier 5.5% case to the 8%–12% range. A strategy that works only under favorable financing is not robust.

### Full-sample winners are not sufficient

The repeated pattern was:

1. A strategy looked attractive across the complete history.
2. The result weakened when selected only on development data.
3. It failed validation, holdout or earlier-period evidence.
4. Crisis attribution showed dependence on a small number of episodes.

## Measurement lessons

### Equal contributions are mandatory

Every recurring-contribution comparison must give each strategy the same owner capital on the same dates. Higher contributions cannot be treated as strategy profit.

### Final value, IRR and time-weighted return answer different questions

- **Final value** measures the ending account after the specified contribution schedule.
- **IRR** measures the investor's money-weighted experience and depends on contribution timing.
- **Time-weighted return** removes external cash-flow effects and better isolates strategy performance.

A strategy should not be declared superior based on only one of these measurements.

### Drawdown must remove external cash flows

The early raw account-value drawdowns were understated because weekly deposits lifted account value during declines. Later studies use unitized NAV or cash-flow-adjusted drawdown.

For example, weekly B&H's apparent drawdown near −38% became approximately **−55%** after removing the effect of deposits.

## Improvements made to the backtesting suite

The research added or verified support for:

- Equal recurring contribution schedules.
- Money-weighted IRR and time-weighted CAGR.
- Unitized NAV and cash-flow-adjusted drawdown.
- Previous-close signals with next-open execution.
- Opening-gap and adjusted intraday-high/low handling.
- Transaction costs, cash interest and daily margin financing.
- Short borrow charges and signed exposure.
- Initial and maintenance margin requirements.
- Forced liquidation and post-liquidation lockouts.
- Synthetic daily-reset leveraged ETFs with volatility decay and expenses.
- Matched short-overlay versus partial-sale controls.
- Development, validation and holdout periods.
- Anchored chronological testing.
- Parameter-neighborhood testing.
- Crisis attribution.
- Moving-block bootstrap confidence intervals.
- Deflated Sharpe and probability-of-backtest-overfitting checks.
- Auditable signal dates, trade dates and transaction logs.

The latest verification run completed with **191 tests passing**.

## Remaining limitations

1. **The SPY history is now heavily consumed.** Reusing 1993–2026 for additional parameter tuning will create increasingly optimistic results.
2. **Adjusted OHLC data are imperfect for execution.** Adjustments are useful for total return but can distort historical open, high, low and fixed-price target levels.
3. **Taxes remain excluded.** Selling appreciated shares, short-sale treatment and margin-interest deductibility can materially change after-tax rankings.
4. **Historical financing is approximated.** Fixed sensitivity rates do not reproduce every broker's changing margin rate, house requirement or forced-liquidation policy.
5. **Short availability is incomplete.** Locate availability, recalls and payments in lieu of dividends are not reconstructed trade by trade.
6. **Daily data hide intraday paths.** A daily high or low does not reveal the exact order in which margin, stop and target levels were reached.
7. **One ETF provides few independent regimes.** Hundreds of daily observations do not equal hundreds of independent bear markets.
8. **Multiple testing remains material.** The latest validation counted at least **557 known prior result rows**, many selected from the same underlying history.
9. **Forward evidence does not yet exist.** A strategy cannot receive genuinely new confirmation from another rearrangement of the same inspected SPY data.

## Current strategy classification

| Strategy family | Classification | Appropriate interpretation |
|---|---|---|
| Weekly SPY B&H | Benchmark/default | Best-supported wealth-compounding approach in these studies |
| Weekly contribution timing | Rejected as return edge | Calendar choice has negligible effect |
| Adaptive weekly sizing | Rejected as return edge | Full-sample lead did not survive holdout |
| Moving-average timing | Risk-management candidate | Lower drawdown with lower historical wealth |
| Volatility targeting/de-risking | Risk-management candidate | Smoother path, generally lower final value |
| Direct long/short switching | Rejected | Large underperformance and whipsaw |
| Fixed take-profit timing | Rejected | 0/156 configurations beat B&H |
| Explicit SPY short overlay | Dominated implementation | Partial sale produced better matched results |
| Frozen partial-sale hedge | Interesting but unconfirmed | Higher full-period wealth, failed validation gates |
| Constant or conditional leverage | Rejected under realistic base assumptions | Financing overwhelmed the tested timing benefit |

## Practical decision framework

### If the objective is maximum long-term wealth

Use weekly SPY buy-and-hold as the default based on the evidence collected so far.

### If the objective is a materially smaller drawdown

Consider a simple, low-turnover moving-average or volatility de-risking rule only after explicitly accepting that historical ending wealth was lower. Select the exposure reduction based on tolerable drawdown, not by searching for the highest backtested return.

### If the objective is profiting from crashes

Do not use the tested direct-short or long/short rules. The temporary partial-sale rule is operationally preferable to a same-SPY short overlay, but it remains unvalidated and should not replace B&H based on the current evidence.

### If the objective is using leverage

Do not assume that a positive gross leveraged return is an edge. Require the strategy to beat both B&H and a constant-exposure control after the actual broker's financing rate. None of the latest conditional-leverage variants did so.

## Recommended next step

The next meaningful step is **not another search across the same 1993–2026 SPY data**.

1. Freeze any candidate rule before further observation.
2. Record its month-end or weekly signal, intended next-open trade and actual executable price in a forward paper log.
3. Keep weekly B&H and a matched-exposure control beside it.
4. Do not change parameters after a losing period.
5. Accumulate independent signal episodes rather than declaring success after a quiet calendar year.
6. If historical work continues, improve data realism with raw OHLC, separate dividends, historical T-bill yields and broker-specific financing—but label it model improvement, not new independent evidence.

Given the number of hypotheses already tested, future claims of an edge should require genuinely new data and predeclared pass/fail criteria.

## Source reports

- [Bankroll-management variations](spy_bankroll_study_v2.md)
- [Weekly strategy study](spy_weekly_study_clean.md)
- [Weekly strategy status check](spy_weekly_status_check.md)
- [Frozen SMA75 contribution-gate validation](spy_sma75_contribution_validation.md)
- [Adaptive weekly sizing study](spy_adaptive_weekly_study.md)
- [Market-timing study](spy_timing_study.md)
- [Timing plus weekly contributions](spy_timing_weekly_combined_study.md)
- [Realistic leverage retest](spy_realistic_leverage_study.md)
- [Short-during-declines study](spy_short_decline_study.md)
- [Bidirectional timing and take-profit study](spy_directional_take_profit_study.md)
- [Temporary hedge exploration](spy_temporary_hedge_study.md)
- [Frozen hedge validation](spy_hedge_edge_validation.md)
- [Conditional-leverage validation](spy_conditional_leverage_validation.md)

## Final takeaway

The studies did not uncover a hidden weekly timing trick, a reliable crash-short signal or a financing-resistant leverage rule. They did uncover something valuable: **most apparent SPY timing edges disappear when capital, execution, financing, drawdown measurement and out-of-sample validation are handled consistently**.

That leaves a clear evidence-based position:

> Weekly SPY buy-and-hold remains the default. Use timing only when consciously trading expected return for risk reduction, and require genuinely new forward evidence before calling any alternative an edge.
