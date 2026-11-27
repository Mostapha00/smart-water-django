from io import BytesIO


class PdfUnavailable(RuntimeError):
    """ReportLab n'est pas installé : impossible de produire un vrai PDF."""


def render_audit_pdf(report):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:
        # Avant : un faux PDF vide était téléchargé sans avertissement.
        raise PdfUnavailable("ReportLab n'est pas installé : lancez « pip install -r requirements.txt ».") from exc

    output = BytesIO()
    canvas = Canvas(output, pagesize=A4)
    canvas.setTitle("Water Footprint Audit")
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(50, 790, "AquaMind — Water Footprint Audit")
    canvas.setFont("Helvetica", 10)
    lines = [
        f"Period: {report.period_start} to {report.period_end}",
        f"Site: {report.site or 'All sites'}",
        f"Generated: {report.created_at:%Y-%m-%d %H:%M}",
    ]
    for key, value in report.snapshot.items():
        lines.append(f"{key.replace('_', ' ').title()}: {value}")
    y = 755
    for line in lines:
        if y < 50:  # page pleine : nouvelle page
            canvas.showPage()
            canvas.setFont("Helvetica", 10)
            y = 790
        canvas.drawString(50, y, str(line)[:130])
        y -= 18
    canvas.save()
    return output.getvalue()
