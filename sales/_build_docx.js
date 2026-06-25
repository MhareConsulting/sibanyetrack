const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, BorderStyle, WidthType, ShadingType,
        VerticalAlign, PageNumber, HeadingLevel, TableOfContents, Bookmark } = require("docx");

const PURPLE = "8A2BE2", CYAN = "00C8FF", PERI = "EEF0FB", GREY = "555555", INK = "0A0A0A";
const CW = 9746; // content width (A4, 0.75" margins)
const FONT = "Arial";

const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const cellBorder = { style: BorderStyle.SINGLE, size: 1, color: "C5CAE9" };
const cellBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };

// ---- helpers ---------------------------------------------------------------
function sectionBar(num, title) {
  return new Paragraph({
    spacing: { before: 260, after: 120 },
    shading: { type: ShadingType.CLEAR, fill: PURPLE },
    children: [new TextRun({ text: `  ${num}.  ${title}`, bold: true, color: "FFFFFF", size: 24, font: FONT })],
  });
}
function note(text) {
  return new Paragraph({ spacing: { after: 80 },
    children: [new TextRun({ text, italics: true, color: GREY, size: 16, font: FONT })] });
}
const LINE = (n) => " ".repeat(n);
function field(label, width = 60) {
  // label in bold, then an underlined blank to write on
  return new Paragraph({
    spacing: { after: 100 },
    children: [
      new TextRun({ text: label + "  ", bold: true, size: 20, font: FONT }),
      new TextRun({ text: LINE(width), underline: {}, size: 20, font: FONT }),
    ],
  });
}
function twoFields(l1, w1, l2, w2) {
  return new Paragraph({
    spacing: { after: 100 },
    children: [
      new TextRun({ text: l1 + "  ", bold: true, size: 20, font: FONT }),
      new TextRun({ text: LINE(w1), underline: {}, size: 20, font: FONT }),
      new TextRun({ text: "      " + l2 + "  ", bold: true, size: 20, font: FONT }),
      new TextRun({ text: LINE(w2), underline: {}, size: 20, font: FONT }),
    ],
  });
}
function checks(label, opts) {
  const kids = [];
  if (label) kids.push(new TextRun({ text: label + "   ", bold: true, size: 20, font: FONT }));
  opts.forEach((o, i) => {
    kids.push(new TextRun({ text: "☐ " + o + (i < opts.length - 1 ? "     " : ""), size: 20, font: FONT }));
  });
  return new Paragraph({ spacing: { after: 100 }, children: kids });
}
function hcell(text, w, opts = {}) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA }, borders: cellBorders,
    shading: { type: ShadingType.CLEAR, fill: opts.fill || PURPLE },
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({ alignment: opts.align || AlignmentType.LEFT,
      children: [new TextRun({ text, bold: true, color: opts.color || "FFFFFF", size: 16, font: FONT })] })],
  });
}
function bcell(text, w, opts = {}) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA }, borders: cellBorders,
    margins: { top: 70, bottom: 70, left: 90, right: 90 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({ alignment: opts.align || AlignmentType.LEFT,
      children: [new TextRun({ text: text || "", size: opts.size || 18, font: FONT,
        color: opts.color || INK })] })],
  });
}
function table(cols, headers, bodyRows) {
  const rows = [new TableRow({ tableHeader: true, children: headers.map((h, i) => hcell(h, cols[i], { align: AlignmentType.CENTER })) })];
  bodyRows.forEach(r => rows.push(new TableRow({ children: r.map((c, i) => bcell(c, cols[i], { align: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER })) })));
  return new Table({ width: { size: CW, type: WidthType.DXA }, columnWidths: cols, rows });
}
function spacer() { return new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "", size: 8 })] }); }

// ---- document content ------------------------------------------------------
const children = [];

// Cover
children.push(new Paragraph({ spacing: { after: 40 },
  children: [new TextRun({ text: "myTrack", bold: true, color: PURPLE, size: 56, font: FONT })] }));
children.push(new Paragraph({ spacing: { after: 60 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: CYAN, space: 2 } },
  children: [new TextRun({ text: "Track it. Protect it. myTrack.", italics: true, color: GREY, size: 22, font: FONT })] }));
