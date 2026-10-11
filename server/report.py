"""
Lead report PDF for sharing with the HP team after the show.

AES-256 encrypted with BTG_EXPORT_PASSWORD, so a forwarded or misplaced copy
exposes nothing. HP brand styling: Arial-metric type (Liberation Sans,
bundled), white page, flat #D1DDF1 blocks, #004BDF labels, no borders.
Staff/demo players are excluded.
"""

import json
import secrets
import time
from collections import Counter
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import EncryptionMethod, XPos, YPos
from fpdf.fonts import FontFace

from . import db, missions as M

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "app/assets/fonts"
CJK_FALLBACK = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")

ACCENT = (0x00, 0x4B, 0xDF)
BLOCK = (0xD1, 0xDD, 0xF1)
INK = (0, 0, 0)
MUTED = (70, 70, 70)

OFFER_LABELS = {"specialist": "Z specialist meeting", "pilot": "30-day pilot",
                "workshop": "Governance workshop"}
OFFER_ORDER = ["specialist", "pilot", "workshop"]


def _local(ts):
    return time.strftime("%b %d, %Y %H:%M", time.localtime(ts)) if ts else ""


def _day(ts):
    return time.strftime("%a %b %d", time.localtime(ts))


class Report(FPDF):
    def __init__(self, generated):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.generated = generated
        self.set_margins(18, 20, 18)
        self.set_auto_page_break(True, margin=18)
        self.add_font("Sans", "", str(FONTS / "LiberationSans-Regular.ttf"))
        self.add_font("Sans", "B", str(FONTS / "LiberationSans-Bold.ttf"))
        fallbacks = []
        if CJK_FALLBACK.exists():
            try:
                self.add_font("CJK", "", str(CJK_FALLBACK))
                fallbacks.append("CJK")
            except Exception:  # noqa: BLE001
                pass
        if fallbacks:
            self.set_fallback_fonts(fallbacks)

    def header(self):
        self.set_font("Sans", "B", 7.5)
        self.set_text_color(*ACCENT)
        self.set_char_spacing(1.2)
        self.cell(0, 5, "BEAT THE GUARD · EDUCAUSE ANNUAL 2026 · CONFIDENTIAL: "
                        "ATTENDEE CONTACT DATA", new_x=XPos.LMARGIN,
                  new_y=YPos.NEXT)
        self.set_char_spacing(0)
        self.ln(3)

    def footer(self):
        self.set_y(-12)
        self.set_font("Sans", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}} · Generated "
                        f"{self.generated} on the HP ZGX Nano · HP internal. "
                        f"Handle per HP lead policy.", align="C")

    # building blocks -------------------------------------------------------
    def label(self, text):
        self.set_font("Sans", "B", 8)
        self.set_text_color(*ACCENT)
        self.set_char_spacing(1.2)
        self.cell(0, 6, text.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_char_spacing(0)
        self.set_text_color(*INK)

    def kpis(self, items, per_row=4):
        gap, h = 4, 22
        w = (self.epw - gap * (per_row - 1)) / per_row
        top = self.get_y()
        for i, (big, small) in enumerate(items):
            x = self.l_margin + (i % per_row) * (w + gap)
            y = top + (i // per_row) * (h + gap)
            self.set_fill_color(*BLOCK)
            self.rect(x, y, w, h, style="F")
            self.set_xy(x + 4, y + 3)
            self.set_font("Sans", "B", 6.5)
            self.set_text_color(*ACCENT)
            self.set_char_spacing(0.8)
            self.cell(w - 8, 4, small.upper())
            self.set_char_spacing(0)
            self.set_xy(x + 4, y + 9)
            self.set_font("Sans", "B", 18)
            self.set_text_color(*INK)
            self.cell(w - 8, 10, str(big))
        rows = (len(items) + per_row - 1) // per_row
        self.set_xy(self.l_margin, top + rows * (h + gap) + 4)

    def table(self, headings, rows, widths, font_size=9):
        self.set_font("Sans", "", font_size)
        self.set_fill_color(255, 255, 255)   # alternate rows: block / white
        head = FontFace(emphasis="BOLD", color=ACCENT, fill_color=(255, 255, 255))
        with super().table(col_widths=widths, borders_layout="NONE",
                           cell_fill_color=BLOCK, cell_fill_mode="ROWS",
                           headings_style=head, line_height=font_size * 0.55,
                           padding=1.6, text_align="LEFT") as t:
            r = t.row()
            for h in headings:
                r.cell(h.upper())
            for row in rows:
                r = t.row()
                for v in row:
                    r.cell("" if v is None else str(v))
        self.ln(4)


def build(password):
    """Returns the encrypted PDF as bytes."""
    now = time.time()
    players = db.q("SELECT * FROM players ORDER BY created_at")
    real = [p for p in players if not p["demo"]]
    demo_n = len(players) - len(real)
    leads = [p for p in real if p["consent"]]
    for p in leads:
        p["_interests"] = [i for i in json.loads(p["interests"] or "[]")
                           if i in OFFER_LABELS]
    stats = db.q(
        "SELECT COUNT(*) AS attempts, SUM(a.decision!='YES') AS blocked, "
        "AVG(a.t_decision_ms) AS ms, SUM(a.is_gap) AS gaps FROM attempts a "
        "JOIN players p ON p.id=a.player_id WHERE a.decision IS NOT NULL "
        "AND p.demo=0", one=True)
    games = db.q("SELECT COUNT(*) AS n FROM games g JOIN players p ON "
                 "p.id=g.player_id WHERE g.status!='active' AND p.demo=0",
                 one=True)["n"]
    gaps = db.q("SELECT a.created_at, a.mission_id, a.text, p.initials FROM "
                "attempts a JOIN players p ON p.id=a.player_id WHERE "
                "a.is_gap=1 AND p.demo=0 ORDER BY a.created_at")

    pdf = Report(time.strftime("%b %d, %Y %H:%M", time.localtime(now)))
    pdf.alias_nb_pages()
    pdf.set_title("Beat the Guard: lead report")
    pdf.set_author("HP ZGX Nano booth, EDUCAUSE Annual 2026")

    # --- summary -------------------------------------------------------------
    pdf.add_page()
    pdf.set_font("Sans", "B", 26)
    pdf.cell(0, 12, "Lead report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Sans", "", 11)
    pdf.set_text_color(*MUTED)
    span = (f"{_local(real[0]['created_at'])} to {_local(real[-1]['created_at'])}"
            if real else "No players yet")
    pdf.multi_cell(0, 6, f"Beat the Guard, EDUCAUSE Annual 2026, Denver. {span}.",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.ln(4)

    interest = Counter(i for p in leads for i in p["_interests"])
    attempts = stats["attempts"] or 0
    pdf.kpis([
        (len(leads), "Consented leads"),
        (interest.get("specialist", 0), "Want Z specialist"),
        (interest.get("pilot", 0), "Want 30-day pilot"),
        (interest.get("workshop", 0), "Want workshop"),
        (len(real), "Players"),
        (games, "Games played"),
        (f"{100 * (stats['blocked'] or 0) / attempts:.0f}%" if attempts else "–",
         "Attempts blocked"),
        (stats["gaps"] or 0, "Gaps found"),
    ])

    pdf.label("By role")
    roles = Counter(p["role"] or "Not given" for p in real)
    lead_roles = Counter(p["role"] or "Not given" for p in leads)
    pdf.table(["Role", "Players", "Consented leads"],
              [(r, n, lead_roles.get(r, 0)) for r, n in roles.most_common()],
              (90, 40, 50))

    pdf.label("By day")
    days, lead_days = Counter(), Counter()
    for p in real:
        days[_day(p["created_at"])] += 1
    for p in leads:
        lead_days[_day(p["created_at"])] += 1
    pdf.table(["Day", "Players", "Consented leads"],
              [(d, n, lead_days.get(d, 0)) for d, n in days.items()],
              (90, 40, 50))

    pdf.set_font("Sans", "", 8.5)
    pdf.set_text_color(*MUTED)
    avg_ms = f"{stats['ms']:.0f} ms" if stats["ms"] else "–"
    pdf.multi_cell(0, 4.5,
        "Contact details were collected only from attendees who ticked the "
        "consent box. Everyone else appears in the counts only (initials and "
        f"role). {demo_n} staff/demo test player(s) excluded. Average guard "
        f"decision time: {avg_ms}, processed on-device with no internet "
        "connection. All game scenarios used synthetic data.",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)

    # --- leads ---------------------------------------------------------------
    pdf.add_page(orientation="L")
    pdf.set_font("Sans", "B", 18)
    pdf.cell(0, 10, f"Consented leads ({len(leads)})", new_x=XPos.LMARGIN,
             new_y=YPos.NEXT)
    pdf.set_font("Sans", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "Sorted by requested follow-up (Z specialist, pilot, "
                   "workshop), then by time.", new_x=XPos.LMARGIN,
             new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.ln(3)

    def rank(p):
        ranks = [OFFER_ORDER.index(i) for i in p["_interests"]] or [9]
        return (min(ranks), p["created_at"])

    rows = [(n, p["name"] or "", p["email"] or "", p["institution"] or "",
             p["role"] or "", ", ".join(OFFER_LABELS[i] for i in OFFER_ORDER
                                        if i in p["_interests"]) or "None chosen",
             _local(p["created_at"]))
            for n, p in enumerate(sorted(leads, key=rank), 1)]
    if rows:
        pdf.table(["#", "Name", "Email", "Institution", "Role", "Wants",
                   "When"], rows, (8, 38, 58, 50, 30, 42, 30), font_size=8.5)
    else:
        pdf.cell(0, 8, "No consented leads yet.")

    # --- gaps ----------------------------------------------------------------
    pdf.add_page(orientation="P")
    pdf.set_font("Sans", "B", 18)
    pdf.cell(0, 10, f"Logged gaps ({len(gaps)})", new_x=XPos.LMARGIN,
             new_y=YPos.NEXT)
    pdf.set_font("Sans", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4.5,
        "Requests that got a YES from the guard on a mission that should be "
        "blocked: red-team findings for review. Each one relied on a claim in "
        "the request that no system of record verified. Text is as typed by "
        "attendees (initials only).", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.ln(3)
    titles = {mid: m["title"] for mid, m in M.load().items()}
    if gaps:
        pdf.table(["When", "Player", "Mission", "Request"],
                  [(_local(g["created_at"]), g["initials"],
                    titles.get(g["mission_id"], g["mission_id"]),
                    g["text"]) for g in gaps],
                  (30, 19, 36, 95), font_size=8.5)
    else:
        pdf.cell(0, 8, "No gaps logged.")

    pdf.set_encryption(owner_password=secrets.token_urlsafe(24),
                       user_password=password,
                       encryption_method=EncryptionMethod.AES_256)
    return bytes(pdf.output())
