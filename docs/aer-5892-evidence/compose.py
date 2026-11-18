"""Compose the MENU1 bench evidence (AER-5892) from the raw Beelink x11grab
frames in a frames directory (see README.md). Usage:
    python3 compose.py <frames_dir> <out_dir> <font.ttf>"""
import sys
from PIL import Image, ImageDraw, ImageFont

src, out, ttf = sys.argv[1], sys.argv[2], sys.argv[3]
F = ImageFont.truetype(ttf, 18)


def tile(name, w, h, caption):
    im = Image.open("%s/%s.png" % (src, name)).convert("RGB").resize((w, h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h + 30), (255, 255, 255))
    canvas.paste(im, (0, 30))
    ImageDraw.Draw(canvas).text((6, 5), caption, fill=(0, 0, 0), font=F)
    return canvas


def grid(cells, cols, w, h, path):
    rows = (len(cells) + cols - 1) // cols
    g = Image.new("RGB", (cols * (w + 6), rows * (h + 36)), (255, 255, 255))
    for i, (name, cap) in enumerate(cells):
        g.paste(tile(name, w, h, cap), ((i % cols) * (w + 6), (i // cols) * (h + 36)))
    g.save(path, optimize=True)


grid([("before_dev", "dev: no menu"),
      ("s11_menu_after_plain_restart", "branch: after the corner swipe")],
     2, 960, 540, out + "/before_after_pfd.png")

grid([("s11_menu_after_plain_restart", "PFD (the bench panel)"),
      ("s51_menu_on_PFD_AI_ONLY", "PFD_AI_ONLY"),
      ("s4_menu_on_RADIO", "RADIO"),
      ("s4_menu_on_EMS", "EMS"),
      ("s4_menu_on_EMS2", "EMS2"),
      ("s75_accept_on_fpl", "FLIGHTPLAN"),
      ("s21_menu_over_data_status", "DataStatus"),
      ("s31_screens_page", "Screens page (PFD outlined: current)")],
     4, 480, 270, out + "/menu_on_every_screen.png")

grid([("s50_on_PFD_AI_ONLY", "1. on PFD_AI_ONLY"),
      ("s51_menu_on_PFD_AI_ONLY", "2. swipe: menu"),
      ("s52_data_status_from_PFD_AI_ONLY", "3. Data Status"),
      ("s53_continue_returns", "4. Continue: back on PFD_AI_ONLY"),
      ("s54_about_from_PFD_AI_ONLY", "5. swipe, About"),
      ("s55_about_back_returns", "6. Back: back on PFD_AI_ONLY")],
     3, 560, 315, out + "/return_route.png")

grid([("s62_reject_map_pan", "map pan: map moves, no menu"),
      ("s63_reject_slow_corner_drag", "swipe shape over 2.5 s: no menu"),
      ("s64_reject_straight_down", "straight down from corner: no menu"),
      ("s65_reject_below_strip", "swipe from 45 px down: no menu"),
      ("s66_reject_too_flat", "flat leftward drag: no menu"),
      ("s67_reject_corner_tap", "tap in the corner: no menu"),
      ("s71_reject_fpl_scroll_down", "FPL scroll down: no menu"),
      ("s73_reject_fpl_scroll_from_corner", "FPL scroll from corner: no menu"),
      ("s74_reject_fpl_wobbly_scroll", "FPL wobbly scroll: no menu"),
      ("s68_accept_after_rejects", "then the swipe: menu")],
     5, 384, 216, out + "/rejects.png")

# 1:1 crops of the card for the look
Image.open(src + "/s68_accept_after_rejects.png").convert("RGB").crop(
    (1240, 0, 1920, 300)).save(out + "/card_main_1to1.png", optimize=True)
Image.open(src + "/s31_screens_page.png").convert("RGB").crop(
    (1240, 0, 1920, 440)).save(out + "/card_screens_1to1.png", optimize=True)