children.push(new Paragraph({ spacing: { before: 200, after: 40 },
  children: [new TextRun({ text: "Business Needs Assessment", bold: true, size: 40, font: FONT })] }));
children.push(new Paragraph({ spacing: { after: 200 },
  children: [new TextRun({ text: "Fleet telematics requirements & scoping form", color: GREY, size: 22, font: FONT })] }));
children.push(twoFields("Assessment ref:", 24, "Date:", 24));
children.push(twoFields("Completed by (myTrack):", 30, "Branch:", 20));

// 1. Client / Company Profile
children.push(sectionBar(1, "Client / Company Profile"));
children.push(field("Company name:", 70));
children.push(twoFields("Industry / sector:", 36, "Company reg. no.:", 24));
children.push(twoFields("Primary contact:", 34, "Role:", 28));
children.push(twoFields("Phone:", 24, "Email:", 40));
children.push(field("Decision-maker (if different):", 56));
children.push(field("Billing contact & email:", 60));
children.push(twoFields("No. of branches / depots:", 12, "Head-office location:", 30));

// 2. Fleet Profile
children.push(sectionBar(2, "Fleet Profile"));
children.push(note("One row per vehicle group. Tank size + CAN/OBD availability drive hardware selection and unit cost."));
{
  const cols = [820, 1700, 1900, 760, 1206, 1100, 1130, 1130];
  const headers = ["Qty", "Vehicle type", "Make / Model", "Year", "Fuel type", "Tank (L)", "CAN bus? Y/N", "OBD port? Y/N"];
  const body = Array.from({ length: 6 }, () => Array(8).fill(""));
  children.push(table(cols, headers, body));
}
children.push(note("Vehicle types: truck / rigid / van / bakkie / sedan / trailer / reefer / yellow-metal."));

// 3. Operational Context
children.push(sectionBar(3, "Operational Context"));
children.push(field("Operating provinces / regions:", 56));
children.push(checks("Route profile:", ["Local / urban", "Long-haul", "Cross-border (roaming needed)"]));
children.push(field("Depots & yards (locations):", 56));
children.push(twoFields("Hours of operation:", 30, "Shift pattern:", 26));

// 4. Objectives & Pain Points
children.push(sectionBar(4, "Objectives & Pain Points"));
children.push(note("Rank the client's priorities 1 (highest) to 5. Leave blank if not relevant."));
{
  const cols = [7300, 2446];
  const headers = ["Objective", "Priority (1–5)"];
  const items = ["Stop / reduce fuel theft", "Asset visibility & recovery", "Driver safety & behaviour",
    "Compliance (licence / PDP expiry)", "Utilisation & idle-cost reduction", "Customer ETAs / delivery proof",
    "Insurance premium reduction"];
  children.push(table(cols, headers, items.map(i => [i, ""])));
}
children.push(field("Other objectives:", 60));

// 5. Feature Requirements
children.push(sectionBar(5, "Feature Requirements"));
children.push(note("Mark each myTrack feature as Must-have, Nice-to-have, or Not needed."));
{
  const cols = [4946, 1600, 1600, 1600];
  const headers = ["Feature", "Must-have", "Nice-to-have", "Not needed"];
  const feats = ["Live GPS tracking", "Fuel theft detection", "Driver behaviour scoring",
    "Speed limit enforcement", "Compliance alerts (licence / PDP)", "Fuel consumption reports",
    "WhatsApp driver notifications", "Geofencing", "Multi-depot / multi-branch",
    "Delivery / customer tracking share", "Idle & fleet-cost reporting", "Geofence dwell-time reporting"];
  children.push(table(cols, headers, feats.map(fn => [fn, "☐", "☐", "☐"])));
}

