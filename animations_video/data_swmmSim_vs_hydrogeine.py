import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np

# 1. Styling & Theme Palette (Ceramic Botanical)
BG_CANVAS = '#F3F6F1'
PINE_HEADER = '#233E2B'
LEAF_GREEN = '#2E7D32'
TERRACOTTA = '#BA3C23'
TEXT_DARK = '#192B1D'
CARD_BORDER = '#CAD7C7'

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['text.color'] = TEXT_DARK
plt.rcParams['axes.labelcolor'] = TEXT_DARK
plt.rcParams['xtick.color'] = TEXT_DARK
plt.rcParams['ytick.color'] = TEXT_DARK

# 2. Canonical Real-World Validation Data (October 2024 Bengaluru)
incidents = [
    {'name': 'Silk Board Junc.', 'dist': 33.7, 'status': 'CAPTURED'},
    {'name': 'Madiwala Junc.', 'dist': 10.2, 'status': 'CAPTURED'},
    {'name': 'Ecospace (ORR)', 'dist': 27.8, 'status': 'CAPTURED'},
    {'name': 'Iblur-Marathahalli', 'dist': 29.8, 'status': 'CAPTURED'},
    {'name': 'Devarabeesanahalli', 'dist': 26.8, 'status': 'CAPTURED'},
    {'name': 'Bellandur Lake', 'dist': 82.7, 'status': 'MISSED'},
    {'name': 'Roopena Agrahara', 'dist': 140.1, 'status': 'MISSED'},
    {'name': 'HSR 27th Main', 'dist': 236.1, 'status': 'MISSED'},
    {'name': 'Sarjapur Rd', 'dist': 223.3, 'status': 'MISSED'},
    {'name': 'Bommanahalli', 'dist': 171.6, 'status': 'MISSED'},
    {'name': 'Hope Farm Junc.', 'dist': 92.8, 'status': 'MISSED'},
    {'name': 'ITPL Road', 'dist': 355.6, 'status': 'MISSED'},
    {'name': 'Electronic City', 'dist': 198.8, 'status': 'MISSED'},
]

incidents = sorted(incidents, key=lambda x: x['dist'])
names = [item['name'] for item in incidents]
distances = [item['dist'] for item in incidents]
colors = [
    LEAF_GREEN if item['status'] == 'CAPTURED' else TERRACOTTA
    for item in incidents
]

# Total frames to complete animation together
ANIMATION_FRAMES = 40
HOLD_FRAMES = 20  # Hold the final completed frame for readability
TOTAL_FRAMES = ANIMATION_FRAMES + HOLD_FRAMES

# Time domain (full 60-min storm completed across the animation window)
time_min = np.linspace(0, 60, ANIMATION_FRAMES)
swmm_peak = 0.85
swmm_curve = swmm_peak / (1 + np.exp(-0.15 * (time_min - 25)))
gnn_curve = 0.82 / (1 + np.exp(-0.15 * (time_min - 24.5)))

# 3. Canvas Setup
fig, (ax_bar, ax_curve) = plt.subplots(1, 2, figsize=(14, 6), dpi=150)
fig.patch.set_facecolor(BG_CANVAS)
ax_bar.set_facecolor('#FFFFFF')
ax_curve.set_facecolor('#FFFFFF')

fig.suptitle(
    'UrbanFLOW vs. EPA SWMM 5.2 | Bengaluru October 2024 Monsoon Validation',
    fontsize=14,
    fontweight='bold',
    color=PINE_HEADER,
    y=0.96,
)

# 4. Initialize Elements
ax_bar.set_xlim(0, 380)
ax_bar.set_xlabel('Nearest Predicted Hazard Distance (meters)', fontsize=10)
ax_bar.set_title(
    'Spatial Capture Audit (13 Ground Truth Sites)',
    fontsize=11,
    fontweight='bold',
    pad=10,
)
ax_bar.invert_yaxis()

