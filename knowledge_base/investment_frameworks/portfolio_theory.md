# Modern Portfolio Theory and Advanced Portfolio Construction

## Overview

Modern Portfolio Theory (MPT), introduced by Harry Markowitz in his landmark 1952 paper "Portfolio Selection," fundamentally transformed investment management by demonstrating that risk and return must be considered together at the portfolio level, not asset by asset. MPT established that diversification — combining assets whose returns do not move in perfect lockstep — can reduce risk without proportionately reducing expected return. This insight underpins virtually all professional portfolio construction today.

---

## Markowitz and the Efficient Frontier

The **Efficient Frontier** is the set of optimal portfolios that offer the highest expected return for a given level of risk (standard deviation of returns), or equivalently, the lowest risk for a given expected return.

**Mathematical Framework:**
```
Expected Portfolio Return: E(Rp) = Σ wi × E(Ri)
Portfolio Variance: σp² = Σi Σj wi × wj × σi × σj × ρij
```
Where:
- `wi` = weight of asset i in portfolio
- `E(Ri)` = expected return of asset i
- `σi`, `σj` = standard deviations of assets i and j
- `ρij` = correlation coefficient between assets i and j

**Key Insights:**
- Portfolios on the Efficient Frontier dominate all others — no other portfolio at the same risk level offers a higher return
- The "minimum variance portfolio" is the leftmost point on the frontier — the lowest possible risk achievable
- Adding a new asset shifts the frontier leftward (lower risk) only if the asset has imperfect correlation with existing holdings
- The Capital Market Line (CML) extends from the risk-free rate tangent to the Efficient Frontier; the tangent point is the **Market Portfolio** (in theory, the value-weighted portfolio of all risky assets)

**Practical Limitations:**
- MPT requires estimates of expected returns, variances, and correlations — all of which are unstable and difficult to estimate precisely
- Covariances spike during market crises (correlations converge to 1 in sell-offs), precisely when diversification is needed most — the "diversification disappears in a crash" problem
- Normal distribution assumption understates fat-tail risk (Black Swan events)

---

## Sharpe Ratio: Risk-Adjusted Return

The **Sharpe Ratio**, developed by William Sharpe (1966), measures the excess return earned per unit of total risk (volatility):

```
Sharpe Ratio = (Rp − Rf) / σp
```
Where:
- `Rp` = Portfolio return (annualized)
- `Rf` = Risk-free rate (typically 3-month Treasury bill yield)
- `σp` = Annualized standard deviation of portfolio returns

**Interpretation:**
- **Sharpe > 1.0**: Good; earning more than 1 unit of return per unit of risk
- **Sharpe > 2.0**: Excellent; institutional quality
- **Sharpe > 3.0**: Exceptional; hedge fund elite tier (often unsustainable long-term)
- **Sharpe < 0**: Portfolio underperforms the risk-free rate on a risk-adjusted basis

**Related Ratios:**

| Ratio | Formula | Key Difference from Sharpe |
|-------|---------|---------------------------|
| **Sortino Ratio** | (Rp − Rf) / Downside Deviation | Only penalizes downside volatility |
| **Calmar Ratio** | Annualized Return / Max Drawdown | Uses worst drawdown instead of std dev |
| **Treynor Ratio** | (Rp − Rf) / Beta | Uses systematic risk instead of total risk |
| **Information Ratio** | (Rp − Rb) / Tracking Error | Measures active return per unit of active risk |

**Sortino is preferred** for strategies with positive skew (asymmetric return profiles) because upside volatility should not be penalized the same as downside volatility.

---

## Beta and Alpha: Decomposing Returns

**Beta (β)** measures a portfolio's sensitivity to market movements:
```
β = Cov(Rp, Rm) / Var(Rm)
```
- `β = 1.0`: Portfolio moves in lockstep with the market
- `β > 1.0`: Amplified market exposure (e.g., β = 1.3 → 30% more volatile than market)
- `β < 1.0`: Less sensitive to market swings (defensive)
- `β < 0`: Inverse relationship to market (rare; characteristic of true hedges like gold in some regimes)

**Alpha (α)** represents the return above what is explained by market exposure:
```
α = Rp − [Rf + β × (Rm − Rf)]
```
- Positive alpha indicates genuine skill (value added beyond systematic market exposure)
- The CAPM framework predicts alpha should be zero in aggregate (markets are efficient); persistent positive alpha is very rare

**Jensen's Alpha**: Uses regression of portfolio returns against market returns over time, yielding the intercept as alpha. Statistically significant positive alpha (p < 0.05 over 3+ years) is evidence of skill vs. luck.

**Fama-French Multi-Factor Alpha**: Modern factor models include:
- **SMB** (Small Minus Big): Size factor
- **HML** (High Minus Low Book): Value factor
- **MOM** (Momentum): Winner/loser momentum
- **QMJ** (Quality Minus Junk): Quality factor
- **BAB** (Betting Against Beta): Low-beta premium

---

## Correlation and Diversification

**Correlation coefficient (ρ)** ranges from -1 to +1:
- **ρ = +1**: Perfect positive correlation — no diversification benefit
- **ρ = 0**: Uncorrelated — diversification reduces portfolio variance by √2 for equal-weighted 2-asset portfolio
- **ρ = -1**: Perfect negative correlation — theoretical zero variance portfolio possible

**Diversification Impact on Portfolio Variance:**
As uncorrelated assets are added to a portfolio, idiosyncratic (company-specific) risk diversifies away. The remaining risk is **systematic risk** (market risk, factor risk), which cannot be eliminated by diversification alone.

