# sustainability — Économies & audits

Responsable : **Student 4**.

```
Classes à implémenter (voir le diagramme de classes du dossier de validation) :

- WaterSavingsTarget  : site (FK infrastructure.Site), period_start, period_end,
                        baseline_volume_m3, target_savings_m3, measured_volume_m3
                        méthode : measure_progress()
- WaterSavingsProject : site, manager (FK accounts.AuditManager), origin_incident (FK quality_leaks.LeakIncident),
                        name, project_type, investment_tnd, annual_savings_m3, annual_net_gain_tnd,
                        roi_pct, profile_cluster, model_version, analyzed_at
                        méthodes : calculate_roi(), classify_profile()
- WaterAuditReport    : site, manager, projects (M2M), title, période, budget_tnd, summary,
                        optimization_result (JSON), optimizer_version, optimized_at, generated_at
                        méthodes : optimize_portfolio() (PuLP), generate_pdf() (ReportLab)

Règle du projet : les rapports séparent les économies MESURÉES des économies ESTIMÉES.
```

Travailler sur une branche `feature/sustainability-...` puis ouvrir une pull request vers `main`.