(line_swmm,) = ax_curve.plot(
    [],
    [],
    color='#1F3826',
    linewidth=2.2,
    linestyle='--',
    label='EPA SWMM 5.2 (1D/2D Saint-Venant)',
)
(line_gnn,) = ax_curve.plot(
    [],
    [],
    color=LEAF_GREEN,
    linewidth=2.5,
    label='UrbanFLOW HydroGINE-v5 (Sub-100 ms API)',
)
ax_curve.axhline(
    0.15,
    color=TERRACOTTA,
    linestyle=':',
    linewidth=1.2,
    label='Hazard Threshold (≥0.15 m)',
)
ax_curve.set_xlim(0, 60)
ax_curve.set_ylim(0, 1.0)
ax_curve.set_xlabel('Storm Elapsed Time (minutes)', fontsize=10)
ax_curve.set_ylabel('Junction Inundation Depth (meters)', fontsize=10)
ax_curve.set_title(
    'Silk Board Junction Hydrograph Response',
    fontsize=11,
    fontweight='bold',
    pad=10,
)
ax_curve.grid(True, linestyle=':', alpha=0.6)
ax_curve.legend(loc='upper left', fontsize=9)

time_text = ax_curve.text(
    0.70,
    0.15,
    '',
    transform=ax_curve.transAxes,
    fontsize=10,
    fontweight='bold',
    bbox=dict(
        boxstyle='round,pad=0.4', facecolor=BG_CANVAS, edgecolor=PINE_HEADER
    ),
)


# 5. Synchronized Animation Update
def update(frame):
  # Cap progression at ANIMATION_FRAMES so both hold steady during hold frames
  idx = min(frame, ANIMATION_FRAMES - 1)
  progress_frac = (idx + 1) / float(ANIMATION_FRAMES)

  # Synchronized Hydrograph update (finishes at frame 40)
  t = time_min[: idx + 1]
  line_swmm.set_data(t, swmm_curve[: idx + 1])
  line_gnn.set_data(t, gnn_curve[: idx + 1])
  time_text.set_text(f'Storm T = {time_min[idx]:.1f} min')

  # Synchronized Bar Chart update (finishes at frame 40)
  ax_bar.cla()
  ax_bar.set_facecolor('#FFFFFF')
  ax_bar.axvline(
      50.0,
      color=PINE_HEADER,
      linestyle='--',
      linewidth=1.5,
      label='50 m Capture Buffer',
  )
  ax_bar.set_xlim(0, 380)
  ax_bar.set_xlabel('Nearest Predicted Hazard Distance (meters)', fontsize=10)
  ax_bar.set_title(
      'Spatial Capture Audit (13 Ground Truth Sites)',
      fontsize=11,
      fontweight='bold',
      pad=10,
  )
  ax_bar.set_yticks(range(len(names)))
  ax_bar.set_yticklabels(names, fontsize=8)
  ax_bar.invert_yaxis()
  ax_bar.grid(axis='x', linestyle=':', alpha=0.6)
  ax_bar.legend(loc='lower right', fontsize=9)

  current_bars = [d * progress_frac for d in distances]
  bars = ax_bar.barh(
      range(len(names)),
      current_bars,
      color=colors,
      height=0.65,
      alpha=0.9,
      edgecolor=CARD_BORDER,
  )

  # Text labels display once both animations finish
  if progress_frac >= 1.0:
    for i, b in enumerate(bars):
      status = incidents[i]['status']
      dist_val = incidents[i]['dist']
      ax_bar.text(
          dist_val + 5,
          i,
          f'{dist_val} m ({status})',
          va='center',
          fontsize=7.5,
          fontweight='bold',
          color=colors[i],
      )

  return line_swmm, line_gnn, time_text


# 6. Build and Export
ani = animation.FuncAnimation(
    fig, update, frames=TOTAL_FRAMES, interval=50, blit=False
)

ani.save('urbanflow_bengaluru_validation_sync.gif', writer='pillow', fps=20)
plt.tight_layout(rect=[0, 0.03, 1, 0.93])
plt.show()