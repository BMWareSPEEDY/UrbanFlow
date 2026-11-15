"""
UrbanFLOW Pristine 16:9 Presentation Deck Generator
Generates clean, spacious, beautifully formatted slides with ZERO broken UI or text overflow.
Slide 0: Minimalist Title Slide (Project Name, Basic Info, Ashish Paliwal)
Slides 1-5: Empirical Hydrodynamic Research Slides matching Botanical Ceramic Console
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE

# --- Color Constants (Botanical Ceramic Municipal Console) ---
CANVAS_BG = RGBColor(243, 246, 241)        # #F3F6F1 Ceramic Off-White
CARD_BG = RGBColor(255, 255, 255)          # #FFFFFF Pure White Card
CARD_BORDER = RGBColor(202, 215, 199)      # #CAD7C7 Sage/Celadon outline
CARD_MUTED_BG = RGBColor(235, 245, 234)    # #EBF5EA Pale Celadon Tint
AMBER_TINT = RGBColor(253, 244, 229)       # #FDF4E5 Natural Amber Light
HAZARD_TINT = RGBColor(253, 239, 236)      # #FDEFEC Terracotta Hazard Light
CODE_BG = RGBColor(240, 244, 239)          # #F0F4EF

PINE_FOREST = RGBColor(35, 62, 43)         # #233E2B Deep Pine Forest (Primary Text)
PINE_DARK = RGBColor(25, 43, 29)           # #192D1F
LEAF_GREEN = RGBColor(46, 125, 50)         # #2E7D32 Leaf Green
LEAF_LIGHT = RGBColor(67, 160, 71)         # #43A047
NATURAL_AMBER = RGBColor(201, 114, 24)     # #C97218 Natural Amber
HAZARD_TERRACOTTA = RGBColor(186, 60, 35)  # #BA3C23 Terracotta Hazard Alert
TEXT_MUTED = RGBColor(100, 119, 104)       # #647768 Olive Muted
TEXT_SECONDARY = RGBColor(63, 82, 67)      # #3F5243 Dark Sage

FONT_SANS = "Calibri"  # Universally supported on PowerPoint & Google Slides
FONT_MONO = "Consolas" # Universally supported monospaced font

def init_presentation():
    prs = Presentation()
    # 16:9 standard widescreen: 13.333" x 7.5"
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs

def set_slide_background(slide):
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5))
    bg.fill.solid()
    bg.fill.fore_color.rgb = CANVAS_BG
    bg.line.fill.background()
    return bg

def add_header(slide, title, subtitle, category_str, slide_idx_str):
    # Category tag / Pill
    pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.35), Inches(5.2), Inches(0.28))
    pill.fill.solid()
    pill.fill.fore_color.rgb = CARD_MUTED_BG
    pill.line.color.rgb = CARD_BORDER
    pill.line.width = Pt(0.75)
    tf_p = pill.text_frame
    tf_p.word_wrap = False
    tf_p.margin_left = Inches(0.12)
    tf_p.margin_top = Inches(0.02)
    tf_p.margin_right = Inches(0.12)
    tf_p.margin_bottom = Inches(0.02)
    p0 = tf_p.paragraphs[0]
    p0.text = category_str.upper()
    p0.font.name = FONT_MONO
    p0.font.size = Pt(8.5)
    p0.font.bold = True
    p0.font.color.rgb = LEAF_GREEN

    # Slide index indicator badge on top right
    idx_box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(11.533), Inches(0.35), Inches(1.0), Inches(0.28))
    idx_box.fill.solid()
    idx_box.fill.fore_color.rgb = PINE_FOREST
    idx_box.line.fill.background()
    tf_i = idx_box.text_frame
    tf_i.margin_top = Inches(0.02)
    tf_i.margin_bottom = Inches(0.02)
    pi = tf_i.paragraphs[0]
    pi.alignment = PP_ALIGN.CENTER
    pi.text = slide_idx_str
    pi.font.name = FONT_MONO
    pi.font.size = Pt(9)
    pi.font.bold = True
    pi.font.color.rgb = RGBColor(255, 255, 255)

    # Main Title
    tb_title = slide.shapes.add_textbox(Inches(0.8), Inches(0.66), Inches(11.733), Inches(0.42))
    tf_t = tb_title.text_frame
    tf_t.word_wrap = True
    tf_t.margin_left = Inches(0)
    tf_t.margin_top = Inches(0)
    tf_t.margin_right = Inches(0)
    tf_t.margin_bottom = Inches(0)
    pt = tf_t.paragraphs[0]
    pt.text = title
    pt.font.name = FONT_SANS
    pt.font.size = Pt(20)
    pt.font.bold = True
    pt.font.color.rgb = PINE_FOREST

    # Subtitle
    tb_sub = slide.shapes.add_textbox(Inches(0.8), Inches(1.10), Inches(11.733), Inches(0.30))
    tf_s = tb_sub.text_frame
    tf_s.word_wrap = True
    tf_s.margin_left = Inches(0)
    tf_s.margin_top = Inches(0)
    tf_s.margin_right = Inches(0)
    tf_s.margin_bottom = Inches(0)
    ps = tf_s.paragraphs[0]
    ps.text = subtitle
    ps.font.name = FONT_SANS
    ps.font.size = Pt(11)
    ps.font.color.rgb = TEXT_SECONDARY

def add_card(slide, left, top, width, height, fill_color=CARD_BG, border_color=CARD_BORDER, border_width=1.0):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = fill_color
    if border_color:
        card.line.color.rgb = border_color
        card.line.width = Pt(border_width)
    else:
        card.line.fill.background()
    return card

def add_bottom_banner(slide, label, text, left=Inches(0.8), top=Inches(6.45), width=Inches(11.733), height=Inches(0.65)):
    card = add_card(slide, left, top, width, height, fill_color=CARD_MUTED_BG, border_color=LEAF_GREEN, border_width=1.2)
    tb = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.08), width - Inches(0.4), height - Inches(0.16))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_top = Inches(0)
    p = tf.paragraphs[0]
    
    r_label = p.add_run()
    r_label.text = label + ": "
    r_label.font.name = FONT_SANS
    r_label.font.bold = True
    r_label.font.size = Pt(10.5)
    r_label.font.color.rgb = LEAF_GREEN
    
    r_text = p.add_run()
    r_text.text = text
    r_text.font.name = FONT_SANS
    r_text.font.size = Pt(10.5)
    r_text.font.color.rgb = PINE_FOREST

# ==============================================================================
# SLIDE 0: TITLE SLIDE (CLEAN & MINIMALIST AS REQUESTED)
# ==============================================================================
def build_slide_0(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)

    # Main Center Card
    card_w = Inches(11.733)
    card_h = Inches(5.9)
    card_x = Inches(0.8)
    card_y = Inches(0.8)
    add_card(slide, card_x, card_y, card_w, card_h, fill_color=CARD_BG, border_color=CARD_BORDER, border_width=1.5)

    # Subtle top accent bar inside card
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, card_x, card_y, card_w, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = LEAF_GREEN
    bar.line.fill.background()

    # Content Container
    tb = slide.shapes.add_textbox(card_x + Inches(0.8), card_y + Inches(0.6), card_w - Inches(1.6), card_h - Inches(1.0))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_bottom = Inches(0)

    # Category Pill Text
    p0 = tf.paragraphs[0]
    p0.space_after = Pt(20)
    r_cat = p0.add_run()
    r_cat.text = "EARTH & ENVIRONMENTAL SCIENCES  •  PHYSICS-GUIDED DEEP LEARNING"
    r_cat.font.name = FONT_MONO
    r_cat.font.size = Pt(11)
    r_cat.font.bold = True
    r_cat.font.color.rgb = LEAF_GREEN

    # Project Title
    p1 = tf.add_paragraph()
    p1.space_after = Pt(8)
    r_title = p1.add_run()
    r_title.text = "UrbanFLOW"
    r_title.font.name = FONT_SANS
    r_title.font.size = Pt(50)
    r_title.font.bold = True
    r_title.font.color.rgb = PINE_FOREST

    # Project Subtitle
    p2 = tf.add_paragraph()
    p2.space_after = Pt(8)
    r_sub = p2.add_run()
    r_sub.text = "Autonomous Hydrodynamic GNN Early Warning Twin"
    r_sub.font.name = FONT_SANS
    r_sub.font.size = Pt(21)
    r_sub.font.bold = True
    r_sub.font.color.rgb = LEAF_GREEN

    # Problem Statement / Tagline
    p3 = tf.add_paragraph()
    p3.space_after = Pt(40)
    r_tag = p3.add_run()
    r_tag.text = "Real-Time Junction-Scale Inundation Surrogate vs. Numerical Stability Bottlenecks"
    r_tag.font.name = FONT_SANS
    r_tag.font.size = Pt(14)
    r_tag.font.italic = True
    r_tag.font.color.rgb = TEXT_SECONDARY

    # Divider line
    div = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, card_x + Inches(0.8), card_y + Inches(3.6), Inches(4.5), Pt(1.5))
    div.fill.solid()
    div.fill.fore_color.rgb = CARD_BORDER
    div.line.fill.background()

    # Author Name Box
    tb_author = slide.shapes.add_textbox(card_x + Inches(0.8), card_y + Inches(3.85), Inches(9.0), Inches(1.4))
    tf_a = tb_author.text_frame
    tf_a.word_wrap = True
    tf_a.margin_left = Inches(0)
    tf_a.margin_top = Inches(0)

    pa0 = tf_a.paragraphs[0]
    pa0.space_after = Pt(4)
    r_auth = pa0.add_run()
    r_auth.text = "Ashish Paliwal"
    r_auth.font.name = FONT_SANS
    r_auth.font.size = Pt(22)
    r_auth.font.bold = True
    r_auth.font.color.rgb = PINE_FOREST

    pa1 = tf_a.add_paragraph()
    pa1.space_after = Pt(4)
    r_inst = pa1.add_run()
    r_inst.text = "IRIS National Fair 2026–27  |  ISEF-Affiliated Research Submission"
    r_inst.font.name = FONT_SANS
    r_inst.font.size = Pt(13)
    r_inst.font.color.rgb = TEXT_MUTED

# ==============================================================================
# SLIDE 1: Title & The Numerical Hydrodynamic Crisis
# ==============================================================================
def build_slide_1(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)

    add_header(
        slide,
        title="UrbanFLOW | Autonomous Hydrodynamic GNN Early Warning Twin",
        subtitle="Real-Time Junction-Scale Inundation Surrogate vs. Numerical Stability Bottlenecks",
        category_str="IRIS National Fair 2026–27 | Earth & Environmental Sciences",
        slide_idx_str="01 / 05"
    )

    card_top = Inches(1.52)
    card_w = Inches(5.72)
    card_h = Inches(4.75)

    # --- Card A: Drainage Crisis ---
    left_a = Inches(0.8)
    add_card(slide, left_a, card_top, card_w, card_h, border_color=CARD_BORDER)
    
    # Card Header
    hdr_box_a = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_a, card_top, card_w, Inches(0.48))
    hdr_box_a.fill.solid()
    hdr_box_a.fill.fore_color.rgb = HAZARD_TINT
    hdr_box_a.line.color.rgb = CARD_BORDER
    hdr_box_a.line.width = Pt(0.75)
    tf_ha = hdr_box_a.text_frame
    tf_ha.margin_left = Inches(0.18)
    tf_ha.margin_top = Inches(0.08)
    pha = tf_ha.paragraphs[0]
    pha.text = "Card A: The Convective Cloudburst Drainage Crisis"
    pha.font.name = FONT_SANS
    pha.font.size = Pt(12.5)
    pha.font.bold = True
    pha.font.color.rgb = HAZARD_TERRACOTTA

    # Card A Bullets
    tb_a = slide.shapes.add_textbox(left_a + Inches(0.22), card_top + Inches(0.58), card_w - Inches(0.44), card_h - Inches(0.68))
    tf_ca = tb_a.text_frame
    tf_ca.word_wrap = True
    tf_ca.margin_left = Inches(0)
    tf_ca.margin_top = Inches(0)

    bullets_a = [
        ("Severe Storm Rates: ", "Extreme convective cloudbursts exceeding 50–100 mm/hr overwhelm curb inlets within minutes of onset."),
        ("Basin Runoff Amplification: ", "Expanding urban asphalt and concrete surfaces reduce infiltration and magnify peak surface runoff by up to 400%."),
        ("Topological Traps: ", "Depressed underpasses and sunken highway bottlenecks become hazardous submergence zones before conventional alerts issue."),
        ("Extreme Zero-Inflation: ", "80.9% of urban road nodes remain completely dry during storms (<0.15 m), causing naive deep neural networks to suffer gradient collapse and smooth away high-risk flood peaks.")
    ]

    for i, (b_title, b_desc) in enumerate(bullets_a):
        p = tf_ca.paragraphs[0] if i == 0 else tf_ca.add_paragraph()
        p.space_after = Pt(12)
        r_bullet = p.add_run()
        r_bullet.text = "• "
        r_bullet.font.bold = True
        r_bullet.font.color.rgb = HAZARD_TERRACOTTA
        
        r_b_title = p.add_run()
        r_b_title.text = b_title
        r_b_title.font.name = FONT_SANS
        r_b_title.font.bold = True
        r_b_title.font.size = Pt(10)
        r_b_title.font.color.rgb = PINE_FOREST

        r_b_desc = p.add_run()
        r_b_desc.text = b_desc
        r_b_desc.font.name = FONT_SANS
        r_b_desc.font.size = Pt(10)
        r_b_desc.font.color.rgb = TEXT_SECONDARY

    # --- Card B: Numerical Solver Bottleneck ---
    left_b = Inches(6.81)
    add_card(slide, left_b, card_top, card_w, card_h, border_color=CARD_BORDER)

    hdr_box_b = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_b, card_top, card_w, Inches(0.48))
    hdr_box_b.fill.solid()
    hdr_box_b.fill.fore_color.rgb = AMBER_TINT
    hdr_box_b.line.color.rgb = CARD_BORDER
    hdr_box_b.line.width = Pt(0.75)
    tf_hb = hdr_box_b.text_frame
    tf_hb.margin_left = Inches(0.18)
    tf_hb.margin_top = Inches(0.08)
    phb = tf_hb.paragraphs[0]
    phb.text = "Card B: The Numerical Solver Bottleneck (EPA SWMM 5.2)"
    phb.font.name = FONT_SANS
    phb.font.size = Pt(12.5)
    phb.font.bold = True
    phb.font.color.rgb = NATURAL_AMBER

    # Card B Bullets
    tb_b = slide.shapes.add_textbox(left_b + Inches(0.22), card_top + Inches(0.58), card_w - Inches(0.44), card_h - Inches(0.68))
    tf_cb = tb_b.text_frame
    tf_cb.word_wrap = True
    tf_cb.margin_left = Inches(0)
    tf_cb.margin_top = Inches(0)

    # Bullet 1
    p1 = tf_cb.paragraphs[0]
    p1.space_after = Pt(8)
    r1_b = p1.add_run()
    r1_b.text = "• "
    r1_b.font.bold = True
    r1_b.font.color.rgb = NATURAL_AMBER
    r1_t = p1.add_run()
    r1_t.text = "Governing Equations: "
    r1_t.font.name = FONT_SANS
    r1_t.font.bold = True
    r1_t.font.size = Pt(10)
    r1_t.font.color.rgb = PINE_FOREST
    r1_d = p1.add_run()
    r1_d.text = "Solves the 1D/2D Saint-Venant shallow water equations for mass and momentum conservation."
    r1_d.font.name = FONT_SANS
    r1_d.font.size = Pt(10)
    r1_d.font.color.rgb = TEXT_SECONDARY

    # Bullet 2: CFL Condition
    p2 = tf_cb.add_paragraph()
    p2.space_after = Pt(4)
    r2_b = p2.add_run()
    r2_b.text = "• "
    r2_b.font.bold = True
    r2_b.font.color.rgb = NATURAL_AMBER
    r2_t = p2.add_run()
    r2_t.text = "Courant-Friedrichs-Lewy (CFL) Condition:"
    r2_t.font.name = FONT_SANS
    r2_t.font.bold = True
    r2_t.font.size = Pt(10)
    r2_t.font.color.rgb = PINE_FOREST

    # Equation Callout Box
    eq_card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left_b + Inches(0.22), card_top + Inches(1.72), card_w - Inches(0.44), Inches(0.46))
    eq_card.fill.solid()
    eq_card.fill.fore_color.rgb = CODE_BG
    eq_card.line.color.rgb = CARD_BORDER
    eq_card.line.width = Pt(0.75)
    tf_eq = eq_card.text_frame
    tf_eq.margin_left = Inches(0.12)
    tf_eq.margin_top = Inches(0.06)
    peq = tf_eq.paragraphs[0]
    peq.alignment = PP_ALIGN.CENTER
    peq.text = "dt <= min( L_e / [ |v_e| + sqrt(g * A_e / B_e) ] )"
    peq.font.name = FONT_MONO
    peq.font.size = Pt(9.5)
    peq.font.bold = True
    peq.font.color.rgb = PINE_FOREST

    # Bullet 3 & 4 (Lower text box to avoid overlap)
    tb_b2 = slide.shapes.add_textbox(left_b + Inches(0.22), card_top + Inches(2.28), card_w - Inches(0.44), card_h - Inches(2.38))
    tf_cb2 = tb_b2.text_frame
    tf_cb2.word_wrap = True
    tf_cb2.margin_left = Inches(0)
    tf_cb2.margin_top = Inches(0)

    p3 = tf_cb2.paragraphs[0]
    p3.space_after = Pt(12)
    r3_b = p3.add_run()
    r3_b.text = "• "
    r3_b.font.bold = True
    r3_b.font.color.rgb = NATURAL_AMBER
    r3_t = p3.add_run()
    r3_t.text = "Sub-Second Stepping: "
    r3_t.font.name = FONT_SANS
    r3_t.font.bold = True
    r3_t.font.size = Pt(10)
    r3_t.font.color.rgb = PINE_FOREST
    r3_d = p3.add_run()
    r3_d.text = "Dense urban street graphs with short pipe segments (L_e < 10 m) force numerical stability time-steps under 0.5 seconds."
    r3_d.font.name = FONT_SANS
    r3_d.font.size = Pt(10)
    r3_d.font.color.rgb = TEXT_SECONDARY

    p4 = tf_cb2.add_paragraph()
    r4_b = p4.add_run()
    r4_b.text = "• "
    r4_b.font.bold = True
    r4_b.font.color.rgb = NATURAL_AMBER
    r4_t = p4.add_run()
    r4_t.text = "Operational Simulation Gap: "
    r4_t.font.name = FONT_SANS
    r4_t.font.bold = True
    r4_t.font.size = Pt(10)
    r4_t.font.color.rgb = PINE_FOREST
    r4_d = p4.add_run()
    r4_d.text = "Simulating 60 minutes of storm runoff across 3,000 to 13,000 nodes requires 15 to 45 minutes of CPU execution, rendering numerical solvers too slow for automated barrier closure or emergency pump dispatch."
    r4_d.font.name = FONT_SANS
    r4_d.font.size = Pt(10)
    r4_d.font.color.rgb = TEXT_SECONDARY

    # Bottom Banner
    add_bottom_banner(
        slide,
        label="Core Hypothesis",
        text="A graph neural operator can emulate shallow-water differential flow in sub-100 ms without physical divergence or mass continuity violations."
    )

# ==============================================================================
# SLIDE 2: Physics-Guided Architecture & Inductive Biases
# ==============================================================================
def build_slide_2(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)

    add_header(
        slide,
        title="UrbanFLOW | System Architecture & Inductive Biases",
        subtitle="6-Layer Edge-Conditioned HydroGINE-v5 with Decoupled FiLM Modulation",
        category_str="Physics-Guided Deep Learning Architecture",
        slide_idx_str="02 / 05"
    )

    card_top = Inches(1.52)
    card_w = Inches(3.72)
    card_h = Inches(4.75)
    gap = Inches(0.28)

    steps_data = [
        (
            "Step 1: Directed Topological Graph G = (V, E)",
            LEAF_GREEN,
            CARD_MUTED_BG,
            [
                ("Inputs: ", "Synthesizes 10 m Copernicus/SRTM DEM micro-topography with OpenStreetMap street centerlines into 76,316 nodes across 16 global catchments."),
                ("32-d Node Features: ", "Invert elevation, Kirpich time of concentration (Tc = 0.0195 * L^0.77 * S^-0.385), parabolic sag index, depression storage depth, impervious fraction, and dynamic rainfall volume (I * dt)."),
                ("6-d Edge Features: ", "Pipe length, longitudinal slope (S_0), carrying capacity, coordinate deltas, and directional gravity gate."),
                ("Geographic Generalization: ", "Explicitly omits raw latitude/longitude coordinates to enforce scale-invariant, zero-shot transfer.")
            ]
        ),
        (
            "Step 2: HydroGINE-v5 Operator",
            PINE_FOREST,
            CODE_BG,
            [
                ("6 GINE Layers: ", "1-WL topological expressiveness with multi-scale skip concatenation (h_cat in R^288)."),
                ("Directional Gravity Gating:\n", "g_gate,uv = sigma(1.0 - 5.0 * ReLU(S_0,uv))\nDownhill edges remain fully open (g ≈ 1.0); uphill message propagation is physically attenuated toward 0 to prevent uphill water flow."),
                ("Universal Physical Rails: ", "Non-differentiable 2.1 ms post-inference stack enforcing WSE backwater envelopes, mass bounds, and dry ridge clamping.")
            ]
        ),
        (
            "Step 3: Decoupled FiLM Dual-Head",
            NATURAL_AMBER,
            AMBER_TINT,
            [
                ("Head 1 (Margin Focal Classifier): ", "Isolates the discrete hazard threshold (>=0.15 m) across sparse wet nodes."),
                ("FiLM Modulation Generator: ", "Maps flood probability into affine transformation vectors [gamma, beta] in R^288."),
                ("Head 2 (Depth Regressor): ", "Modulates latent features to prevent depth bleeding onto dry elevated pavement."),
                ("Asymmetric Safety Loss (A_i): ", "Applies a 2.0x heavier penalty when under-predicting dangerous water depths to eliminate dangerous false negatives.")
            ]
        )
    ]

    for idx, (title, color, tint_bg, bullets) in enumerate(steps_data):
        c_left = Inches(0.8) + idx * (card_w + gap)
        add_card(slide, c_left, card_top, card_w, card_h, border_color=CARD_BORDER)

        # Step Header Pill
        hdr = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, c_left, card_top, card_w, Inches(0.48))
        hdr.fill.solid()
        hdr.fill.fore_color.rgb = tint_bg
        hdr.line.color.rgb = CARD_BORDER
        hdr.line.width = Pt(0.75)
        tf_h = hdr.text_frame
        tf_h.margin_left = Inches(0.14)
        tf_h.margin_top = Inches(0.08)
        ph = tf_h.paragraphs[0]
        ph.text = title
        ph.font.name = FONT_SANS
        ph.font.size = Pt(11)
        ph.font.bold = True
        ph.font.color.rgb = color

        # Bullets Container
        tb = slide.shapes.add_textbox(c_left + Inches(0.16), card_top + Inches(0.56), card_w - Inches(0.32), card_h - Inches(0.66))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0)
        tf.margin_top = Inches(0)

        for b_idx, (b_title, b_desc) in enumerate(bullets):
            p = tf.paragraphs[0] if b_idx == 0 else tf.add_paragraph()
            p.space_after = Pt(8)
            r_bullet = p.add_run()
            r_bullet.text = "• "
            r_bullet.font.bold = True
            r_bullet.font.color.rgb = color

            r_title = p.add_run()
            r_title.text = b_title
            r_title.font.name = FONT_SANS
            r_title.font.bold = True
            r_title.font.size = Pt(9.2)
            r_title.font.color.rgb = PINE_FOREST

            r_desc = p.add_run()
            r_desc.text = b_desc
            r_desc.font.name = FONT_SANS
            r_desc.font.size = Pt(9.2)
            r_desc.font.color.rgb = TEXT_SECONDARY

    # Bottom Callout
    add_bottom_banner(
        slide,
        label="Engineering Innovation",
        text="Decoupling flood probability from depth regression resolves zero-inflation collapse; non-destructive MoE routing preserves 100% of street conduit topology."
    )

# ==============================================================================
# SLIDE 3: Multi-Catchment Global Benchmark & Speedup
# ==============================================================================
def build_slide_3(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)

    add_header(
        slide,
        title="UrbanFLOW | Multi-Scale Global Benchmark & Computational Acceleration",
        subtitle="Empirical Evaluation Across 16 Basins (76,316 Nodes) Under Multi-Scale Storms",
        category_str="Empirical Validation & Computational Benchmarks",
        slide_idx_str="03 / 05"
    )

    # 4 Metric Badges on Top
    metrics = [
        ("Global MAE", "2.44 cm", "Dynamic-wave numerical parity < 5.0 cm", LEAF_GREEN),
        ("Catchment NSE", "0.9128", "Superior field fit; Flooded-only NSE: 0.8765", PINE_FOREST),
        ("Critical Hotspot Recall", "99.4%", "Top-480 highest-consequence nodes", NATURAL_AMBER),
        ("End-to-End API Latency", "85.5 ms", "~1,310x to 8,690x speedup vs. SWMM 5.2", HAZARD_TERRACOTTA)
    ]

    badge_w = Inches(2.78)
    badge_h = Inches(1.15)
    badge_gap = Inches(0.20)
    top_badge = Inches(1.50)

    for i, (label, val, sub, col) in enumerate(metrics):
        bx = Inches(0.8) + i * (badge_w + badge_gap)
        add_card(slide, bx, top_badge, badge_w, badge_h, border_color=CARD_BORDER)

        tb = slide.shapes.add_textbox(bx + Inches(0.14), top_badge + Inches(0.08), badge_w - Inches(0.28), badge_h - Inches(0.16))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0)
        tf.margin_top = Inches(0)

        # Label
        p0 = tf.paragraphs[0]
        r0 = p0.add_run()
        r0.text = label.upper()
        r0.font.name = FONT_MONO
        r0.font.size = Pt(8.5)
        r0.font.bold = True
        r0.font.color.rgb = TEXT_MUTED

        # Value
        p1 = tf.add_paragraph()
        r1 = p1.add_run()
        r1.text = val
        r1.font.name = FONT_SANS
        r1.font.size = Pt(21)
        r1.font.bold = True
        r1.font.color.rgb = col

        # Subtitle
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = sub
        r2.font.name = FONT_SANS
        r2.font.size = Pt(8)
        r2.font.color.rgb = TEXT_SECONDARY

    # 2 Analytical Cards Below
    bottom_card_top = Inches(2.82)
    bottom_card_h = Inches(4.35)
    bottom_card_w = Inches(5.72)

    # Card 1: Error Distribution & Hotspot Verification
    left_1 = Inches(0.8)
    add_card(slide, left_1, bottom_card_top, bottom_card_w, bottom_card_h)
    
    hdr1 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_1, bottom_card_top, bottom_card_w, Inches(0.44))
    hdr1.fill.solid()
    hdr1.fill.fore_color.rgb = CARD_MUTED_BG
    hdr1.line.color.rgb = CARD_BORDER
    hdr1.line.width = Pt(0.75)
    tf_h1 = hdr1.text_frame
    tf_h1.margin_left = Inches(0.18)
    tf_h1.margin_top = Inches(0.08)
    ph1 = tf_h1.paragraphs[0]
    ph1.text = "Card 1: Error Distribution & Hotspot Verification"
    ph1.font.name = FONT_SANS
    ph1.font.size = Pt(12)
    ph1.font.bold = True
    ph1.font.color.rgb = PINE_FOREST

    tb_c1 = slide.shapes.add_textbox(left_1 + Inches(0.2), bottom_card_top + Inches(0.54), bottom_card_w - Inches(0.4), bottom_card_h - Inches(0.64))
    tf_c1 = tb_c1.text_frame
    tf_c1.word_wrap = True
    tf_c1.margin_left = Inches(0)
    tf_c1.margin_top = Inches(0)

    bullets_c1 = [
        ("Comprehensive Tolerance: ", "94.2% of all nodes within +/- 10 cm, 96.7% within +/- 15 cm, and 98.9% within +/- 30 cm of SWMM 5.2 Dynamic Wave simulations."),
        ("Top-480 High-Consequence Hotspots (30 deepest per catchment):\n", "• 99.4% categorical hazard recall.\n• 100% of depth disagreements (124/480) are conservative under-predictions; zero dangerous over-prediction."),
        ("Mass Continuity Error: ", "Limited to 8.61% globally (comfortably within the 10.0% physical threshold)."),
        ("100 mm/hr Stress Test: ", "Flooded nodes expanded to 22,170 (29.1% of network); model sustained 98.8% hazard precision and 86.4% F1.")
    ]

    for idx, (b_title, b_desc) in enumerate(bullets_c1):
        p = tf_c1.paragraphs[0] if idx == 0 else tf_c1.add_paragraph()
        p.space_after = Pt(10)
        r_b = p.add_run()
        r_b.text = "• "
        r_b.font.bold = True
        r_b.font.color.rgb = LEAF_GREEN
        r_t = p.add_run()
        r_t.text = b_title
        r_t.font.name = FONT_SANS
        r_t.font.bold = True
        r_t.font.size = Pt(9.6)
        r_t.font.color.rgb = PINE_FOREST
        r_d = p.add_run()
        r_d.text = b_desc
        r_d.font.name = FONT_SANS
        r_d.font.size = Pt(9.6)
        r_d.font.color.rgb = TEXT_SECONDARY

    # Card 2: Runtime Acceleration vs. EPA SWMM 5.2
    left_2 = Inches(6.81)
    add_card(slide, left_2, bottom_card_top, bottom_card_w, bottom_card_h)

    hdr2 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_2, bottom_card_top, bottom_card_w, Inches(0.44))
    hdr2.fill.solid()
    hdr2.fill.fore_color.rgb = CODE_BG
    hdr2.line.color.rgb = CARD_BORDER
    hdr2.line.width = Pt(0.75)
    tf_h2 = hdr2.text_frame
    tf_h2.margin_left = Inches(0.18)
    tf_h2.margin_top = Inches(0.08)
    ph2 = tf_h2.paragraphs[0]
    ph2.text = "Card 2: Runtime Acceleration vs. EPA SWMM 5.2"
    ph2.font.name = FONT_SANS
    ph2.font.size = Pt(12)
    ph2.font.bold = True
    ph2.font.color.rgb = PINE_FOREST

    # Benchmark Speedup Rows inside Card 2
    tb_c2 = slide.shapes.add_textbox(left_2 + Inches(0.2), bottom_card_top + Inches(0.54), bottom_card_w - Inches(0.4), bottom_card_h - Inches(0.64))
    tf_c2 = tb_c2.text_frame
    tf_c2.word_wrap = True
    tf_c2.margin_left = Inches(0)
    tf_c2.margin_top = Inches(0)

    rows = [
        ("Small Catchment (HSR Layout, 1,379 nodes)", "SWMM: 42.1 s  |  UrbanFLOW API: 32.0 ms", "Speedup: ~1,310x", LEAF_GREEN),
        ("Medium Catchment (Electronic City, 3,337 nodes)", "SWMM: 228.0 s (3.8 min)  |  UrbanFLOW API: 54.6 ms", "Speedup: ~4,180x", NATURAL_AMBER),
        ("Large Catchment (Tokyo Metro, 13,173 nodes)", "SWMM: 1,476.0 s (24.6 min)  |  UrbanFLOW API: 169.8 ms", "Speedup: ~8,690x", HAZARD_TERRACOTTA),
    ]

    for idx, (basin, time_str, speedup, col) in enumerate(rows):
        p_t = tf_c2.paragraphs[0] if idx == 0 else tf_c2.add_paragraph()
        r_t = p_t.add_run()
        r_t.text = "• " + basin + "\n"
        r_t.font.name = FONT_SANS
        r_t.font.bold = True
        r_t.font.size = Pt(9.6)
        r_t.font.color.rgb = PINE_FOREST

        r_sub = p_t.add_run()
        r_sub.text = "  " + time_str + "  •  "
        r_sub.font.name = FONT_SANS
        r_sub.font.size = Pt(9.2)
        r_sub.font.color.rgb = TEXT_SECONDARY

        r_sp = p_t.add_run()
        r_sp.text = speedup + "\n"
        r_sp.font.name = FONT_MONO
        r_sp.font.bold = True
        r_sp.font.size = Pt(9.4)
        r_sp.font.color.rgb = col
        p_t.space_after = Pt(8)

    # Tensor Forward Pass note
    p_gpu = tf_c2.add_paragraph()
    r_gpu_b = p_gpu.add_run()
    r_gpu_b.text = "• Tensor Forward Pass: "
    r_gpu_b.font.name = FONT_SANS
    r_gpu_b.font.bold = True
    r_gpu_b.font.size = Pt(9.6)
    r_gpu_b.font.color.rgb = PINE_FOREST

    r_gpu_d = p_gpu.add_run()
    r_gpu_d.text = "4.0 ms to 15.0 ms evaluated locally on consumer hardware (NVIDIA RTX 4060)."
    r_gpu_d.font.name = FONT_SANS
    r_gpu_d.font.size = Pt(9.6)
    r_gpu_d.font.color.rgb = TEXT_SECONDARY

# ==============================================================================
# SLIDE 4: Empirical Disaster Validation & Ablation Discovery
# ==============================================================================
def build_slide_4(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)

    add_header(
        slide,
        title="UrbanFLOW | Empirical Monsoon Validation & Topological Integrity",
        subtitle="October 2024 Bengaluru Monsoon Evaluation and the SAGPool Discovery",
        category_str="Disaster Ground-Truth & Architectural Ablation",
        slide_idx_str="04 / 05"
    )

    card_top = Inches(1.52)
    card_w = Inches(5.72)
    card_h = Inches(5.58)

    # Card 1: Monsoon Validation
    left_1 = Inches(0.8)
    add_card(slide, left_1, card_top, card_w, card_h)

    hdr1 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_1, card_top, card_w, Inches(0.48))
    hdr1.fill.solid()
    hdr1.fill.fore_color.rgb = CARD_MUTED_BG
    hdr1.line.color.rgb = CARD_BORDER
    hdr1.line.width = Pt(0.75)
    tf_h1 = hdr1.text_frame
    tf_h1.margin_left = Inches(0.18)
    tf_h1.margin_top = Inches(0.08)
    ph1 = tf_h1.paragraphs[0]
    ph1.text = "Card 1: Real-World Bengaluru Monsoon Validation"
    ph1.font.name = FONT_SANS
    ph1.font.size = Pt(12)
    ph1.font.bold = True
    ph1.font.color.rgb = PINE_FOREST

    tb_1 = slide.shapes.add_textbox(left_1 + Inches(0.2), card_top + Inches(0.56), card_w - Inches(0.4), card_h - Inches(0.66))
    tf_1 = tb_1.text_frame
    tf_1.word_wrap = True
    tf_1.margin_left = Inches(0)
    tf_1.margin_top = Inches(0)

    # Provenance
    p1 = tf_1.paragraphs[0]
    p1.space_after = Pt(8)
    r1 = p1.add_run()
    r1.text = "• Data Provenance: "
    r1.font.bold = True
    r1.font.size = Pt(9.6)
    r1.font.color.rgb = PINE_FOREST
    r1_d = p1.add_run()
    r1_d.text = "13 documented flood locations compiled across 3 real storm events from mainstream press (The Hindu, Indian Express, TOI, Moneycontrol):\n  - Oct 14–15: 65 mm (142 waterlogged points across the city)\n  - Oct 19–20: Kengeri 141 mm, Hosur Road deluged\n  - Oct 21–22: IMD GKVK 186.2 mm (27-year record cloudburst)"
    r1_d.font.size = Pt(9.0)
    r1_d.font.color.rgb = TEXT_SECONDARY

    # 50m Proximity Capture
    p2 = tf_1.add_paragraph()
    p2.space_after = Pt(8)
    r2 = p2.add_run()
    r2.text = "• Strict 50-Meter Proximity Capture Results:\n"
    r2.font.bold = True
    r2.font.size = Pt(9.6)
    r2.font.color.rgb = PINE_FOREST
    
    captures = [
        ("Silk Board Junction & Hosur Rd", "CAPTURED (nearest hazard: 33.7 m)"),
        ("Madiwala Junction", "CAPTURED (nearest hazard: 10.2 m)"),
        ("Ecospace Junction (ORR)", "CAPTURED (nearest hazard: 27.8 m)"),
        ("ORR Iblur–Marathahalli Service Rd", "CAPTURED (nearest hazard: 29.8 m)"),
        ("Devarabeesanahalli (ORR)", "CAPTURED (nearest hazard: 26.8 m)")
    ]
    for loc, status in captures:
        rc = p2.add_run()
        rc.text = f"  ✓ {loc}: "
        rc.font.bold = True
        rc.font.size = Pt(9.0)
        rc.font.color.rgb = LEAF_GREEN
        rs = p2.add_run()
        rs.text = status + "\n"
        rs.font.size = Pt(9.0)
        rs.font.color.rgb = TEXT_SECONDARY

    # Capture rate & attribution
    p3 = tf_1.add_paragraph()
    p3.space_after = Pt(6)
    r3 = p3.add_run()
    r3.text = "• Zero-Shot Spatial Capture Rate: "
    r3.font.bold = True
    r3.font.size = Pt(9.6)
    r3.font.color.rgb = PINE_FOREST
    r3_d = p3.add_run()
    r3_d.text = "5/13 locations (38.5%) under strict 50 m buffer without local sensor tuning."
    r3_d.font.size = Pt(9.2)
    r3_d.font.color.rgb = TEXT_SECONDARY

    p4 = tf_1.add_paragraph()
    r4 = p4.add_run()
    r4.text = "• Transparent Failure Attribution: "
    r4.font.bold = True
    r4.font.size = Pt(9.6)
    r4.font.color.rgb = PINE_FOREST
    r4_d = p4.add_run()
    r4_d.text = "Misses (83–356 m) reflect localized trash-screen debris blockages and unmodeled lake breaches not represented in 10 m DEM topography."
    r4_d.font.size = Pt(9.0)
    r4_d.font.color.rgb = TEXT_SECONDARY

    # Card 2: SAGPool Topological Failure Case
    left_2 = Inches(6.81)
    add_card(slide, left_2, card_top, card_w, card_h)

    hdr2 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_2, card_top, card_w, Inches(0.48))
    hdr2.fill.solid()
    hdr2.fill.fore_color.rgb = HAZARD_TINT
    hdr2.line.color.rgb = CARD_BORDER
    hdr2.line.width = Pt(0.75)
    tf_h2 = hdr2.text_frame
    tf_h2.margin_left = Inches(0.18)
    tf_h2.margin_top = Inches(0.08)
    ph2 = tf_h2.paragraphs[0]
    ph2.text = "Card 2: The SAGPool Topological Failure Case"
    ph2.font.name = FONT_SANS
    ph2.font.size = Pt(12)
    ph2.font.bold = True
    ph2.font.color.rgb = HAZARD_TERRACOTTA

    tb_2 = slide.shapes.add_textbox(left_2 + Inches(0.2), card_top + Inches(0.56), card_w - Inches(0.4), card_h - Inches(0.66))
    tf_2 = tb_2.text_frame
    tf_2.word_wrap = True
    tf_2.margin_left = Inches(0)
    tf_2.margin_top = Inches(0)

    sag_points = [
        ("The Pooling Hypothesis: ", "Evaluated Self-Attention Graph Pooling (SAGPool) to compress massive networks by dropping non-critical nodes."),
        ("The Hydraulic Failure Mechanism: ", "In steep coastal topographies like Hong Kong (mean relief dz = 184 m), pruning intermediate nodes severed contiguous downstream drainage conduits, breaking hydraulic head continuity."),
        ("The Engineering Solution: ", "Completely removed pooling in favor of non-destructive, full-resolution message passing governed by a Topological Mixture-of-Experts (MoE) Router."),
        ("Validated Outcome: ", "Preserved 100% of street conduit connectivity, restoring Hong Kong F1-score to 0.942 and maintaining global MAE at 2.44 cm.")
    ]

    for idx, (title, desc) in enumerate(sag_points):
        p = tf_2.paragraphs[0] if idx == 0 else tf_2.add_paragraph()
        p.space_after = Pt(14)
        rb = p.add_run()
        rb.text = "• "
        rb.font.bold = True
        rb.font.color.rgb = HAZARD_TERRACOTTA
        rt = p.add_run()
        rt.text = title
        rt.font.name = FONT_SANS
        rt.font.bold = True
        rt.font.size = Pt(9.6)
        rt.font.color.rgb = PINE_FOREST
        rd = p.add_run()
        rd.text = desc
        rd.font.name = FONT_SANS
        rd.font.size = Pt(9.6)
        rd.font.color.rgb = TEXT_SECONDARY

# ==============================================================================
# SLIDE 5: Municipal Digital Twin Console & Asset Dispatch
# ==============================================================================
def build_slide_5(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_background(slide)

    add_header(
        slide,
        title="UrbanFLOW | Municipal Command Console & Physical Asset Dispatch",
        subtitle="From Sub-100 ms Graph Inference to Autonomous Civic Interventions",
        category_str="Civic Digital Twin & Autonomous Interventions",
        slide_idx_str="05 / 05"
    )

    card_top = Inches(1.52)
    card_h = Inches(4.75)

    # Left Column: Digital Twin UI
    col_w_left = Inches(5.6)
    left_1 = Inches(0.8)
    add_card(slide, left_1, card_top, col_w_left, card_h)

    hdr1 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_1, card_top, col_w_left, Inches(0.48))
    hdr1.fill.solid()
    hdr1.fill.fore_color.rgb = CARD_MUTED_BG
    hdr1.line.color.rgb = CARD_BORDER
    hdr1.line.width = Pt(0.75)
    tf_h1 = hdr1.text_frame
    tf_h1.margin_left = Inches(0.18)
    tf_h1.margin_top = Inches(0.08)
    ph1 = tf_h1.paragraphs[0]
    ph1.text = "Interactive WebGL / Canvas Twin Dashboard"
    ph1.font.name = FONT_SANS
    ph1.font.size = Pt(12)
    ph1.font.bold = True
    ph1.font.color.rgb = PINE_FOREST

    tb_1 = slide.shapes.add_textbox(left_1 + Inches(0.2), card_top + Inches(0.56), col_w_left - Inches(0.4), card_h - Inches(0.66))
    tf_1 = tb_1.text_frame
    tf_1.word_wrap = True
    tf_1.margin_left = Inches(0)
    tf_1.margin_top = Inches(0)

    bullets_ui = [
        ("Frontend Stack: ", "Built with Leaflet 1.9.4 and a custom HTML5 Canvas overlay delivering full-catchment depth rendering in <100 ms."),
        ("Tactical Forcing Controls: ", "Dynamic rainfall slider (10 to 300 mm/hr, step 5, default 50 mm/hr) and storm duration slider (15 to 120 min)."),
        ("Multi-Tier Risk Visualization:\n", "• Safe Nodes (<0.05 m): Baseline green markers.\n• Advisory Corridors (0.15–0.35 m): Terracotta alert markers.\n• Surcharged Sags (>=0.35 m): Deep crimson with active pulsing outer halo."),
        ("Junction Hydraulic Inspector: ", "Click any node to inspect predicted depth (m/cm), SWMM dynamic-wave baseline, surface elevation, invert slope, sag index, and automated dispatch orders.")
    ]

    for idx, (title, desc) in enumerate(bullets_ui):
        p = tf_1.paragraphs[0] if idx == 0 else tf_1.add_paragraph()
        p.space_after = Pt(10)
        rb = p.add_run()
        rb.text = "• "
        rb.font.bold = True
        rb.font.color.rgb = LEAF_GREEN
        rt = p.add_run()
        rt.text = title
        rt.font.name = FONT_SANS
        rt.font.bold = True
        rt.font.size = Pt(9.4)
        rt.font.color.rgb = PINE_FOREST
        rd = p.add_run()
        rd.text = desc
        rd.font.name = FONT_SANS
        rd.font.size = Pt(9.4)
        rd.font.color.rgb = TEXT_SECONDARY

    # Right Column: 3 Decision Directives
    col_w_right = Inches(5.85)
    left_2 = Inches(6.68)
    add_card(slide, left_2, card_top, col_w_right, card_h)

    hdr2 = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_2, card_top, col_w_right, Inches(0.48))
    hdr2.fill.solid()
    hdr2.fill.fore_color.rgb = AMBER_TINT
    hdr2.line.color.rgb = CARD_BORDER
    hdr2.line.width = Pt(0.75)
    tf_h2 = hdr2.text_frame
    tf_h2.margin_left = Inches(0.18)
    tf_h2.margin_top = Inches(0.08)
    ph2 = tf_h2.paragraphs[0]
    ph2.text = "Autonomous Civic Directives"
    ph2.font.name = FONT_SANS
    ph2.font.size = Pt(12)
    ph2.font.bold = True
    ph2.font.color.rgb = NATURAL_AMBER

    directives = [
        ("1. Automated Barrier Gate Actuation",
         "Automatically issues motorized closure signals to barrier gates when underpass junctions exceed 0.30 m predicted depth, preventing vehicles from entering submerged highway traps.",
         HAZARD_TERRACOTTA, HAZARD_TINT),
        ("2. Mobile Dewatering Pump Dispatch",
         "Evaluates topological accumulation gradients to calculate optimal staging of trailer-mounted 5,000 L/min pumps at critical depression sags.",
         NATURAL_AMBER, AMBER_TINT),
        ("3. Dynamic Emergency Routing",
         "Exports real-time travel-time penalty matrices to municipal dispatch systems, rerouting ambulances and fire services around flooded intersections.",
         LEAF_GREEN, CARD_MUTED_BG)
    ]

    dir_y = card_top + Inches(0.58)
    dir_h = Inches(1.22)
    dir_gap = Inches(0.14)

    for i, (d_title, d_desc, d_color, d_tint) in enumerate(directives):
        dy = dir_y + i * (dir_h + dir_gap)
        d_card = add_card(slide, left_2 + Inches(0.2), dy, col_w_right - Inches(0.4), dir_h, fill_color=d_tint, border_color=d_color, border_width=1.0)
        
        tb_d = slide.shapes.add_textbox(left_2 + Inches(0.32), dy + Inches(0.08), col_w_right - Inches(0.64), dir_h - Inches(0.16))
        tf_d = tb_d.text_frame
        tf_d.word_wrap = True
        tf_d.margin_left = Inches(0)
        tf_d.margin_top = Inches(0)

        pd0 = tf_d.paragraphs[0]
        rd_title = pd0.add_run()
        rd_title.text = d_title
        rd_title.font.name = FONT_SANS
        rd_title.font.size = Pt(10.5)
        rd_title.font.bold = True
        rd_title.font.color.rgb = d_color

        pd1 = tf_d.add_paragraph()
        pd1.space_before = Pt(3)
        rd_desc = pd1.add_run()
        rd_desc.text = d_desc
        rd_desc.font.name = FONT_SANS
        rd_desc.font.size = Pt(9.0)
        rd_desc.font.color.rgb = PINE_FOREST

    # Bottom Closing Strip
    add_bottom_banner(
        slide,
        label="Operational Impact",
        text="Bridges the gap between retrospective numerical simulation and sub-second proactive disaster mitigation, enabling climate-resilient early warning worldwide."
    )

def main():
    prs = init_presentation()
    print("Building Slide 0: Title Slide (Clean & Minimalist)...")
    build_slide_0(prs)
    print("Building Slide 1: Crisis vs. Numerical Solver...")
    build_slide_1(prs)
    print("Building Slide 2: Physics-Guided Architecture...")
    build_slide_2(prs)
    print("Building Slide 3: Multi-Catchment Global Benchmark...")
    build_slide_3(prs)
    print("Building Slide 4: Empirical Disaster Validation & SAGPool...")
    build_slide_4(prs)
    print("Building Slide 5: Municipal Twin Console & Dispatch...")
    build_slide_5(prs)

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "UrbanFLOW_Research_Deck.pptx")
    prs.save(out_path)
    print(f"Presentation saved successfully to: {out_path}")

if __name__ == "__main__":
    main()
