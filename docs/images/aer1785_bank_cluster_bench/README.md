# AER-1794 -- bank-angle cluster on the glass, `aer-1785/windowed-bank-radius-stale`

Bench: Beelink, `10.110.10.241` (`beelinkpyefis`), pyEfis checkout staged via
`bench-deploy.sh --ref aer-1785/windowed-bank-radius-stale` at commit
`283969e` (merge of `dev`@`4838942` into the PR branch). `pyefis.service`
`active`, no tracebacks in the post-restart journal.

`SIGUSR1`'s `/tmp/pyefis_screenshot.png` grab is a Qt offscreen widget-grab
and blanks the SVS/AI `QOpenGLWidget` (documented pyEfis behavior, not a bug
here) -- it cannot show the bank cluster, which is GL-rendered. This box runs
an X11 kiosk (`DISPLAY=:0`), so a real X-server screen capture does include
the composited GL content:

```bash
sudo apt-get install -y scrot   # not present on the box; passwordless sudo
DISPLAY=:0 scrot -o /tmp/bank-cluster-full.png
```

`bank_cluster_full_1920x1080.png` is that capture, unmodified, full screen.
`bank_cluster_zoom2x.png` is a nearest-neighbour 2x crop of the bank-angle
scale itself (the sky-pointer triangle, static aircraft symbol, and 10/20/30
degree diamond marks at the top of the AI), cropped to `(350,40)-(950,220)`
of the full frame.

![bank cluster, full frame](https://raw.githubusercontent.com/billmallard/pyEfis/9417846e2852f06a6f5cfb699c2f5fbb092f75b2/docs/images/aer1785_bank_cluster_bench/bank_cluster_full_1920x1080.png)

![bank cluster, 2x zoom crop](https://raw.githubusercontent.com/billmallard/pyEfis/9417846e2852f06a6f5cfb699c2f5fbb092f75b2/docs/images/aer1785_bank_cluster_bench/bank_cluster_zoom2x.png)

## Disposition

This is a staging capture for Bill's on-glass judgement of the bank-angle
cluster -- nothing here self-certifies correctness. `aer-1785/windowed-bank-radius-stale`
merged as PR #251; its content is now `dev`. AER-1793, which held the
`--restore` decision, was discharged by Elon and closed on 2026-09-20; no open
issue owns the restore. AER-1803 returns the bench to `dev`.
