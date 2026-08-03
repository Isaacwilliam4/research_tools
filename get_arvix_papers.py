#!/usr/bin/env python3
"""
Download arXiv PDFs for the references in the LiDAR sim2real literature review
and bundle them into lidar_sim2real_refs.zip.

Usage:  python download_lidar_refs.py
Requires: requests  (pip install requests)

References with a known arXiv ID are fetched directly. References without a
known ID are looked up by title via the arXiv API; if no match is found they
are skipped (some, e.g. the Huch Sensors/T-IV papers or Towards Zero Domain
Gap, may not be on arXiv at all).
"""

import re
import time
import zipfile
from pathlib import Path

import requests

OUT_DIR = Path("lidar_sim2real_refs")
ZIP_NAME = "lidar_sim2real_refs.zip"
HEADERS = {"User-Agent": "lit-review-downloader/1.0 (personal research use)"}

# (output filename, arXiv ID or None, title used for API lookup if ID is None)
REFS = [
    ("lidarsim_cvpr2020",            "2006.09348", None),
    ("learning_realistic_lidars_iros2022", "2209.10986", None),
    ("towards_zero_domain_gap_iccv2023", None, "Towards Zero Domain Gap: A Comprehensive Study of Realistic LiDAR Simulation for Autonomy Testing"),
    ("fog_simulation_iccv2021",      "2108.05249", None),
    ("snowfall_simulation_cvpr2022", "2203.15118", None),
    ("lisa_2021",                    "2107.07004", None),
    ("squeezesegv2_icra2019",        "1809.08495", None),
    ("epointda_aaai2021",            "2009.03456", None),
    ("lidarnet_icra2021",            "2003.01174", None),
    ("xmuda_cvpr2020",               "1911.12676", None),
    ("synlidar_aaai2022",            "2107.05399", None),
    ("cosmix_eccv2022",              "2207.09778", None),
    ("polarmix_neurips2022",         "2208.00223", None),
    ("drum_2025",                    None, "DRUM diffusion sim2real LiDAR raydrop"),
    ("lidar_diffusion_models_cvpr2024", "2404.00815", None),
    ("neural_lidar_fields_iccv2023", "2305.01643", None),
    ("lidar_nerf_2023",              "2304.10406", None),
    ("lidar4d_cvpr2024",             "2404.02742", None),
    ("lidar_gs_2024",                "2410.05111", None),
    ("gs_lidar_iclr2025",            None, "GS-LiDAR: Generating Realistic LiDAR Point Clouds with Panoramic Gaussian Splatting"),
    ("lidardm_2024",                 "2404.02903", None),
    ("unisim_cvpr2023",              None, "UniSim: A Neural Closed-Loop Sensor Simulator"),
    ("huch_quantifying_tiv2023",     None, "Quantifying the LiDAR Sim-to-Real Domain Shift"),
    ("huch_object_level_da_sensors2023", None, "Object-Level Local Domain Adaptation for 3D Point Clouds of Autonomous Vehicles"),
    ("zhao_sim2real_survey_ssci2020","2009.13303", None),
    ("tobin_domain_randomization_iros2017", "1703.06907", None),
    ("omni_perception_2025",         "2505.19214", None),
    ("salimpour_isaacsim_ros2_2025", "2501.02902", None),
    ("miki_perceptive_locomotion_scirobotics2022", "2201.08117", None),
]


def search_arxiv_id(title: str) -> str | None:
    """Look up an arXiv ID by title via the arXiv API. Returns None if no hit."""
    url = "http://export.arxiv.org/api/query"
    params = {"search_query": f'ti:"{title}"', "max_results": 1}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException:
        return None
    m = re.search(r"<id>https?://arxiv\.org/abs/([^<]+)</id>", r.text)
    if not m:
        return None
    return m.group(1).split("v")[0]  # strip version suffix


def download_pdf(arxiv_id: str, dest: Path) -> bool:
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=120)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            dest.write_bytes(r.content)
            return True
    except requests.RequestException:
        pass
    return False


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    ok, skipped = [], []

    for name, arxiv_id, title in REFS:
        dest = OUT_DIR / f"{name}.pdf"
        if dest.exists():
            print(f"[skip] {name} (already downloaded)")
            ok.append(name)
            continue

        if arxiv_id is None and title:
            print(f"[find] searching arXiv for: {title[:60]}...")
            arxiv_id = search_arxiv_id(title)
            time.sleep(3)  # arXiv API asks for ~3 s between requests

        if arxiv_id and download_pdf(arxiv_id, dest):
            print(f"[ ok ] {name}  (arXiv:{arxiv_id})")
            ok.append(name)
        else:
            print(f"[miss] {name} — not found on arXiv, skipping")
            skipped.append(name)
        time.sleep(3)

    with zipfile.ZipFile(ZIP_NAME, "w", zipfile.ZIP_DEFLATED) as zf:
        for pdf in sorted(OUT_DIR.glob("*.pdf")):
            zf.write(pdf, pdf.name)

    print(f"\nDone: {len(ok)} PDFs zipped into {ZIP_NAME}; {len(skipped)} skipped.")
    if skipped:
        print("Skipped (likely not on arXiv):")
        for name in skipped:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
