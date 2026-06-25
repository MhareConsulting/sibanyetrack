from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import mm

PURPLE = HexColor("#8A2BE2")
CYAN = HexColor("#00C8FF")
PERI = HexColor("#EEF0FB")
GREY = HexColor("#555555")
LINEC = HexColor("#C5CAE9")
FIELDBG = HexColor("#FBFBFE")

W, H = A4
LM, RM, TM, BM = 40, 40, 56, 50
CW = W - LM - RM

class Form:
    def __init__(self, path):
        self.c = canvas.Canvas(path, pagesize=A4)
        self.c.setTitle("myTrack Business Needs Assessment")
        self.c.setAuthor("myTrack (MyReach)")
        self.n = 0
        self.page = 0
        self._newpage()

    def fname(self, base):
        self.n += 1
        return f"{base}_{self.n}"

    def _header(self):
        c = self.c
        c.setFillColor(PURPLE); c.setFont("Helvetica-Bold", 12)
        c.drawString(LM, H - 34, "myTrack")
        c.setFillColor(GREY); c.setFont("Helvetica", 9)
        c.drawRightString(W - RM, H - 34, "Business Needs Assessment")
        c.setStrokeColor(CYAN); c.setLineWidth(1.5)
        c.line(LM, H - 40, W - RM, H - 40)

    def _footer(self):
        c = self.c
        c.setFillColor(GREY); c.setFont("Helvetica", 7)
        c.drawCentredString(W / 2, 30, f"myTrack — a MyReach product   |   Confidential   |   Page {self.page}")

    def _newpage(self):
        if self.page:
            self._footer(); self.c.showPage()
        self.page += 1
        self._header()
        self.y = H - TM

    def need(self, h):
        if self.y - h < BM:
            self._newpage()

    # ---- elements ----------------------------------------------------------
    def cover(self):
        c = self.c
        self.y = H - 90
        c.setFillColor(PURPLE); c.setFont("Helvetica-Bold", 34)
        c.drawString(LM, self.y, "myTrack"); self.y -= 22
        c.setFillColor(GREY); c.setFont("Helvetica-Oblique", 11)
        c.drawString(LM, self.y, "Track it. Protect it. myTrack.")
        c.setStrokeColor(CYAN); c.setLineWidth(2); c.line(LM, self.y - 6, W - RM, self.y - 6)
        self.y -= 40
        c.setFillColor(black); c.setFont("Helvetica-Bold", 22)
        c.drawString(LM, self.y, "Business Needs Assessment"); self.y -= 20
        c.setFillColor(GREY); c.setFont("Helvetica", 11)
        c.drawString(LM, self.y, "Fleet telematics requirements & scoping form"); self.y -= 28
        self.two_fields("Assessment ref:", "ref", "Date:", "date")
        self.two_fields("Completed by (myTrack):", "completedby", "Branch:", "branch")
        self.y -= 6

    def section(self, num, title):
        self.need(40)
        self.y -= 6
        c = self.c
        bar_h = 20
        c.setFillColor(PURPLE); c.rect(LM, self.y - bar_h, CW, bar_h, fill=1, stroke=0)
        c.setFillColor(white); c.setFont("Helvetica-Bold", 11)
        c.drawString(LM + 8, self.y - bar_h + 6, f"{num}.  {title}")
        self.y -= bar_h + 10

    def note(self, text):
        self.need(16)
        self.c.setFillColor(GREY); self.c.setFont("Helvetica-Oblique", 8)
        self.c.drawString(LM, self.y, text); self.y -= 14

    def _textfield(self, name, x, y, w, h=14):
        self.c.acroForm.textfield(name=self.fname(name), x=x, y=y, width=w, height=h,
            fontSize=9, borderWidth=0.5, borderColor=LINEC, fillColor=FIELDBG,
            textColor=black, forceBorder=True)

    def field(self, label, name, label_w=None):
        self.need(24)
        c = self.c
        c.setFillColor(black); c.setFont("Helvetica-Bold", 9.5)
        lw = label_w or c.stringWidth(label, "Helvetica-Bold", 9.5) + 8
        c.drawString(LM, self.y - 10, label)
        fx = LM + lw
        self._textfield(name, fx, self.y - 14, W - RM - fx)
        self.y -= 24

    def two_fields(self, l1, n1, l2, n2):
        self.need(24)
        c = self.c; half = CW / 2
        c.setFillColor(black); c.setFont("Helvetica-Bold", 9.5)
        l1w = c.stringWidth(l1, "Helvetica-Bold", 9.5) + 6
        c.drawString(LM, self.y - 10, l1)
        self._textfield(n1, LM + l1w, self.y - 14, half - l1w - 10)
        x2 = LM + half
        l2w = c.stringWidth(l2, "Helvetica-Bold", 9.5) + 6
        c.drawString(x2, self.y - 10, l2)
        self._textfield(n2, x2 + l2w, self.y - 14, (W - RM) - (x2 + l2w))
        self.y -= 24

    def checks(self, label, opts, name="cb"):
        self.need(22)
        c = self.c
        x = LM
        if label:
            c.setFillColor(black); c.setFont("Helvetica-Bold", 9.5)
            c.drawString(x, self.y - 10, label)
            x += c.stringWidth(label, "Helvetica-Bold", 9.5) + 12
        for o in opts:
            sz = 10
            self.c.acroForm.checkbox(name=self.fname(name), x=x, y=self.y - 12, size=sz,
                borderWidth=0.5, borderColor=LINEC, fillColor=white, buttonStyle="check")
            c.setFillColor(black); c.setFont("Helvetica", 9)
            c.drawString(x + sz + 4, self.y - 10, o)
            x += sz + 8 + c.stringWidth(o, "Helvetica", 9) + 16
            if x > W - RM - 40 and o != opts[-1]:
                self.y -= 16; x = LM + 12
        self.y -= 22

    def grid(self, headers, widths, n_rows, fields=True, check_cols=None):
        """Table with fillable cells. check_cols: list of col indices that get checkboxes instead of text."""
        check_cols = check_cols or []
        rh = 20
        total_h = rh * (n_rows + 1)
        self.need(total_h + 6)
        c = self.c
        x0 = LM
        # header
        c.setFillColor(PURPLE); c.rect(x0, self.y - rh, sum(widths), rh, fill=1, stroke=0)
        c.setFillColor(white); c.setFont("Helvetica-Bold", 8)
        cx = x0
        for h, wdt in zip(headers, widths):
            c.drawCentredString(cx + wdt / 2, self.y - rh + 6, h)
            cx += wdt
        top = self.y - rh
        # body grid
        c.setStrokeColor(LINEC); c.setLineWidth(0.5)
        for r in range(n_rows):
            ry = top - rh * (r + 1)
            cx = x0
            for ci, wdt in enumerate(widths):
                c.rect(cx, ry, wdt, rh, fill=0, stroke=1)
                if fields and ci in check_cols:
                    self.c.acroForm.checkbox(name=self.fname("g"), x=cx + wdt / 2 - 5,
                        y=ry + rh / 2 - 5, size=10, borderWidth=0.4, borderColor=LINEC,
                        fillColor=white, buttonStyle="check")
                elif fields:
                    self.c.acroForm.textfield(name=self.fname("g"), x=cx + 1, y=ry + 1,
                        width=wdt - 2, height=rh - 2, fontSize=8, borderWidth=0,
                        fillColor=FIELDBG, textColor=black)
                cx += wdt
        # header top border
        c.rect(x0, top, sum(widths), rh, fill=0, stroke=1)
        self.y = top - rh * n_rows - 6

    def gap(self, h=8):
        self.y -= h

    def save(self):
        self._footer(); self.c.save()


