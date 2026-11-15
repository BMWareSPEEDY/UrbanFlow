"""
Verification suite for UrbanFLOW Science Fair Presentation Deck
Tests both the PPTX file structure and the Flask web presentation endpoints.
"""

import os
import sys
from pptx import Presentation

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

def test_pptx_deck():
    pptx_path = os.path.join(BASE_DIR, "UrbanFLOW_Research_Deck.pptx")
    assert os.path.exists(pptx_path), f"File {pptx_path} does not exist!"
    
    prs = Presentation(pptx_path)
    
    # 1. Check aspect ratio (16:9 widescreen)
    w_in = prs.slide_width.inches
    h_in = prs.slide_height.inches
    ratio = w_in / h_in
    print(f"[TEST 1] Dimensions: {w_in:.3f}\" x {h_in:.3f}\" (aspect ratio: {ratio:.3f})")
    assert abs(ratio - (16/9)) < 0.01, f"Expected 16:9 aspect ratio, got {ratio}"
    
    # 2. Check slide count (Slide 0 + 5 slides = 6 total slides)
    num_slides = len(prs.slides)
    print(f"[TEST 2] Number of slides: {num_slides}")
    assert num_slides == 6, f"Expected exactly 6 slides, got {num_slides}"
    
    # 3. Check slide contents
    expected_keywords_per_slide = [
        # Slide 0: Title Slide / Research Pitch
        ["UrbanFLOW", "IRIS NATIONAL FAIR 2026–27", "EAEV-26-HYDRO-048", "Pillar I", "Pillar II", "Pillar III"],
        # Slide 1: Crisis & SWMM
        ["Convective Cloudburst Drainage Crisis", "EPA SWMM 5.2", "Saint-Venant", "Courant-Friedrichs-Lewy", "80.9%", "Core Hypothesis"],
        # Slide 2: Architecture & Biases
        ["HydroGINE-v5", "Kirpich", "g_gate,uv", "Universal Physical Rails", "Decoupled FiLM", "Asymmetric Safety Loss"],
        # Slide 3: Multi-Catchment Global Benchmark & Speedup
        ["2.44 cm", "0.9128", "99.4%", "85.5 ms", "16 Basins", "~1,310x", "~8,690x", "RTX 4060"],
        # Slide 4: Empirical Disaster Validation & SAGPool
        ["Bengaluru", "Silk Board", "Madiwala", "Ecospace", "SAGPool", "Mixture-of-Experts"],
        # Slide 5: Municipal Twin Console & Asset Dispatch
        ["Leaflet 1.9.4", "Automated Barrier Gate", "Dewatering Pump", "Dynamic Emergency Routing", "Operational Impact"]
    ]
    
    for idx, (slide, keywords) in enumerate(zip(prs.slides, expected_keywords_per_slide)):
        slide_text = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    slide_text.append(p.text)
        full_slide_text = " ".join(slide_text)
        
        print(f"\n--- Checking Slide {idx} ---")
        for kw in keywords:
            assert kw.lower() in full_slide_text.lower(), f"Slide {idx} missing keyword: '{kw}'"
            print(f"  ✓ Found keyword: '{kw}'")
            
    print("\n[ALL PPTX DECK TESTS PASSED SUCCESSFULLY!]")

def test_web_presentation():
    from app import app
    client = app.test_client()
    
    # 1. Test /presentation route
    res = client.get('/presentation')
    print(f"[TEST WEB 1] /presentation status: {res.status_code}")
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert "UrbanFLOW" in html
    assert "slide-0" in html and "slide-5" in html
    assert "IRIS NATIONAL FAIR 2026–27" in html
    assert "g_gate,uv" in html
    assert "Silk Board" in html
    print("  ✓ /presentation HTML contains all slides, math, and telemetry")
    
    # 2. Test /download/deck route
    res_dl = client.get('/download/deck')
    print(f"[TEST WEB 2] /download/deck status: {res_dl.status_code}")
    assert res_dl.status_code == 200
    assert len(res_dl.data) > 30000
    print(f"  ✓ /download/deck delivered {len(res_dl.data)} bytes")
    
    # 3. Test index page has link to deck
    res_idx = client.get('/')
    print(f"[TEST WEB 3] / status: {res_idx.status_code}")
    assert res_idx.status_code == 200
    idx_html = res_idx.data.decode('utf-8')
    assert "/presentation" in idx_html
    assert "Science Fair Deck" in idx_html
    print("  ✓ Index page has active link to Science Fair Deck")
    
    print("\n[ALL WEB PRESENTATION TESTS PASSED SUCCESSFULLY!]")

if __name__ == "__main__":
    test_pptx_deck()
    test_web_presentation()
