import sys
import numpy as np
from PIL import Image

def load(path):
    im = Image.open(path).convert("RGB")
    return np.asarray(im).astype(np.float32)

def ladder_extent(path, h, ppd, horizon_y, band=(360, 440), clean=(80, 180),
                   ymin=0, ymax=None):
    """Row-by-row: is there a ladder mark (tick/text) at this row that
    isn't present in the clean background band? Returns the furthest
    |pitch degrees from current pitch (0)| where a mark is still found,
    separately above and below the horizon."""
    arr = load(path)
    H, W, _ = arr.shape
    ymax = ymax or H
    band_px = arr[:, band[0]:band[1], :]
    clean_px = arr[:, clean[0]:clean[1], :]
    # per-row std across the band vs the clean reference column set;
    # a ladder tick/text row has much higher local variance than sky/terrain fill
    band_std = band_px.std(axis=(1, 2))
    clean_std = clean_px.std(axis=(1, 2))
    signal = band_std - clean_std
    thresh = max(3.0, np.percentile(signal[ymin:ymax], 60))
    marked_rows = np.where(signal[ymin:ymax] > thresh)[0] + ymin

    up_rows = marked_rows[marked_rows < horizon_y]
    down_rows = marked_rows[marked_rows > horizon_y]

    up_deg = (horizon_y - up_rows.min()) / ppd if len(up_rows) else 0.0
    down_deg = (down_rows.max() - horizon_y) / ppd if len(down_rows) else 0.0
    return up_deg, down_deg, thresh, len(marked_rows)

if __name__ == "__main__":
    H = 480
    cases = [
        ("baseline_hp68_800x480.png", H / 30.0, H/2 - (0.68-0.5)*H, "baseline pitchDegreesShown=30, hp=68"),
        ("decouple_v2_hp50_800x480.png", H / 50.0, H/2 - (0.50-0.5)*H, "decouple-v2 pitchDegreesShown=50, hp=50"),
        ("decouple_v2_hp68_800x480.png", H / 50.0, H/2 - (0.68-0.5)*H, "decouple-v2 pitchDegreesShown=50, hp=68"),
    ]
    for fname, ppd, horizon_y, label in cases:
        up, down, thresh, n = ladder_extent(fname, H, ppd, horizon_y)
        print(f"{label:45s} ppd={ppd:5.2f} horizon_y={horizon_y:6.1f}  "
              f"up={up:5.1f} deg  down={down:5.1f} deg  (thresh={thresh:.1f}, n_rows={n})")