**Typical Asset Class Correlations (approximate long-run averages):**
- US Equities / International Equities: ρ ≈ 0.75–0.85
- US Equities / US Bonds: ρ ≈ −0.10 to −0.30 (negative in most regimes)
- US Equities / REITs: ρ ≈ 0.65
- US Equities / Commodities: ρ ≈ 0.10–0.20
- US Equities / Gold: ρ ≈ 0.00 to −0.10
- Bitcoin / US Equities: ρ ≈ 0.40–0.60 (elevated; crisis correlation rises further)

**Correlation Instability**: During financial crises (2008, March 2020), correlations across risk assets spike toward 1.0 as forced selling and risk-off behavior dominates. Only US Treasuries and gold typically maintain or increase their negative correlation during these episodes.

---

## Kelly Criterion: Optimal Position Sizing

The **Kelly Criterion**, derived from information theory by John Kelly (1956), calculates the theoretically optimal fraction of capital to bet on each opportunity to maximize long-run geometric growth:

```
Kelly Fraction (f*) = (b × p − q) / b
```
Where:
- `p` = probability of winning
- `q` = probability of losing (1 − p)
- `b` = net odds received (profit per $1 risked)

**Example**: If a trade has a 60% win probability and pays 1.5:1 (winning $1.50 per $1 risked):
```
f* = (1.5 × 0.6 − 0.4) / 1.5 = (0.9 − 0.4) / 1.5 = 0.333 = 33.3%
```

**Practical Modification — Half-Kelly:**
Full Kelly produces extreme drawdowns (up to 50% in theory) that are psychologically untenable for most investors. **Half-Kelly (f*/2)** is the most common practical adjustment:
- Reduces theoretical drawdown substantially
- Achieves approximately 75% of the theoretical growth rate
- Provides margin of safety for estimation errors in p and b

**Limitations**: Kelly requires accurate probability and payoff estimates — in financial markets, these are genuinely uncertain. The model also assumes independent bets; correlated positions effectively increase the Kelly fraction beyond safe levels.

---

## Rebalancing Strategies

**Rebalancing** restores a portfolio to its target asset allocation after market movements cause drift.

**Rebalancing Methods:**

| Method | Trigger | Pros | Cons |
|--------|---------|------|------|
| **Calendar** | Fixed dates (monthly, quarterly, annually) | Simple, predictable | Ignores market dynamics |
| **Threshold/Band** | Asset drifts ±5% from target | Responds to market; avoids over-trading | Requires monitoring |
| **Combined** | Calendar + threshold trigger | Best of both | Slightly more complex |
| **Constant Proportion** | Dynamic; more equities in bull, more bonds in bear | Trend-following element | May underperform in volatile markets |

**Rebalancing Return Premium**: Research shows rebalancing adds a small but statistically significant return premium ("rebalancing bonus") of approximately 0.3%–0.5% per year over 10+ year periods, driven by systematically buying low and selling high.

**Tax Considerations**: In taxable accounts, rebalancing triggers capital gains taxes. Strategies to minimize tax drag:
- Use new contributions to purchase underweight assets
- Rebalance within tax-advantaged accounts (IRA, 401k)
- Use tax-loss harvesting in losing positions to offset rebalancing gains

---

## Risk Parity

**Risk Parity** (pioneered by Ray Dalio at Bridgewater with the All Weather fund) allocates portfolio risk equally across asset classes rather than allocating capital equally.

**Core Concept**: Traditional 60/40 (equity/bond) portfolios have 85%+ of their risk concentrated in equities because equities are 3–5x more volatile than bonds. Risk Parity corrects this by:

1. Estimating the volatility of each asset class
2. Calculating position sizes inversely proportional to volatility (lower volatility = larger position)
3. Applying leverage to bonds/commodities to achieve target risk contribution

**All Weather Portfolio (Dalio) Asset Allocation:**
- 30% US Equities
- 40% Long-Term Bonds (high volatility compensated by larger allocation; actual risk contribution ~25%)
- 15% Intermediate-Term Bonds
- 7.5% Gold
- 7.5% Commodities

**Risk Parity Performance:**
- Historically strong risk-adjusted returns (high Sharpe ratio) due to diversification across economic regimes
- **Weakness**: Underperforms in environments where bonds and equities fall simultaneously (e.g., 2022 inflation shock where 60/40 fell -17% and risk parity strategies also suffered)

**Economic Regime Framework** (Bridgewater's Four Quadrants):
- **Growth Rising + Inflation Falling**: Equities and bonds both perform well
- **Growth Rising + Inflation Rising**: Equities and commodities perform well; bonds suffer
- **Growth Falling + Inflation Falling**: Bonds and gold perform well; equities suffer
- **Growth Falling + Inflation Rising**: Commodities and TIPS; equities and bonds both suffer (stagflation)

Holding assets that perform well in each quadrant creates a truly all-weather portfolio.

---

## Summary

Modern portfolio theory provides the mathematical foundation for professional portfolio construction. In practice, it is extended by multi-factor models, dynamic correlation analysis, risk parity, and behavioral considerations. The central insight remains valid: diversification across uncorrelated assets is the only "free lunch" in investing. The Sharpe ratio, Kelly criterion, and rebalancing discipline translate theory into actionable portfolio management. For maximum long-run wealth creation, focus on maximizing risk-adjusted return (Sharpe/Sortino), maintaining target risk allocations through disciplined rebalancing, and ensuring position sizes respect the Kelly criterion to avoid ruin.
