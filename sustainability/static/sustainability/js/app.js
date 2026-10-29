/* Smart Water Platform — Module 4 shell behaviour.
 * Phase 1 scope: mobile sidebar toggling and shared chart defaults.
 * Kept dependency-free (no jQuery) so later phases can extend it safely.
 */
(function () {
    'use strict';

    function initSidebar() {
        var toggle = document.querySelector('[data-sidebar-toggle]');
        var backdrop = document.querySelector('[data-sidebar-backdrop]');
        if (!toggle || !backdrop) { return; }

        function setOpen(open) {
            document.body.classList.toggle('sidebar-open', open);
            backdrop.hidden = !open;
        }

        toggle.addEventListener('click', function () {
            setOpen(!document.body.classList.contains('sidebar-open'));
        });
        backdrop.addEventListener('click', function () { setOpen(false); });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') { setOpen(false); }
        });
    }

    function initChartDefaults() {
        if (typeof window.Chart === 'undefined') { return; }
        Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
        Chart.defaults.color = '#64748b';
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.boxWidth = 8;
        Chart.defaults.elements.line.tension = 0.35;
    }

    document.addEventListener('DOMContentLoaded', function () {
        initSidebar();
        initChartDefaults();
    });
})();
