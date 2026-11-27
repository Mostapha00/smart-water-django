"""Choix des projets sous budget : programmation linéaire en nombres entiers (PuLP), sinon tri glouton.

PuLP maximise les m³ économisés sans dépasser le budget (problème du sac à dos) : la solution est optimale.
Le tri glouton (meilleur rapport m³/TND d'abord) ne sert que si PuLP est absent ou ne trouve pas de solution
optimale ; la raison est alors écrite dans le journal. Le solveur utilisé est enregistré avec le résultat.
"""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def _pulp_selection(projects, budget):
    """Projets choisis par PuLP, ou None si PuLP est absent ou sans solution optimale."""
    try:
        import pulp
    except ImportError:
        logger.warning("PuLP n'est pas installé (requirements.txt) : sélection gloutonne utilisée.")
        return None
    try:
        problem = pulp.LpProblem("water_savings", pulp.LpMaximize)
        variables = [pulp.LpVariable(f"project_{p.pk}", cat="Binary") for p in projects]
        problem += pulp.lpSum(float(p.expected_savings_m3) * v for p, v in zip(projects, variables))
        problem += pulp.lpSum(float(p.budget_tnd) * v for p, v in zip(projects, variables)) <= float(budget)
        problem.solve(pulp.PULP_CBC_CMD(msg=False))
    except pulp.PulpError:
        logger.exception("PuLP a échoué : sélection gloutonne utilisée.")
        return None
    status = pulp.LpStatus[problem.status]
    if status != "Optimal":
        logger.warning("PuLP n'a pas trouvé de solution optimale (%s) : sélection gloutonne utilisée.", status)
        return None
    return [p for p, v in zip(projects, variables) if v.value() and v.value() > 0.5]


def _greedy_selection(projects, budget):
    ranked = sorted(projects, key=lambda p: (p.expected_savings_m3 / p.budget_tnd if p.budget_tnd else Decimal("0")), reverse=True)
    selected, spent = [], Decimal("0")
    for project in ranked:
        if spent + project.budget_tnd <= budget:
            selected.append(project)
            spent += project.budget_tnd
    return selected


def optimize_projects(projects, budget):
    projects = list(projects)
    budget = Decimal(str(budget))
    chosen = _pulp_selection(projects, budget) if projects else []
    solver = "PuLP"
    if chosen is None:
        chosen, solver = _greedy_selection(projects, budget), "greedy-fallback"
    spent = sum((p.budget_tnd for p in chosen), Decimal("0"))
    savings = sum((p.expected_savings_m3 for p in chosen), Decimal("0"))
    annual = sum((p.expected_annual_savings_tnd for p in chosen), Decimal("0"))
    payback = (spent / annual * 12).quantize(Decimal("0.01")) if annual else None
    return {"projects": chosen, "solver": solver, "total_cost": spent, "savings": savings, "annual_savings": annual, "payback": payback}
