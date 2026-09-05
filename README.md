# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/billmallard/pyEfis/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                    |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/pyefis/\_\_init\_\_.py                              |        1 |        0 |        0 |        0 |    100% |           |
| src/pyefis/cfg.py                                       |       79 |        0 |       70 |        0 |    100% |           |
| src/pyefis/common/\_\_init\_\_.py                       |       10 |        0 |        4 |        0 |    100% |           |
| src/pyefis/editor/\_\_init\_\_.py                       |        0 |        0 |        0 |        0 |    100% |           |
| src/pyefis/editor/groups.py                             |       17 |       17 |        2 |        0 |      0% |     31-83 |
| src/pyefis/editor/resolver.py                           |       49 |        3 |       16 |        2 |     92% |57-\>60, 67-68, 89 |
| src/pyefis/editor/schema.py                             |       78 |       28 |       32 |        2 |     60% |143, 148-158, 163-166, 195-\>197, 242, 395-411, 415 |
| src/pyefis/gui.py                                       |      213 |        4 |       70 |        2 |     98% |237, 246-\>245, 252-255 |
| src/pyefis/hmi/\_\_init\_\_.py                          |       13 |        0 |        2 |        0 |    100% |           |
| src/pyefis/hmi/actionclass.py                           |       36 |        0 |        4 |        0 |    100% |           |
| src/pyefis/hmi/data.py                                  |       77 |        0 |       36 |        0 |    100% |           |
| src/pyefis/hmi/functions.py                             |       30 |        1 |        2 |        1 |     94% |        47 |
| src/pyefis/hmi/keys.py                                  |       51 |        0 |       24 |        0 |    100% |           |
| src/pyefis/hmi/menu.py                                  |      176 |        0 |       50 |        0 |    100% |           |
| src/pyefis/hooks.py                                     |       14 |        0 |        4 |        0 |    100% |           |
| src/pyefis/instruments/NumericalDisplay/\_\_init\_\_.py |      209 |        0 |       42 |        0 |    100% |           |
| src/pyefis/instruments/\_\_init\_\_.py                  |        0 |        0 |        0 |        0 |    100% |           |
| src/pyefis/instruments/ai/VirtualVfr.py                 |      768 |        0 |      238 |        0 |    100% |           |
| src/pyefis/instruments/ai/\_\_init\_\_.py               |      854 |      159 |      206 |       22 |     79% |303-306, 328-331, 356, 367-403, 409-416, 423-433, 437-445, 472-476, 479-\>485, 663-666, 689-\>707, 699-\>703, 730, 733-734, 740-748, 751-754, 757-759, 772-781, 800-\>802, 850, 890, 896, 991-994, 998-1002, 1018-1060, 1066-1067, 1102, 1140-1145, 1160-1166, 1305 |
| src/pyefis/instruments/ai/airport\_db.py                |      277 |      120 |       98 |       11 |     51% |116-117, 122-124, 133, 150, 157, 160, 165, 179-\>183, 191, 196, 230-231, 247-264, 268, 278-371, 377-390, 402-423, 496, 498-500 |
| src/pyefis/instruments/ai/camera.py                     |       26 |        0 |        0 |        0 |    100% |           |
| src/pyefis/instruments/ai/highway\_db.py                |       49 |        6 |       12 |        2 |     87% |50-51, 59-61, 72 |
| src/pyefis/instruments/ai/obstacle\_db.py               |       66 |       30 |       14 |        1 |     46% |49-53, 58, 68-74, 78, 84-108 |
| src/pyefis/instruments/ai/pose.py                       |       54 |        0 |       14 |        1 |     99% |   85-\>88 |
| src/pyefis/instruments/ai/svs.py                        |     1123 |      660 |      334 |       20 |     37% |58, 61-64, 67-90, 98-99, 102-103, 106-107, 216-218, 271-\>277, 289-307, 319-337, 513, 675, 693-\>707, 695-696, 717, 730-731, 745-748, 779-870, 889-1096, 1109-1154, 1178-1182, 1204-1235, 1242-1342, 1363-1365, 1375-1399, 1406-1424, 1452-1491, 1494-1501, 1533, 1543-1546, 1549-1561, 1575-1578, 1582-\>1589, 1591, 1602, 1614, 1627-1662, 1665-1672, 1691, 1696-1699, 1702, 1767-1778, 1793-1809, 1826, 1835, 1853-1915, 1952-2052, 2087-2093 |
| src/pyefis/instruments/ai/svs\_gl.py                    |      799 |      660 |      188 |        5 |     16% |475-591, 691-719, 724, 731-748, 752-764, 775-798, 809-817, 826-965, 970, 976-1028, 1041-1078, 1087-1145, 1154-1233, 1240-1261, 1272-1325, 1338-1362, 1371-1391, 1404-1640, 1647-1653, 1657-1663, 1666-1709, 1712-1766, 1792-1833, 1871-\>1868, 1893, 1909-1911, 1926-1959 |
| src/pyefis/instruments/ai/water\_db.py                  |      157 |       10 |       40 |        7 |     91% |253, 255-259, 275, 349, 354-355, 384, 401 |
| src/pyefis/instruments/airspeed/\_\_init\_\_.py         |      436 |       21 |      102 |       10 |     94% |264-\>269, 376-\>384, 384-\>393, 481-\>518, 509, 511, 524-542, 549-\>566, 554, 560-561, 569-570 |
| src/pyefis/instruments/altimeter/\_\_init\_\_.py        |      329 |        4 |       76 |        6 |     98% |420, 428, 454, 499, 514-\>516, 519-\>exit |
| src/pyefis/instruments/button/\_\_init\_\_.py           |      248 |        0 |      106 |        1 |     99% |   51-\>54 |
| src/pyefis/instruments/checklist/\_\_init\_\_.py        |      285 |       10 |      104 |       14 |     94% |110, 112-\>114, 116-\>114, 302, 315-316, 332-\>exit, 337-\>exit, 342-\>exit, 347-\>exit, 352-\>exit, 357-\>exit, 387-389, 415, 435, 464-465, 474-\>exit |
| src/pyefis/instruments/data\_status/\_\_init\_\_.py     |      676 |       68 |      138 |       25 |     87% |82, 88-89, 109-111, 167-\>169, 241-246, 383, 415-418, 532-534, 544, 550-556, 559-564, 567-577, 600, 630-631, 642, 644, 665-668, 676, 681, 687, 696, 709-710, 719, 722, 723-\>exit, 732, 743-744, 765, 851-\>857, 855-\>857, 907-909, 940-941, 945-\>exit, 948-949 |
| src/pyefis/instruments/gauges/\_\_init\_\_.py           |        4 |        0 |        0 |        0 |    100% |           |
| src/pyefis/instruments/gauges/abstract.py               |      456 |        0 |      168 |        0 |    100% |           |
| src/pyefis/instruments/gauges/arc.py                    |      223 |        0 |       66 |        0 |    100% |           |
| src/pyefis/instruments/gauges/horizontalBar.py          |      131 |        0 |       34 |        0 |    100% |           |
| src/pyefis/instruments/gauges/numeric.py                |       60 |        0 |       10 |        0 |    100% |           |
| src/pyefis/instruments/gauges/verticalBar.py            |      245 |        0 |       72 |        0 |    100% |           |
| src/pyefis/instruments/helpers/\_\_init\_\_.py          |      156 |        2 |       28 |        4 |     97% |302, 314-\>335, 350, 351-\>362 |
| src/pyefis/instruments/hsi/\_\_init\_\_.py              |     1441 |      116 |      386 |       48 |     89% |193-194, 211-218, 225-226, 235-236, 245-246, 256-257, 266-267, 363-\>404, 501-\>507, 535-539, 560-\>572, 611-614, 635, 639, 644, 648, 651-654, 657-659, 662-663, 666-667, 670-671, 788-791, 793-796, 852-\>884, 881, 944, 948, 1035, 1071, 1090-1091, 1122-\>exit, 1154-1157, 1188, 1195, 1330-\>exit, 1333-\>1337, 1337-\>exit, 1341-\>exit, 1343-\>exit, 1347-\>exit, 1349-\>exit, 1353-\>exit, 1355-\>exit, 1360-1364, 1367-1369, 1372-1374, 1377-1379, 1382-\>exit, 1385, 1404, 1459, 1515-\>1517, 1621-\>1624, 1629-\>1641, 1654, 1691-\>1716, 1725-\>exit, 1758-1766, 1774, 1786, 1806, 1823-1832, 1983-1984, 2148-2149, 2152-2153, 2162, 2171-2173, 2177-\>2179 |
| src/pyefis/instruments/listbox/\_\_init\_\_.py          |      215 |        0 |       58 |        0 |    100% |           |
| src/pyefis/instruments/live\_binding.py                 |      103 |       29 |       34 |       11 |     71% |71, 81-83, 95-96, 108, 117, 129, 132-133, 140, 142, 145, 149-150, 157, 159-162, 165, 169-170, 174-175, 184, 188-189 |
| src/pyefis/instruments/map/\_\_init\_\_.py              |      326 |       32 |       64 |       13 |     87% |158, 163-164, 182, 210, 217-218, 286-287, 291, 345-\>exit, 352-\>367, 356, 358-359, 360-\>366, 371-377, 381-382, 393, 397-404, 411-\>413, 456, 480 |
| src/pyefis/instruments/map/layers/\_\_init\_\_.py       |       40 |        2 |        2 |        0 |     95% |    41, 44 |
| src/pyefis/instruments/map/layers/airports.py           |      138 |      104 |       38 |        2 |     20% |52-54, 57-58, 65-112, 120-137, 141-165, 168-193 |
| src/pyefis/instruments/map/layers/navaids.py            |      168 |      114 |       42 |        2 |     27% |43-44, 50-66, 69-96, 100-102, 113-114, 123-159, 172-173, 179-197, 210-211, 218-237 |
| src/pyefis/instruments/map/layers/rivers.py             |       14 |        0 |        0 |        0 |    100% |           |
| src/pyefis/instruments/map/layers/roads.py              |      161 |       44 |       38 |        7 |     69% |91-96, 111, 131, 133, 150-160, 163-187, 195, 229, 236 |
| src/pyefis/instruments/map/layers/terrain.py            |      242 |       75 |       46 |       10 |     67% |100-102, 109-116, 143, 145, 168-183, 186-210, 237-241, 295, 310-\>313, 315-\>285, 317-319, 341, 355, 379-400 |
| src/pyefis/instruments/misc/\_\_init\_\_.py             |      260 |       58 |       44 |        4 |     76% |167-173, 184-205, 220-221, 242-269, 301-302, 355-\>357 |
| src/pyefis/instruments/pa/\_\_init\_\_.py               |       63 |        0 |        6 |        0 |    100% |           |
| src/pyefis/instruments/tab\_section/\_\_init\_\_.py     |       55 |        5 |       12 |        1 |     91% |92, 125-126, 132-133 |
| src/pyefis/instruments/tc/\_\_init\_\_.py               |      227 |        0 |       42 |        0 |    100% |           |
| src/pyefis/instruments/vsi/\_\_init\_\_.py              |      407 |        1 |       74 |        1 |     99% |       455 |
| src/pyefis/instruments/weston/\_\_init\_\_.py           |       61 |        3 |       14 |        0 |     96% |     11-13 |
| src/pyefis/instruments/wind/\_\_init\_\_.py             |       97 |        0 |       12 |        0 |    100% |           |
| src/pyefis/main.py                                      |      176 |       13 |       62 |        0 |     94% |251, 253-263, 271-272 |
| src/pyefis/screens/\_\_init\_\_.py                      |        0 |        0 |        0 |        0 |    100% |           |
| src/pyefis/screens/instrument\_spec.py                  |      104 |       21 |       38 |       16 |     71% |109, 113, 140, 144, 148, 154, 158, 161, 163, 167, 187, 191, 206, 249, 255, 260, 266-269, 273 |
| src/pyefis/screens/screenbuilder.py                     |      204 |        0 |       72 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_config.py             |      135 |        0 |       78 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_display.py            |       31 |        0 |       14 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_encoder.py            |       89 |        0 |       46 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_factory.py            |      151 |       11 |       32 |        7 |     88% |98, 118, 134, 168, 169-\>171, 171-\>173, 179-185, 1309-\>1311 |
| src/pyefis/screens/screenbuilder\_layout.py             |      129 |        0 |       70 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_options.py            |       75 |        3 |       36 |        1 |     96% | 61, 68-69 |
| src/pyefis/screens/screenbuilder\_overlay.py            |       46 |        0 |       10 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_preferences.py        |       36 |        0 |       30 |        0 |    100% |           |
| src/pyefis/version.py                                   |        2 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                               | **13671** | **2434** | **3806** |  **259** | **81%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/billmallard/pyEfis/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/billmallard/pyEfis/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/billmallard/pyEfis/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/billmallard/pyEfis/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fbillmallard%2FpyEfis%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/billmallard/pyEfis/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.