// 6. Hardware Requirements
children.push(sectionBar(6, "Hardware Requirements"));
children.push(note("Per vehicle group. Base unit is the Teltonika FMB tracker. Data source: CAN adapter (LV-CAN200) preferred, OBD plug for light vehicles, LLS fuel probe as fallback."));
{
  const cols = [2100, 2100, 3146, 2400];
  const headers = ["Vehicle group", "Data source (CAN/OBD/Probe)", "Accessories required", "Qty"];
  const body = Array.from({ length: 5 }, () => Array(4).fill(""));
  children.push(table(cols, headers, body));
}
children.push(checks("Accessory key:", ["Panic button", "Immobiliser / cut-off", "RFID / iButton ID", "Temp sensor (reefer)", "Backup battery"]));

// 7. Installation Logistics
children.push(sectionBar(7, "Installation Logistics"));
children.push(checks("Install location:", ["At depot (single site)", "Multiple sites", "Mobile / on-site"]));
children.push(twoFields("No. of sites:", 10, "Furthest site distance (km):", 16));
children.push(field("Vehicle downtime windows available:", 48));
children.push(checks("Certified auto-electrician required on-site?", ["Yes", "No"]));
children.push(field("Scheduling notes / constraints:", 54));

// 8. Connectivity & Data
children.push(sectionBar(8, "Connectivity & Data"));
children.push(checks("SIM / data supplied by:", ["myTrack", "Client"]));
children.push(field("Network coverage concerns in operating area:", 44));
children.push(checks("Cross-border roaming required?", ["Yes", "No"]));

// 9. Integration & Reporting
children.push(sectionBar(9, "Integration & Reporting"));
children.push(field("Existing systems (ERP / fuel cards / accounting):", 42));
children.push(checks("API / integration needed?", ["Yes", "No"]));
children.push(twoFields("No. of platform users / logins:", 12, "Report cadence:", 24));
children.push(checks("White-label / client branding required?", ["Yes", "No"]));

// 10. Compliance & Data Governance
children.push(sectionBar(10, "Compliance & Data Governance"));
children.push(checks("POPIA consent process in place for driver tracking?", ["Yes", "No", "Needs guidance"]));
children.push(twoFields("Required data-retention period:", 24, "Data owner:", 24));

// 11. Commercial
children.push(sectionBar(11, "Commercial"));
children.push(field("Budget range / expectation:", 50));
children.push(checks("Preferred contract term:", ["12 months", "24 months", "36 months"]));
children.push(checks("Hardware billing preference:", ["Upfront (once-off)", "Amortised into monthly"]));
children.push(twoFields("Payment terms:", 26, "Billing entity:", 28));

// 12. Service & Support
children.push(sectionBar(12, "Service & Support"));
children.push(field("SLA / response-time expectations:", 46));
children.push(checks("Training required?", ["Yes – on-site", "Yes – remote", "No"]));
children.push(field("Support hours expected:", 52));

// 13. Sign-off
children.push(sectionBar(13, "Sign-off"));
children.push(spacer());
children.push(twoFields("myTrack assessor:", 30, "Date:", 22));
children.push(spacer());
children.push(twoFields("Client name & signature:", 34, "Date:", 22));
children.push(note("Information gathered is used to prepare an indicative subscription proposal (once-off install, initiation fee, monthly per-unit cost). Pricing subject to site survey. E&OE."));

// ---- assemble --------------------------------------------------------------
const doc = new Document({
  creator: "myTrack (MyReach)",
  title: "myTrack Business Needs Assessment",
  styles: { default: { document: { run: { font: FONT, size: 20, color: INK } } } },
  sections: [{
    properties: { page: {
      size: { width: 11906, height: 16838 },
      margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } } },
    headers: { default: new Header({ children: [new Paragraph({
      alignment: AlignmentType.RIGHT,
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: CYAN, space: 2 } },
      children: [new TextRun({ text: "myTrack  ", bold: true, color: PURPLE, size: 18, font: FONT }),
                 new TextRun({ text: "Business Needs Assessment", color: GREY, size: 16, font: FONT })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "myTrack — a MyReach product   |   Confidential   |   Page ", color: GREY, size: 14, font: FONT }),
                 new TextRun({ children: [PageNumber.CURRENT], color: GREY, size: 14, font: FONT })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync("myTrack_Needs_Assessment.docx", buf); console.log("saved"); });
