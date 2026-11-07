# Engine pictures

For [Engine Monitoring](../../wiki/Engine-Monitoring.md).

`bench_engine_tab_no_data.png`: the Engine tab of the simulator bench's panel
(the Beelink, X11), box (1248, 0, 1920, 330) of the 1920 x 1080 frame. Ground
capture on 2026-11-07 at about 14:05 UTC, no flight running, bench lock held:
touch the Engine tab (`xdotool mousemove 1422 13 click 1`), take pyEFIS's own
screenshot (`kill -USR1 <pyefis pid>`), then touch the Map tab again. The bench
sends no engine data, so every gauge shows its stale-data colours and a reading
of 0.0.
