from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.schemas.orders import ReportOut


def report_to_excel(report: ReportOut) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Reporte diario"
    sheet["A1"] = f"QR System - Reporte {report.date}"
    sheet["A1"].font = Font(size=16, bold=True)
    sheet["A3"] = "Total pedidos"
    sheet["B3"] = report.total_orders

    sections = [
        ("Atendidos por origen", report.attended_by_origin),
        ("Tipos de desayuno", report.breakfast_types),
        ("Adicionales mas pedidos", report.extras),
        ("Horas pico", report.peak_hours),
        ("Motivos de cancelacion", report.cancellation_reasons),
    ]

    row = 5
    header_fill = PatternFill("solid", fgColor="1F6F5B")
    for title, data in sections:
        sheet.cell(row=row, column=1, value=title).font = Font(bold=True)
        row += 1
        sheet.cell(row=row, column=1, value="Concepto")
        sheet.cell(row=row, column=2, value="Cantidad")
        for cell in sheet[row]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
        row += 1
        if data:
            for label, value in data.items():
                sheet.cell(row=row, column=1, value=label)
                sheet.cell(row=row, column=2, value=value)
                row += 1
        else:
            sheet.cell(row=row, column=1, value="Sin datos")
            sheet.cell(row=row, column=2, value=0)
            row += 1
        row += 1

    sheet.column_dimensions["A"].width = 42
    sheet.column_dimensions["B"].width = 16
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output
