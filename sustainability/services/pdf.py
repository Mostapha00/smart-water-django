from io import BytesIO


def render_audit_pdf(report):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen.canvas import Canvas
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
        y = 755
        for key, value in report.snapshot.items():
            lines.append(f"{key.replace('_', ' ').title()}: {value}")
        for line in lines:
            canvas.drawString(50, y, str(line)[:130])
            y -= 18
        canvas.save()
        return output.getvalue()
    except ImportError:
        return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