def col(widths_pct):
    return [CW * p for p in widths_pct]

f = Form("myTrack_Needs_Assessment.pdf")
f.cover()

# 1
f.section(1, "Client / Company Profile")
f.field("Company name:", "company")
f.two_fields("Industry / sector:", "industry", "Company reg. no.:", "regno")
f.two_fields("Primary contact:", "contact", "Role:", "role")
f.two_fields("Phone:", "phone", "Email:", "email")
f.field("Decision-maker (if different):", "dm")
f.field("Billing contact & email:", "billing")
f.two_fields("No. of branches / depots:", "depots", "Head-office location:", "ho")

# 2
f.section(2, "Fleet Profile")
f.note("One row per vehicle group. Tank size + CAN/OBD availability drive hardware selection and unit cost.")
f.grid(["Qty", "Vehicle type", "Make / Model", "Year", "Fuel type", "Tank (L)", "CAN? Y/N", "OBD? Y/N"],
       col([0.08, 0.18, 0.20, 0.08, 0.13, 0.11, 0.11, 0.11]), 6)
f.note("Vehicle types: truck / rigid / van / bakkie / sedan / trailer / reefer / yellow-metal.")

# 3
f.section(3, "Operational Context")
f.field("Operating provinces / regions:", "regions")
f.checks("Route profile:", ["Local / urban", "Long-haul", "Cross-border (roaming)"])
f.field("Depots & yards (locations):", "yards")
f.two_fields("Hours of operation:", "hours", "Shift pattern:", "shift")

