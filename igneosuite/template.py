"""Excel template authors can download, fill in and upload."""
from __future__ import annotations
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

ID_COLS = [("Sample ID", "Your sample name or number. Required.", True),
           ("Latitude", "Decimal degrees, north positive (e.g. 25.4567). Degrees-minutes-seconds with N/S also accepted. Required.", True),
           ("Longitude", "Decimal degrees, east positive (e.g. 33.1234). Degrees-minutes-seconds with E/W also accepted. Required.", True),
           ("Age (Ma)", "Crystallisation age in million years. Optional but recommended.", False)]
MAJORS = ["SiO2", "TiO2", "Al2O3", "Fe2O3t", "MnO", "MgO", "CaO", "Na2O", "K2O", "P2O5"]
TRACES = ["Sc", "V", "Cr", "Co", "Ni", "Cu", "Zn", "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Sn", "Cs", "Ba",
          "Hf", "Ta", "Pb", "Th", "U"]
REE = ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]

# Invented values for illustration only: they are not real analyses.
EXAMPLES = [
    ["EXAMPLE-1", 25.4567, 33.1234, 610,
     72.5, 0.25, 13.8, 2.1, 0.05, 0.40, 1.20, 3.90, 4.60, 0.06,
     4, 18, 6, 2, 3, 8, 45, 17, 160, 120, 35, 210, 18, 3, 3.5, 620, 6.0, 1.4, 22, 16, 4.2,
     38, 74, 8.1, 29, 5.8, 0.70, 5.0, 0.85, 5.2, 1.10, 3.2, 0.50, 3.3, 0.50],
    ["EXAMPLE-2", "25°20'15\"N", "33°40'30\"E", None,
     64.8, 0.62, 15.9, 4.8, 0.09, 1.90, 3.90, 4.10, 2.70, 0.18,
     9, 60, 25, 9, 12, 15, 60, 18, 75, 420, 19, 180, 9, None, 2.1, 690, 4.8, 0.7, 12, 9, 2.6,
     None, None, None, None, None, None, None, None, None, None, None, None, None, None],
    ["EXAMPLE-3", 24.9012, 34.0456, 585,
     76.1, 0.08, 12.3, 1.2, 0.03, 0.05, 0.40, 4.20, 4.70, None,
     None, None, None, None, None, None, 80, 24, 310, 15, 95, 250, 65, None, 6.0, 40, 9.5, 4.8, 35, 38, 8.0,
     45, 98, 11, 40, 10.5, 0.15, 10.2, 1.9, 12.8, 2.70, 8.3, 1.30, 8.9, 1.30],
]

HEAD = PatternFill("solid", fgColor="2A78D6")
REQ = PatternFill("solid", fgColor="0B2F5E")
EX = PatternFill("solid", fgColor="F4F3EF")
THIN = Border(bottom=Side(style="thin", color="E4E3DF"))


def build() -> bytes:
    wb = Workbook()
    ws = wb.active; ws.title = "Data"
    headers = [c[0] for c in ID_COLS] + [f"{m} wt.%" for m in MAJORS] + [f"{t} ppm" for t in TRACES] + [f"{r} ppm" for r in REE]
    ws.append(headers)
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=j)
        req = j <= 3
        c.fill = REQ if req else HEAD
        c.font = Font(bold=True, color="FFFFFF")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if j <= len(ID_COLS):
            c.comment = Comment(ID_COLS[j - 1][1], "IgneoSuite")
        ws.column_dimensions[get_column_letter(j)].width = 13 if j > 1 else 16
    for row in EXAMPLES:
        ws.append(row)
    for r in range(2, 2 + len(EXAMPLES)):
        for j in range(1, len(headers) + 1):
            ws.cell(row=r, column=j).fill = EX
            ws.cell(row=r, column=j).font = Font(italic=True, color="52514E")
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "B2"
    for col, lim in (("B", 90), ("C", 180)):
        dv = DataValidation(type="decimal", operator="between", formula1=str(-lim), formula2=str(lim), allow_blank=True,
                            showErrorMessage=False, showInputMessage=True,
                            promptTitle="Decimal degrees", prompt=f"Between -{lim} and {lim}. N/E positive.")
        ws.add_data_validation(dv); dv.add(f"{col}5:{col}100000")
    dv = DataValidation(type="decimal", operator="between", formula1="0", formula2="4600", allow_blank=True,
                        showErrorMessage=True, errorTitle="Age", error="Age must be between 0 and 4,600 Ma.")
    ws.add_data_validation(dv); dv.add("D2:D100000")

    ins = wb.create_sheet("Instructions", 0)
    lines = [
        ("IgneoSuite data template", True),
        ("", False),
        ("1. Fill the sheet 'Data': one sample per row. Delete the three grey EXAMPLE rows first (their values are invented).", False),
        ("2. Sample ID, Latitude and Longitude are required for every sample (dark blue headers).", False),
        ("3. Latitude and longitude: decimal degrees, WGS84, north and east positive (e.g. 25.4567, 33.1234).", False),
        ("   Also accepted: 25°27'24\"N, 25 27 24 N, 25°27.4'N, N25.4567, 33.12W. They are converted to decimal degrees.", False),
        ("4. Age (Ma) is optional but recommended (crystallisation age in million years).", False),
        ("5. Major oxides in wt.%, trace elements and REE in ppm. Leave a cell empty if not analysed.", False),
        ("   Values reported below detection limit (e.g. '<0.5' or 'b.d.l.') are read as missing.", False),
        ("6. You may delete columns you did not analyse, or add others (keep the unit in the header).", False),
        ("7. Upload the file in IgneoSuite, step 1. Only the sheet you choose is read.", False),
    ]
    for t, bold in lines:
        ins.append([t])
        ins.cell(row=ins.max_row, column=1).font = Font(bold=bold, size=14 if bold else 11)
    ins.column_dimensions["A"].width = 120
    wb.active = 1
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()
