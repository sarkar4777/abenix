"""Advanced financial calculations: NPV, IRR, LCOE, DCF, amortization, escalation modeling."""

from __future__ import annotations

import json
import math
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class FinancialCalculatorTool(BaseTool):
    name = "financial_calculator"
    description = (
        "Perform advanced financial calculations including NPV (net present value), "
        "IRR (internal rate of return), LCOE (levelized cost of energy), DCF (discounted "
        "cash flow), loan amortization, price escalation modeling, bond pricing, "
        "WACC, depreciation schedules, and breakeven analysis. Returns detailed "
        "calculation breakdowns."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "calculation": {
                "type": "string",
                "enum": [
                    "npv", "irr", "lcoe", "dcf", "amortization", "escalation",
                    "bond_price", "wacc", "depreciation", "breakeven",
                    "payback_period", "roi", "cagr",
                ],
                "description": "Type of financial calculation to perform",
            },
            "params": {
                "type": "object",
                "description": "Calculation-specific parameters (see description for each calculation type)",
            },
        },
        "required": ["calculation", "params"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        calc_type = arguments.get("calculation", "")
        params = arguments.get("params", {})

        if not calc_type:
            return ToolResult(content="Error: calculation type is required", is_error=True)

        calculators = {
            "npv": self._npv,
            "irr": self._irr,
            "lcoe": self._lcoe,
            "dcf": self._dcf,
            "amortization": self._amortization,
            "escalation": self._escalation,
            "bond_price": self._bond_price,
            "wacc": self._wacc,
            "depreciation": self._depreciation,
            "breakeven": self._breakeven,
            "payback_period": self._payback_period,
            "roi": self._roi,
            "cagr": self._cagr,
        }

        fn = calculators.get(calc_type)
        if not fn:
            return ToolResult(
                content=f"Unknown calculation: {calc_type}. Available: {list(calculators.keys())}",
                is_error=True,
            )

        try:
            result = fn(params)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(content=output, metadata={"calculation": calc_type})
        except Exception as e:
            return ToolResult(content=f"Calculation error: {e}", is_error=True)

    def _npv(self, params: dict[str, Any]) -> dict[str, Any]:
        rate = params.get("discount_rate", 0.1)
        cash_flows = params.get("cash_flows", [])
        initial_investment = params.get("initial_investment", 0)

        if not cash_flows:
            return {"error": "cash_flows array is required"}

        flows = [-abs(initial_investment)] + cash_flows if initial_investment else cash_flows
        pv_flows = []
        for t, cf in enumerate(flows):
            pv = cf / ((1 + rate) ** t)
            pv_flows.append({
                "year": t,
                "cash_flow": round(cf, 2),
                "discount_factor": round(1 / ((1 + rate) ** t), 6),
                "present_value": round(pv, 2),
            })

        npv = sum(pf["present_value"] for pf in pv_flows)
        return {
            "npv": round(npv, 2),
            "discount_rate": rate,
            "total_cash_flows": round(sum(cf for cf in flows), 2),
            "yearly_breakdown": pv_flows,
        }

    def _irr(self, params: dict[str, Any]) -> dict[str, Any]:
        cash_flows = params.get("cash_flows", [])
        initial_investment = params.get("initial_investment", 0)

        if not cash_flows:
            return {"error": "cash_flows array is required"}

        flows = [-abs(initial_investment)] + cash_flows if initial_investment else cash_flows

        low, high = -0.5, 5.0
        for _ in range(200):
            mid = (low + high) / 2
            npv = sum(cf / ((1 + mid) ** t) for t, cf in enumerate(flows))
            if abs(npv) < 0.01:
                break
            if npv > 0:
                low = mid
            else:
                high = mid

        irr = mid
        npv_at_irr = sum(cf / ((1 + irr) ** t) for t, cf in enumerate(flows))

        sensitivity = []
        for r in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]:
            npv_s = sum(cf / ((1 + r) ** t) for t, cf in enumerate(flows))
            sensitivity.append({"rate": r, "npv": round(npv_s, 2)})

        return {
            "irr": round(irr * 100, 2),
            "irr_decimal": round(irr, 6),
            "verification_npv": round(npv_at_irr, 2),
            "cash_flows": flows,
            "sensitivity": sensitivity,
        }

    def _lcoe(self, params: dict[str, Any]) -> dict[str, Any]:
        capex = params.get("capex", 0)
        annual_opex = params.get("annual_opex", 0)
        annual_generation_mwh = params.get("annual_generation_mwh", 0)
        lifetime_years = params.get("lifetime_years", 25)
        discount_rate = params.get("discount_rate", 0.08)
        degradation_rate = params.get("degradation_rate", 0.005)
        opex_escalation = params.get("opex_escalation", 0.02)

        if annual_generation_mwh <= 0:
            return {"error": "annual_generation_mwh must be positive"}

        total_cost_pv = capex
        total_energy_pv = 0.0
        yearly = []

        for year in range(1, lifetime_years + 1):
            generation = annual_generation_mwh * ((1 - degradation_rate) ** (year - 1))
            opex = annual_opex * ((1 + opex_escalation) ** (year - 1))
            df = 1 / ((1 + discount_rate) ** year)
            cost_pv = opex * df
            energy_pv = generation * df

            total_cost_pv += cost_pv
            total_energy_pv += energy_pv

            if year <= 5 or year == lifetime_years or year % 5 == 0:
                yearly.append({
                    "year": year,
                    "generation_mwh": round(generation, 1),
                    "opex": round(opex, 2),
                    "cost_pv": round(cost_pv, 2),
                    "energy_pv": round(energy_pv, 2),
                })

        lcoe = total_cost_pv / total_energy_pv if total_energy_pv > 0 else 0
        total_generation = sum(
            annual_generation_mwh * ((1 - degradation_rate) ** (y - 1))
            for y in range(1, lifetime_years + 1)
        )

        return {
            "lcoe_per_mwh": round(lcoe, 2),
            "lcoe_per_kwh": round(lcoe / 1000, 4),
            "total_cost_pv": round(total_cost_pv, 2),
            "total_energy_pv_mwh": round(total_energy_pv, 1),
            "total_generation_mwh": round(total_generation, 1),
            "capex": capex,
            "lifetime_years": lifetime_years,
            "discount_rate": discount_rate,
            "sample_years": yearly,
        }

    def _dcf(self, params: dict[str, Any]) -> dict[str, Any]:
        free_cash_flows = params.get("free_cash_flows", [])
        discount_rate = params.get("discount_rate", 0.1)
        terminal_growth = params.get("terminal_growth_rate", 0.02)
        shares_outstanding = params.get("shares_outstanding", 1)
        net_debt = params.get("net_debt", 0)

        if not free_cash_flows:
            return {"error": "free_cash_flows array is required"}

        pv_fcfs = []
        for t, fcf in enumerate(free_cash_flows, 1):
            pv = fcf / ((1 + discount_rate) ** t)
            pv_fcfs.append({"year": t, "fcf": round(fcf, 2), "pv": round(pv, 2)})

        last_fcf = free_cash_flows[-1]
        terminal_value = (last_fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
        pv_terminal = terminal_value / ((1 + discount_rate) ** len(free_cash_flows))

        enterprise_value = sum(pf["pv"] for pf in pv_fcfs) + pv_terminal
        equity_value = enterprise_value - net_debt
        per_share = equity_value / shares_outstanding if shares_outstanding else 0

        return {
            "enterprise_value": round(enterprise_value, 2),
            "equity_value": round(equity_value, 2),
            "per_share_value": round(per_share, 2),
            "terminal_value": round(terminal_value, 2),
            "pv_terminal_value": round(pv_terminal, 2),
            "pv_fcf_total": round(sum(pf["pv"] for pf in pv_fcfs), 2),
            "discount_rate": discount_rate,
            "terminal_growth_rate": terminal_growth,
            "yearly_breakdown": pv_fcfs,
        }

    def _amortization(self, params: dict[str, Any]) -> dict[str, Any]:
        principal = params.get("principal", 0)
        annual_rate = params.get("annual_rate", 0.05)
        years = params.get("years", 30)
        payments_per_year = params.get("payments_per_year", 12)

        if principal <= 0 or years <= 0:
            return {"error": "principal and years must be positive"}

        rate = annual_rate / payments_per_year
        n = years * payments_per_year

        if rate == 0:
            payment = principal / n
        else:
            payment = principal * (rate * (1 + rate) ** n) / ((1 + rate) ** n - 1)

        total_paid = payment * n
        total_interest = total_paid - principal

        schedule = []
        balance = principal
        for period in range(1, n + 1):
            interest = balance * rate
            principal_paid = payment - interest
            balance -= principal_paid
            if period <= 12 or period == n or period % (payments_per_year * 5) == 0:
                schedule.append({
                    "period": period,
                    "payment": round(payment, 2),
                    "principal": round(principal_paid, 2),
                    "interest": round(interest, 2),
                    "balance": round(max(0, balance), 2),
                })

        return {
            "monthly_payment": round(payment, 2),
            "total_paid": round(total_paid, 2),
            "total_interest": round(total_interest, 2),
            "principal": principal,
            "annual_rate": annual_rate,
            "years": years,
            "schedule_sample": schedule,
        }

    def _escalation(self, params: dict[str, Any]) -> dict[str, Any]:
        base_price = params.get("base_price", 0)
        escalation_rate = params.get("escalation_rate", 0.02)
        years = params.get("years", 25)
        start_year = params.get("start_year", 1)
        price_floor = params.get("price_floor")
        price_ceiling = params.get("price_ceiling")
        discount_rate = params.get("discount_rate")

        if base_price <= 0:
            return {"error": "base_price must be positive"}

        schedule = []
        total_nominal = 0
        total_pv = 0

        for y in range(start_year, start_year + years):
            price = base_price * ((1 + escalation_rate) ** (y - start_year))
            if price_floor is not None:
                price = max(price, price_floor)
            if price_ceiling is not None:
                price = min(price, price_ceiling)

            pv = price
            if discount_rate:
                pv = price / ((1 + discount_rate) ** (y - start_year))

            total_nominal += price
            total_pv += pv

            schedule.append({
                "year": y,
                "price": round(price, 4),
                "pv_price": round(pv, 4) if discount_rate else None,
            })

        return {
            "base_price": base_price,
            "escalation_rate": escalation_rate,
            "price_year_1": round(schedule[0]["price"], 4),
            "price_year_10": round(schedule[min(9, len(schedule) - 1)]["price"], 4) if len(schedule) >= 10 else None,
            "price_year_20": round(schedule[min(19, len(schedule) - 1)]["price"], 4) if len(schedule) >= 20 else None,
            "price_final_year": round(schedule[-1]["price"], 4),
            "average_nominal": round(total_nominal / years, 4),
            "average_pv": round(total_pv / years, 4) if discount_rate else None,
            "total_nominal": round(total_nominal, 2),
            "total_pv": round(total_pv, 2) if discount_rate else None,
            "schedule": schedule,
        }

    def _bond_price(self, params: dict[str, Any]) -> dict[str, Any]:
        face_value = params.get("face_value", 1000)
        coupon_rate = params.get("coupon_rate", 0.05)
        ytm = params.get("yield_to_maturity", 0.05)
        years = params.get("years_to_maturity", 10)
        frequency = params.get("frequency", 2)

        coupon = face_value * coupon_rate / frequency
        n = years * frequency
        r = ytm / frequency

        pv_coupons = sum(coupon / ((1 + r) ** t) for t in range(1, n + 1))
        pv_face = face_value / ((1 + r) ** n)
        price = pv_coupons + pv_face

        current_yield = (coupon_rate * face_value) / price * 100
        duration = sum(
            (t / frequency) * (coupon / ((1 + r) ** t)) for t in range(1, n + 1)
        ) + (years * pv_face)
        duration /= price

        return {
            "bond_price": round(price, 2),
            "price_pct_of_par": round(price / face_value * 100, 2),
            "current_yield": round(current_yield, 2),
            "macaulay_duration": round(duration, 2),
            "pv_coupons": round(pv_coupons, 2),
            "pv_face_value": round(pv_face, 2),
            "annual_coupon": round(coupon_rate * face_value, 2),
            "face_value": face_value,
            "coupon_rate": coupon_rate,
            "ytm": ytm,
        }

    def _wacc(self, params: dict[str, Any]) -> dict[str, Any]:
        equity = params.get("equity_value", 0)
        debt = params.get("debt_value", 0)
        cost_of_equity = params.get("cost_of_equity", 0.10)
        cost_of_debt = params.get("cost_of_debt", 0.05)
        tax_rate = params.get("tax_rate", 0.21)

        total = equity + debt
        if total <= 0:
            return {"error": "equity_value + debt_value must be positive"}

        weight_equity = equity / total
        weight_debt = debt / total
        wacc = weight_equity * cost_of_equity + weight_debt * cost_of_debt * (1 - tax_rate)

        return {
            "wacc": round(wacc * 100, 2),
            "wacc_decimal": round(wacc, 6),
            "weight_equity": round(weight_equity * 100, 1),
            "weight_debt": round(weight_debt * 100, 1),
            "after_tax_cost_of_debt": round(cost_of_debt * (1 - tax_rate) * 100, 2),
            "equity_value": equity,
            "debt_value": debt,
            "cost_of_equity": cost_of_equity,
            "cost_of_debt": cost_of_debt,
            "tax_rate": tax_rate,
        }

    def _depreciation(self, params: dict[str, Any]) -> dict[str, Any]:
        cost = params.get("cost", 0)
        salvage = params.get("salvage_value", 0)
        life = params.get("useful_life", 10)
        method = params.get("method", "straight_line")

        if cost <= 0 or life <= 0:
            return {"error": "cost and useful_life must be positive"}

        depreciable = cost - salvage
        schedule = []

        if method == "straight_line":
            annual = depreciable / life
            book_value = cost
            for year in range(1, life + 1):
                book_value -= annual
                schedule.append({
                    "year": year,
                    "depreciation": round(annual, 2),
                    "accumulated": round(annual * year, 2),
                    "book_value": round(max(salvage, book_value), 2),
                })
        elif method == "declining_balance":
            rate = params.get("rate", 2 / life)
            book_value = cost
            accumulated = 0
            for year in range(1, life + 1):
                dep = book_value * rate
                if book_value - dep < salvage:
                    dep = book_value - salvage
                book_value -= dep
                accumulated += dep
                schedule.append({
                    "year": year,
                    "depreciation": round(dep, 2),
                    "accumulated": round(accumulated, 2),
                    "book_value": round(book_value, 2),
                })
        elif method == "macrs":
            macrs_rates = {
                5: [0.20, 0.32, 0.192, 0.1152, 0.1152, 0.0576],
                7: [0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446],
                10: [0.10, 0.18, 0.144, 0.1152, 0.0922, 0.0737, 0.0655, 0.0655, 0.0656, 0.0655, 0.0328],
            }
            rates = macrs_rates.get(life, macrs_rates[7])
            accumulated = 0
            for year, rate in enumerate(rates, 1):
                dep = cost * rate
                accumulated += dep
                schedule.append({
                    "year": year,
                    "rate": round(rate * 100, 2),
                    "depreciation": round(dep, 2),
                    "accumulated": round(accumulated, 2),
                    "book_value": round(cost - accumulated, 2),
                })
        else:
            return {"error": f"Unknown method: {method}. Use straight_line, declining_balance, or macrs"}

        return {
            "method": method,
            "cost": cost,
            "salvage_value": salvage,
            "depreciable_amount": round(depreciable, 2),
            "useful_life": life,
            "schedule": schedule,
        }

    def _breakeven(self, params: dict[str, Any]) -> dict[str, Any]:
        fixed_costs = params.get("fixed_costs", 0)
        variable_cost_per_unit = params.get("variable_cost_per_unit", 0)
        price_per_unit = params.get("price_per_unit", 0)
        target_profit = params.get("target_profit", 0)

        contribution = price_per_unit - variable_cost_per_unit
        if contribution <= 0:
            return {"error": "price_per_unit must exceed variable_cost_per_unit"}

        breakeven_units = math.ceil(fixed_costs / contribution)
        breakeven_revenue = breakeven_units * price_per_unit
        target_units = math.ceil((fixed_costs + target_profit) / contribution) if target_profit else None

        margin_of_safety = []
        for units in [breakeven_units, int(breakeven_units * 1.25), int(breakeven_units * 1.5), int(breakeven_units * 2)]:
            revenue = units * price_per_unit
            total_cost = fixed_costs + units * variable_cost_per_unit
            profit = revenue - total_cost
            margin_of_safety.append({
                "units": units,
                "revenue": round(revenue, 2),
                "total_cost": round(total_cost, 2),
                "profit": round(profit, 2),
            })

        return {
            "breakeven_units": breakeven_units,
            "breakeven_revenue": round(breakeven_revenue, 2),
            "contribution_margin": round(contribution, 2),
            "contribution_margin_ratio": round(contribution / price_per_unit * 100, 1),
            "target_units": target_units,
            "scenarios": margin_of_safety,
        }

    def _payback_period(self, params: dict[str, Any]) -> dict[str, Any]:
        initial_investment = abs(params.get("initial_investment", 0))
        cash_flows = params.get("cash_flows", [])
        discount_rate = params.get("discount_rate")

        if not cash_flows or initial_investment <= 0:
            return {"error": "initial_investment and cash_flows are required"}

        cumulative = 0.0
        payback = None
        discounted_cumulative = 0.0
        discounted_payback = None
        yearly = []

        for t, cf in enumerate(cash_flows, 1):
            cumulative += cf
            dcf = cf / ((1 + discount_rate) ** t) if discount_rate else cf
            discounted_cumulative += dcf

            yearly.append({
                "year": t,
                "cash_flow": round(cf, 2),
                "cumulative": round(cumulative, 2),
                "net_position": round(cumulative - initial_investment, 2),
            })

            if payback is None and cumulative >= initial_investment:
                prev = cumulative - cf
                fraction = (initial_investment - prev) / cf if cf else 0
                payback = t - 1 + fraction

            if discount_rate and discounted_payback is None and discounted_cumulative >= initial_investment:
                discounted_payback = t

        return {
            "payback_period_years": round(payback, 2) if payback else "Never",
            "discounted_payback": discounted_payback if discount_rate else None,
            "initial_investment": initial_investment,
            "total_cash_flows": round(sum(cash_flows), 2),
            "yearly_breakdown": yearly,
        }

    def _roi(self, params: dict[str, Any]) -> dict[str, Any]:
        investment = params.get("investment", 0)
        returns = params.get("returns", 0)
        years = params.get("years", 1)

        if investment <= 0:
            return {"error": "investment must be positive"}

        net_profit = returns - investment
        roi = (net_profit / investment) * 100
        annualized = ((returns / investment) ** (1 / years) - 1) * 100 if years > 1 else roi

        return {
            "roi_percent": round(roi, 2),
            "annualized_roi": round(annualized, 2),
            "net_profit": round(net_profit, 2),
            "investment": investment,
            "returns": returns,
            "years": years,
        }

    def _cagr(self, params: dict[str, Any]) -> dict[str, Any]:
        beginning_value = params.get("beginning_value", 0)
        ending_value = params.get("ending_value", 0)
        years = params.get("years", 1)

        if beginning_value <= 0 or years <= 0:
            return {"error": "beginning_value and years must be positive"}

        cagr = (ending_value / beginning_value) ** (1 / years) - 1

        projections = []
        for y in range(1, min(years + 6, 31)):
            projected = beginning_value * ((1 + cagr) ** y)
            projections.append({"year": y, "projected_value": round(projected, 2)})

        return {
            "cagr_percent": round(cagr * 100, 2),
            "cagr_decimal": round(cagr, 6),
            "beginning_value": beginning_value,
            "ending_value": ending_value,
            "years": years,
            "total_growth": round((ending_value / beginning_value - 1) * 100, 2),
            "projections": projections,
        }