# 4
f.section(4, "Objectives & Pain Points")
f.note("Rank the client's priorities 1 (highest) to 5. Leave blank if not relevant.")
objs = ["Stop / reduce fuel theft", "Asset visibility & recovery", "Driver safety & behaviour",
        "Compliance (licence / PDP expiry)", "Utilisation & idle-cost reduction",
        "Customer ETAs / delivery proof", "Insurance premium reduction"]
# header row for objectives table
f.need(18 * (len(objs) + 1) + 6)
c = f.c
c.setFillColor(PURPLE); c.rect(LM, f.y - 18, CW, 18, fill=1, stroke=0)
c.setFillColor(white); c.setFont("Helvetica-Bold", 8)
c.drawCentredString(LM + CW * 0.375, f.y - 18 + 5, "Objective")
c.drawCentredString(LM + CW * 0.875, f.y - 18 + 5, "Priority (1-5)")
f.y -= 18
for o in objs:
    f.need(20)
    c = f.c
    rh = 18
    c.setStrokeColor(LINEC); c.setLineWidth(0.5)
    c.rect(LM, f.y - rh, CW * 0.75, rh, fill=0, stroke=1)
    c.rect(LM + CW * 0.75, f.y - rh, CW * 0.25, rh, fill=0, stroke=1)
    c.setFillColor(black); c.setFont("Helvetica", 9)
    c.drawString(LM + 6, f.y - rh + 5, o)
    f.c.acroForm.textfield(name=f.fname("prio"), x=LM + CW * 0.75 + 1, y=f.y - rh + 1,
        width=CW * 0.25 - 2, height=rh - 2, fontSize=8, borderWidth=0, fillColor=FIELDBG, textColor=black)
    f.y -= rh
f.gap(4)
f.field("Other objectives:", "otherobj")

# 5
f.section(5, "Feature Requirements")
f.note("Mark each myTrack feature as Must-have, Nice-to-have, or Not needed.")
feats = ["Live GPS tracking", "Fuel theft detection", "Driver behaviour scoring", "Speed limit enforcement",
         "Compliance alerts (licence / PDP)", "Fuel consumption reports", "WhatsApp driver notifications",
         "Geofencing", "Multi-depot / multi-branch", "Delivery / customer tracking share",
         "Idle & fleet-cost reporting", "Geofence dwell-time reporting"]
# header
f.need(20 * (len(feats) + 1) + 6)
c = f.c
widths = col([0.46, 0.18, 0.18, 0.18])
rh = 20
c.setFillColor(PURPLE); c.rect(LM, f.y - rh, CW, rh, fill=1, stroke=0)
c.setFillColor(white); c.setFont("Helvetica-Bold", 8)
hdrs = ["Feature", "Must-have", "Nice-to-have", "Not needed"]
cx = LM
for h, wd in zip(hdrs, widths):
    c.drawCentredString(cx + wd / 2, f.y - rh + 6, h); cx += wd
