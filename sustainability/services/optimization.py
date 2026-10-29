"""Budget optimisation with optional PuLP and a deterministic greedy fallback."""
from decimal import Decimal


def optimize_projects(projects, budget):
    projects = list(projects)
    budget = Decimal(str(budget))
    chosen = []
    solver = "greedy-fallback"
    try:
        import pulp
        problem = pulp.LpProblem("water_savings", pulp.LpMaximize)
        variables = [pulp.LpVariable(f"project_{p.pk}", cat="Binary") for p in projects]
        problem += pulp.lpSum(float(p.expected_savings_m3) * v for p, v in zip(projects, variables))
        problem += pulp.lpSum(float(p.budget_tnd) * v for p, v in zip(projects, variables)) <= float(budget)
        problem.solve(pulp.PULP_CBC_CMD(msg=False))
        chosen = [p for p, v in zip(projects, variables) if v.value() and v.value() > 0.5]
        solver = "PuLP"
    except (ImportError, Exception):
        # A ratio sort is always available when optional scientific packages are not.
        chosen = sorted(projects, key=lambda p: (p.expected_savings_m3 / p.budget_tnd if p.budget_tnd else Decimal("0")), reverse=True)
        selected, spent = [], Decimal("0")
        for project in chosen:
            if spent + project.budget_tnd <= budget:
                selected.append(project)
                spent += project.budget_tnd
        chosen = selected
    spent = sum((p.budget_tnd for p in chosen), Decimal("0"))
    savings = sum((p.expected_savings_m3 for p in chosen), Decimal("0"))
    annual = sum((p.expected_annual_savings_tnd for p in chosen), Decimal("0"))
    payback = (spent / annual * 12).quantize(Decimal("0.01")) if annual else None
    return {"projects": chosen, "solver": solver, "total_cost": spent, "savings": savings, "annual_savings": annual, "payback": payback}
