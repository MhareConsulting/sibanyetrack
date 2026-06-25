import csv
from datetime import datetime
from io import BytesIO, StringIO

from django.http import HttpResponse
from django.utils import timezone


def _normalize_rows(rows):
    if hasattr(rows, "values"):
        rows = list(rows.values())
    else:
        rows = list(rows)
    return rows


def _format_value(value):
    if isinstance(value, datetime):
        local_dt = timezone.localtime(value, timezone.get_current_timezone())
        return local_dt.strftime("%d-%m-%Y %H:%M")
    return value


def _format_rows(rows):
    out = []
    for row in rows:
        out.append({key: _format_value(value) for key, value in row.items()})
    return out


def export_csv_response(filename, rows, metadata=None):
    rows = _normalize_rows(rows)
    rows = _format_rows(rows)
    metadata = metadata or {}
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response)
    if metadata:
        writer.writerow(["Report", metadata.get("title", filename)])
        writer.writerow(["Organisation", metadata.get("organisation", "")])
        writer.writerow(["Depot", metadata.get("depot", "All Depots")])
        writer.writerow(["Vehicle Filter", metadata.get("vehicle", "All Vehicles")])
        writer.writerow(["Date Range", metadata.get("date_range", "")])
        writer.writerow(["Generated At (Joburg)", metadata.get("generated_at", "")])
        writer.writerow([])
    if not rows:
        writer.writerow(["No data"])
        return response
    headers = list(rows[0].keys())
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    return response


def export_pdf_response(filename, title, rows, metadata=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rows = _format_rows(_normalize_rows(rows))
    metadata = metadata or {}
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    styles = getSampleStyleSheet()
    if rows:
        headers = list(rows[0].keys())
        table_rows = [headers] + [[row.get(h, "") for h in headers] for row in rows]
    else:
        table_rows = [["No data"]]
    table = Table(table_rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8A2BE2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    meta_lines = [
        f"Organisation: {metadata.get('organisation', '')}",
        f"Depot: {metadata.get('depot', 'All Depots')}",
        f"Vehicle Filter: {metadata.get('vehicle', 'All Vehicles')}",
        f"Date Range: {metadata.get('date_range', '')}",
        f"Generated At (Joburg): {metadata.get('generated_at', '')}",
    ]
    doc.build(
        [
            Paragraph(title, styles["Heading2"]),
            Paragraph("<br/>".join(meta_lines), styles["Normal"]),
            Spacer(1, 0.2 * cm),
            table,
        ]
    )
    buf.seek(0)
    response = HttpResponse(buf.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


def export_xlsx_response(filename, rows, metadata=None):
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for XLSX exports.") from exc

    rows = _format_rows(_normalize_rows(rows))
    metadata = metadata or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    if metadata:
        ws.append(["Report", metadata.get("title", filename)])
        ws.append(["Organisation", metadata.get("organisation", "")])
        ws.append(["Depot", metadata.get("depot", "All Depots")])
        ws.append(["Vehicle Filter", metadata.get("vehicle", "All Vehicles")])
        ws.append(["Date Range", metadata.get("date_range", "")])
        ws.append(["Generated At (Joburg)", metadata.get("generated_at", "")])
        ws.append([])
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row.get(h, "") for h in headers])
    else:
        ws.append(["No data"])
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def render_csv_string(rows):
    rows = _format_rows(_normalize_rows(rows))
    if not rows:
        return "No data\r\n"
    out = StringIO()
    writer = csv.writer(out)
    headers = list(rows[0].keys())
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    return out.getvalue()