top = f.y - rh
c.setStrokeColor(LINEC); c.setLineWidth(0.5)
for r, ft in enumerate(feats):
    ry = top - rh * (r + 1)
    cx = LM
    for ci, wd in enumerate(widths):
        c.rect(cx, ry, wd, rh, fill=0, stroke=1)
        if ci == 0:
            c.setFillColor(black); c.setFont("Helvetica", 9)
            c.drawString(cx + 6, ry + 6, ft)
        else:
            f.c.acroForm.checkbox(name=f.fname("feat"), x=cx + wd / 2 - 5, y=ry + rh / 2 - 5,
                size=10, borderWidth=0.4, borderColor=LINEC, fillColor=white, buttonStyle="check")
        cx += wd
c.rect(LM, top, CW, rh, fill=0, stroke=1)
f.y = top - rh * len(feats) - 6

# 6
f.section(6, "Hardware Requirements")
f.note("Per vehicle group. Base unit = Teltonika FMB tracker. Data source: CAN adapter (LV-CAN200) preferred, OBD plug for light vehicles, LLS fuel probe as fallback.")
f.grid(["Vehicle group", "Data source (CAN/OBD/Probe)", "Accessories required", "Qty"],
       col([0.24, 0.26, 0.36, 0.14]), 5)
f.checks("Accessory key:", ["Panic", "Immobiliser", "RFID / iButton", "Temp sensor", "Backup battery"])

# 7
f.section(7, "Installation Logistics")
f.checks("Install location:", ["At depot (single site)", "Multiple sites", "Mobile / on-site"])
f.two_fields("No. of sites:", "sites", "Furthest site (km):", "km")
f.field("Vehicle downtime windows available:", "downtime")
f.checks("Certified auto-electrician required on-site?", ["Yes", "No"])
f.field("Scheduling notes / constraints:", "sched")

# 8
f.section(8, "Connectivity & Data")
f.checks("SIM / data supplied by:", ["myTrack", "Client"])
f.field("Network coverage concerns in operating area:", "coverage")
f.checks("Cross-border roaming required?", ["Yes", "No"])

# 9
f.section(9, "Integration & Reporting")
f.field("Existing systems (ERP / fuel cards / accounting):", "systems")
f.checks("API / integration needed?", ["Yes", "No"])
f.two_fields("No. of platform users / logins:", "users", "Report cadence:", "cadence")
f.checks("White-label / client branding required?", ["Yes", "No"])

# 10
f.section(10, "Compliance & Data Governance")
f.checks("POPIA consent process in place for driver tracking?", ["Yes", "No", "Needs guidance"])
f.two_fields("Required data-retention period:", "retention", "Data owner:", "owner")

# 11
f.section(11, "Commercial")
f.field("Budget range / expectation:", "budget")
f.checks("Preferred contract term:", ["12 months", "24 months", "36 months"])
f.checks("Hardware billing preference:", ["Upfront (once-off)", "Amortised into monthly"])
f.two_fields("Payment terms:", "payment", "Billing entity:", "entity")

# 12
f.section(12, "Service & Support")
f.field("SLA / response-time expectations:", "sla")
f.checks("Training required?", ["Yes - on-site", "Yes - remote", "No"])
f.field("Support hours expected:", "supporthours")

# 13
f.section(13, "Sign-off")
f.gap(6)
f.two_fields("myTrack assessor:", "assessor", "Date:", "sdate1")
f.gap(10)
f.two_fields("Client name & signature:", "clientsig", "Date:", "sdate2")
f.gap(4)
f.note("Information gathered is used to prepare an indicative subscription proposal (once-off install, initiation fee, monthly per-unit cost). Pricing subject to site survey. E&OE.")

f.save()
print("saved", f.page, "pages")
