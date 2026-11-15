# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/billmallard/pyEfis/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                    |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/pyefis/\_\_init\_\_.py                              |        1 |        0 |        0 |        0 |    100% |           |
| src/pyefis/advisories.py                                |      111 |        5 |       58 |        5 |     94% |57, 77-78, 82, 85, 169-\>166 |
| src/pyefis/cfg.py                                       |       79 |        0 |       70 |        0 |    100% |           |
| src/pyefis/common/\_\_init\_\_.py                       |       10 |        0 |        4 |        0 |    100% |           |
| src/pyefis/display\_metrics.py                          |       47 |        3 |       10 |        1 |     93% | 67-68, 70 |
| src/pyefis/editor/\_\_init\_\_.py                       |        0 |        0 |        0 |        0 |    100% |           |
| src/pyefis/editor/groups.py                             |       17 |       17 |        2 |        0 |      0% |     31-83 |
| src/pyefis/editor/resolver.py                           |       49 |        3 |       16 |        2 |     92% |57-\>60, 67-68, 89 |
| src/pyefis/editor/schema.py                             |       82 |       28 |       34 |        2 |     62% |143, 148-158, 163-166, 197-\>199, 251, 416-432, 436 |
| src/pyefis/fix\_watchdog.py                             |       78 |        2 |       16 |        1 |     97% |   115-116 |
| src/pyefis/flightplan/\_\_init\_\_.py                   |        0 |        0 |        0 |        0 |    100% |           |
| src/pyefis/flightplan/airac.py                          |       26 |        0 |        4 |        0 |    100% |           |
| src/pyefis/flightplan/airways.py                        |      119 |        1 |       34 |        3 |     97% |152-\>exit, 169-\>exit, 247 |
| src/pyefis/flightplan/catalog.py                        |       97 |        1 |       24 |        2 |     98% |77, 123-\>125 |
| src/pyefis/flightplan/fixbridge.py                      |      309 |        9 |       96 |        5 |     97% |422, 463, 472-473, 485, 563, 568-569, 572 |
| src/pyefis/flightplan/geo.py                            |       38 |        0 |        0 |        0 |    100% |           |
| src/pyefis/flightplan/leg\_paths.py                     |      253 |       14 |       60 |        9 |     93% |160, 163-\>174, 175, 261-\>265, 263-\>265, 300-305, 330-333, 359, 435 |
| src/pyefis/flightplan/model.py                          |      356 |       17 |      132 |       14 |     93% |126, 170, 227, 241, 259, 263-265, 283, 293, 310, 361, 376, 396, 418, 420, 546 |
| src/pyefis/flightplan/proc\_load.py                     |      284 |       15 |      156 |       17 |     91% |126, 170-\>172, 173-\>175, 213, 232, 237, 246-\>248, 257-\>259, 326-\>330, 337, 348, 351-\>354, 425, 464, 490-\>495, 491-\>493, 499-505 |
| src/pyefis/flightplan/procedures.py                     |      145 |        0 |       34 |        1 |     99% | 210-\>208 |
| src/pyefis/flightplan/refusal.py                        |       53 |        1 |       26 |        2 |     96% |84, 89-\>91 |
| src/pyefis/flightplan/waypoints.py                      |      368 |       22 |      100 |       18 |     91% |126, 153, 161-162, 202-203, 246-\>248, 248-\>250, 250-\>252, 260, 285, 291, 335-336, 349, 399-400, 406-407, 426, 448, 460, 514, 517-\>516, 546, 553 |
| src/pyefis/gui.py                                       |      348 |       16 |      114 |        5 |     95% |120-121, 286, 301-\>300, 311-\>310, 315-318, 354-355, 418-419, 435-436, 441, 448-449, 473 |
| src/pyefis/hmi/\_\_init\_\_.py                          |       13 |        0 |        2 |        0 |    100% |           |
| src/pyefis/hmi/actionclass.py                           |       45 |        0 |        6 |        0 |    100% |           |
| src/pyefis/hmi/data.py                                  |       77 |        0 |       36 |        0 |    100% |           |
| src/pyefis/hmi/functions.py                             |       30 |        1 |        2 |        1 |     94% |        47 |
| src/pyefis/hmi/keys.py                                  |       51 |        0 |       24 |        0 |    100% |           |
| src/pyefis/hmi/menu.py                                  |      176 |        0 |       50 |        0 |    100% |           |
| src/pyefis/hooks.py                                     |       14 |        0 |        4 |        0 |    100% |           |
| src/pyefis/install\_ack.py                              |       76 |       10 |       28 |        3 |     88% |63, 74-75, 80-81, 83, 154-156, 160 |
| src/pyefis/instruments/NumericalDisplay/\_\_init\_\_.py |      219 |        1 |       50 |        1 |     99% |       201 |
| src/pyefis/instruments/\_\_init\_\_.py                  |        0 |        0 |        0 |        0 |    100% |           |
| src/pyefis/instruments/about/\_\_init\_\_.py            |      229 |       11 |       58 |        9 |     93% |128-\>130, 130-\>132, 132-\>118, 142, 167-\>169, 290-291, 294, 297, 322-323, 327-\>exit, 330-331, 355-356 |
| src/pyefis/instruments/ai/\_\_init\_\_.py               |        9 |        1 |        2 |        0 |     91% |        43 |
| src/pyefis/instruments/ai/ai\_widget.py                 |     1136 |      108 |      280 |       35 |     89% |385-388, 437, 482, 493-529, 535-542, 549-559, 563-571, 599-602, 605-\>611, 806-809, 832-\>850, 842-\>846, 894, 896, 898, 902-905, 908-910, 929-931, 940-\>exit, 948-\>exit, 954-\>exit, 963-\>exit, 992-\>994, 1054, 1100, 1249-1252, 1259, 1266-\>1273, 1275-1279, 1296, 1306, 1369, 1443, 1484, 1501-1507, 1747-1748, 1807-1808, 1813-\>1816, 1819-1820, 1824, 1833 |
| src/pyefis/instruments/ai/airport\_db.py                |      161 |       10 |       42 |        5 |     93% |124-126, 135, 152, 159, 193, 198, 233-234 |
| src/pyefis/instruments/ai/camera.py                     |       46 |        0 |        6 |        0 |    100% |           |
| src/pyefis/instruments/ai/highway\_db.py                |       81 |        5 |       24 |        2 |     93% |80-82, 98, 142 |
| src/pyefis/instruments/ai/obstacle\_db.py               |       66 |       30 |       14 |        1 |     46% |49-53, 58, 68-74, 78, 84-108 |
| src/pyefis/instruments/ai/pose.py                       |       54 |        0 |       14 |        1 |     99% |   85-\>88 |
| src/pyefis/instruments/ai/road\_ribbon.py               |      184 |        4 |       20 |        3 |     97% |66-67, 143, 208-\>203, 265 |
| src/pyefis/instruments/ai/svs.py                        |     1353 |      572 |      410 |       37 |     54% |66, 78-81, 108, 110, 121-122, 125-126, 129-130, 227-229, 255, 264-266, 326-\>332, 349-351, 356-\>362, 360-361, 384-\>390, 388-389, 414-421, 450-451, 909, 929-930, 966-967, 983, 1015-1103, 1122-1329, 1342-1384, 1408-1412, 1434-1465, 1472-1572, 1593-1594, 1609-1611, 1613, 1614-\>1629, 1622-1623, 1649-\>exit, 1699-1735, 1743-1744, 1788-1791, 1794-1806, 1823, 1836, 1872, 1909-1944, 1955-1958, 1962-1963, 1997, 2003-2006, 2031, 2034, 2087-2095, 2116, 2124-\>2118, 2126, 2143, 2152, 2170-2232, 2281, 2300, 2308, 2420-2518, 2553-2559 |
| src/pyefis/instruments/ai/svs\_gl.py                    |      816 |      647 |      198 |        5 |     19% |494-610, 712-717, 745, 752-769, 773-785, 840-848, 857-997, 1002, 1008-1060, 1073-1110, 1119-1177, 1186-1265, 1272-1293, 1304-1357, 1370-1394, 1403-1423, 1436-1703, 1710-1716, 1720-1726, 1729-1772, 1782-1836, 1862-1903, 1941-\>1938, 1963, 1979-1981, 1996-2029 |
| src/pyefis/instruments/ai/water\_db.py                  |      160 |        4 |       40 |        4 |     96% |265, 368, 408, 426 |
| src/pyefis/instruments/airspeed/\_\_init\_\_.py         |      464 |       20 |      116 |        7 |     95% |381-\>389, 389-\>398, 468, 543-561, 568-\>585, 573, 579-580, 588-589 |
| src/pyefis/instruments/altimeter/\_\_init\_\_.py        |      735 |       25 |      208 |       30 |     94% |511, 532, 563, 615, 630-633, 642-\>648, 649-\>exit, 660-\>exit, 684-\>686, 686-\>690, 688-689, 749-\>752, 754-755, 766-767, 791, 819-\>822, 830-831, 877, 892-\>894, 897-\>exit, 947, 973-\>975, 976-\>978, 1008-\>exit, 1016, 1017-\>1020, 1040, 1059, 1081, 1098, 1110-\>1112, 1112-\>1114, 1135 |
| src/pyefis/instruments/altimeter/altsel.py              |      110 |        5 |       22 |        5 |     92% |96, 102, 110, 171, 189 |
| src/pyefis/instruments/button/\_\_init\_\_.py           |      250 |        0 |      106 |        0 |    100% |           |
| src/pyefis/instruments/checklist/\_\_init\_\_.py        |      289 |       10 |      104 |       14 |     94% |111, 113-\>115, 117-\>115, 306, 319-320, 336-\>exit, 341-\>exit, 346-\>exit, 351-\>exit, 356-\>exit, 361-\>exit, 391-393, 419, 439, 480-481, 490-\>exit |
| src/pyefis/instruments/data\_status/\_\_init\_\_.py     |      873 |       60 |      170 |       30 |     90% |113-\>116, 128, 134-135, 155-157, 214-\>216, 288-293, 430, 462-465, 571-\>exit, 675-677, 681-\>exit, 684-685, 728, 734-740, 743-748, 752, 759, 815-816, 827, 829, 850-853, 861, 866, 872, 881, 899-900, 909, 915, 916-\>exit, 925, 936-937, 958, 992, 994-\>996, 1105-\>1111, 1109-\>1111, 1235-\>exit, 1238-1239 |
| src/pyefis/instruments/edit\_focus.py                   |      176 |        9 |       50 |        7 |     92% |71, 220, 248-\>257, 262, 265, 269-273, 307-\>exit, 322-\>324 |
| src/pyefis/instruments/flight\_plan/\_\_init\_\_.py     |     3163 |      495 |      840 |      156 |     82% |429, 439-440, 467, 470-\>exit, 498, 512-513, 526-536, 560, 574, 620, 624-\>626, 636, 751, 766-767, 797-800, 806-807, 820-822, 830, 832, 853, 861-863, 868-872, 876-\>878, 883-886, 912, 928-929, 932-933, 965-\>968, 975, 978-981, 999-1000, 1008-1010, 1015-\>exit, 1019-1024, 1044-\>1043, 1047, 1061-1064, 1100-1101, 1109-1111, 1136, 1144-1147, 1279-1281, 1320-\>exit, 1338-1341, 1358-\>1361, 1367-\>1369, 1381, 1384, 1405, 1408-1417, 1424-1425, 1434-1438, 1441-1442, 1445-1449, 1452-\>1455, 1459-1464, 1507, 1546, 1558-1560, 1564, 1577, 1582, 1590-1592, 1599, 1621, 1623, 1641, 1652-1653, 1659-1666, 1673, 1677-1678, 1680, 1693-1694, 1726, 1729, 1757-1767, 1770-1771, 1774-1775, 1784, 1787, 1804-1808, 1819-1821, 1827-1831, 1847-1850, 1861-1864, 1873-1874, 1887-1888, 1897, 1926, 1936-1937, 1946-1951, 1954-1958, 1961-1965, 1970, 1975-1976, 1988, 1992, 1995-1996, 2031-2033, 2042-2044, 2050-2051, 2069-2071, 2080-2082, 2089-2090, 2112, 2116, 2121, 2122-\>exit, 2126-2129, 2133-2134, 2136-2144, 2145-\>exit, 2150, 2152, 2154, 2155-\>exit, 2159-2166, 2169-2176, 2190, 2192, 2194, 2196, 2200-2202, 2238-\>2243, 2253-\>2261, 2255-\>2261, 2258, 2269, 2302-2303, 2348, 2350, 2375-\>2382, 2403-\>2405, 2440, 2442, 2446, 2454, 2456, 2458, 2460, 2462, 2468, 2470, 2589-2590, 2593-\>2595, 2600, 2605-2606, 2608, 2620, 2643-2645, 2659, 2674, 2692, 2697-\>exit, 2737-2738, 2809-2810, 2832, 2844, 2846, 2902, 2906, 2913, 2969-\>exit, 3011-\>3016, 3038-3040, 3051-3054, 3067, 3155-\>3158, 3204, 3323, 3331-\>exit, 3341-\>exit, 3468-3471, 3496, 3513, 3558-\>3564, 3603-3611, 3631-\>3635, 3641-3645, 3704, 3706, 3708, 3712, 3745-3749, 3767-\>3770, 3771, 3773, 3795, 3797, 3830-\>exit, 3837-3841, 3849, 3855, 3879, 3888-\>3892, 3930, 3946, 4006, 4009, 4021, 4025-\>4031, 4046-4047, 4073-4087, 4090-4098, 4101-4110, 4116-4121, 4130, 4135-4136, 4155-4165, 4168-4170, 4173-4182, 4186-4238, 4258-4259, 4302-4309, 4322, 4365-4369 |
| src/pyefis/instruments/gauges/\_\_init\_\_.py           |        4 |        0 |        0 |        0 |    100% |           |
| src/pyefis/instruments/gauges/abstract.py               |      524 |        4 |      196 |        5 |     99% |563, 574, 582-583 |
| src/pyefis/instruments/gauges/arc.py                    |      223 |        0 |       66 |        0 |    100% |           |
| src/pyefis/instruments/gauges/horizontalBar.py          |      131 |        0 |       34 |        0 |    100% |           |
| src/pyefis/instruments/gauges/numeric.py                |       62 |        0 |       10 |        0 |    100% |           |
| src/pyefis/instruments/gauges/verticalBar.py            |      245 |        0 |       72 |        0 |    100% |           |
| src/pyefis/instruments/helpers/\_\_init\_\_.py          |      222 |        5 |       40 |        7 |     95% |125, 161, 220, 454, 466-\>487, 502, 503-\>514 |
| src/pyefis/instruments/helpers/bugs.py                  |       71 |        2 |       16 |        0 |     98% |     73-74 |
| src/pyefis/instruments/hsi/\_\_init\_\_.py              |     1781 |      103 |      484 |       52 |     92% |258-265, 272-273, 303-304, 325-326, 443-\>501, 603-\>609, 637-641, 662-\>674, 713-\>exit, 716, 719-\>exit, 741, 745, 750, 754, 757-760, 763-765, 768-769, 772-773, 776-777, 894-897, 899-902, 987, 1133, 1169, 1231-\>1238, 1283-1286, 1335, 1345, 1416, 1616-\>exit, 1634-\>exit, 1636-\>exit, 1640-\>exit, 1642-\>exit, 1646-\>exit, 1648-\>exit, 1692-\>exit, 1694-\>exit, 1699-1703, 1706-1708, 1711-1713, 1716-1718, 1721-\>exit, 1744, 1789, 1835, 1852, 1916-\>1918, 2021-\>2024, 2029-\>2041, 2231-\>2240, 2256-\>2264, 2286-2287, 2296, 2317-2318, 2324-2325, 2344-\>2338, 2353, 2356-2357, 2366-2367, 2374, 2379, 2400, 2404-2405, 2433, 2447-2448, 2605-2606, 2770-2771, 2774-2775, 2784, 2793-2795, 2799-\>2801 |
| src/pyefis/instruments/listbox/\_\_init\_\_.py          |      218 |        0 |       58 |        0 |    100% |           |
| src/pyefis/instruments/live\_binding.py                 |      122 |       31 |       42 |       12 |     74% |71, 81-83, 95-96, 108-\>107, 129, 138, 150, 153-154, 161, 163, 166, 170-171, 178, 180-183, 186, 190-191, 195-196, 213-214, 225, 229-230 |
| src/pyefis/instruments/map/\_\_init\_\_.py              |     1088 |       82 |      274 |       45 |     90% |77, 84-85, 405, 410-412, 425, 445-446, 452, 510-\>exit, 598, 605-606, 732, 735-736, 761, 766, 790, 798, 808, 810, 815, 852-\>exit, 854-\>exit, 875-876, 880, 937-\>exit, 955-959, 962-\>960, 973-\>972, 997, 1003-\>exit, 1025-\>1027, 1030-1031, 1051, 1068, 1071-1072, 1083-1085, 1094, 1097, 1098-\>1100, 1107, 1108-\>1110, 1143-\>exit, 1162-1163, 1168-1169, 1225-1226, 1228, 1238-\>1256, 1276, 1284-1285, 1316, 1334, 1341-\>1344, 1373, 1402, 1468, 1541, 1579, 1589, 1596, 1736-1760 |
| src/pyefis/instruments/map/layers/\_\_init\_\_.py       |      245 |        8 |       48 |        3 |     96% |184-185, 233, 300, 303, 306, 351, 354 |
| src/pyefis/instruments/map/layers/airports.py           |      288 |       33 |      102 |       17 |     85% |97-100, 111-125, 127, 143-\>161, 145-\>149, 152-\>158, 169, 179, 199, 203, 215, 238, 265, 281, 330, 355-356, 380-387, 402 |
| src/pyefis/instruments/map/layers/flight\_plan.py       |      597 |       45 |      220 |       27 |     91% |145-146, 288, 358, 373-374, 383-\>387, 385-\>387, 424, 462-\>466, 626-\>637, 630-633, 666, 673, 678, 682, 694-695, 716, 739, 750-754, 758, 764-769, 777, 874-\>877, 900, 903, 905, 923, 927, 953-960, 972-973 |
| src/pyefis/instruments/map/layers/navaids.py            |      224 |       51 |       62 |        4 |     75% |54-57, 73-83, 107-108, 136-142, 147-149, 161-162, 234-235, 244-\>242, 251, 284-285, 292-311 |
| src/pyefis/instruments/map/layers/rivers.py             |       17 |        0 |        0 |        0 |    100% |           |
| src/pyefis/instruments/map/layers/roads.py              |      290 |       30 |       84 |       10 |     88% |97, 154, 243-248, 278-281, 292, 297-310, 324-325, 350, 356-\>exit, 365, 399, 444 |
| src/pyefis/instruments/map/layers/terrain.py            |      398 |       25 |       88 |       15 |     92% |69, 197-199, 262-\>264, 282-283, 315-\>exit, 356-360, 470, 481, 486-\>489, 490-\>463, 492-496, 497-\>505, 565, 579, 593-\>596, 598-\>553, 600-602, 621-622, 624, 731-\>736 |
| src/pyefis/instruments/map/layers/traffic.py            |      307 |       30 |       98 |       10 |     88% |188-\>197, 222-\>exit, 283, 293-294, 317, 330-\>exit, 337-\>exit, 343-353, 366, 382-\>exit, 403, 463-475 |
| src/pyefis/instruments/map/nd.py                        |      377 |       21 |       92 |        7 |     94% |171-\>177, 173-\>176, 282-283, 338-339, 350-\>360, 358-359, 362-\>365, 398-399, 407-408, 660, 669-\>675, 676-686 |
| src/pyefis/instruments/map/perf.py                      |      145 |        3 |       24 |        3 |     96% |61, 174, 181-\>exit, 253 |
| src/pyefis/instruments/map/raster.py                    |       64 |        0 |       14 |        0 |    100% |           |
| src/pyefis/instruments/misc/\_\_init\_\_.py             |      260 |       58 |       44 |        4 |     76% |167-173, 184-205, 220-221, 242-269, 301-302, 355-\>357 |
| src/pyefis/instruments/nav\_status/\_\_init\_\_.py      |      208 |        2 |       66 |        6 |     97% |248-\>250, 250-\>252, 252-\>257, 257-\>259, 259-\>261, 273-\>272, 320-321 |
| src/pyefis/instruments/pa/\_\_init\_\_.py               |       63 |        0 |        6 |        0 |    100% |           |
| src/pyefis/instruments/tab\_section/\_\_init\_\_.py     |      148 |        7 |       46 |        5 |     93% |99-\>104, 131, 145, 184-\>183, 186-188, 282-283 |
| src/pyefis/instruments/tc/\_\_init\_\_.py               |      227 |        0 |       42 |        0 |    100% |           |
| src/pyefis/instruments/vsi/\_\_init\_\_.py              |      469 |        2 |       82 |        1 |     99% |  420, 498 |
| src/pyefis/instruments/weston/\_\_init\_\_.py           |       61 |        3 |       14 |        0 |     96% |     11-13 |
| src/pyefis/instruments/wind/\_\_init\_\_.py             |       97 |        0 |       12 |        0 |    100% |           |
| src/pyefis/kiosk.py                                     |      162 |        7 |       40 |        6 |     94% |149, 192-\>exit, 228, 235, 239, 241, 271-272 |
| src/pyefis/main.py                                      |      199 |       15 |       70 |        2 |     93% |300, 304-318, 331-332, 339 |
| src/pyefis/screens/\_\_init\_\_.py                      |        0 |        0 |        0 |        0 |    100% |           |
| src/pyefis/screens/color\_tokens.py                     |       67 |        2 |       34 |        3 |     95% |121, 129-\>122, 139 |
| src/pyefis/screens/instrument\_spec.py                  |      131 |       16 |       62 |       15 |     84% |116, 120, 163, 194, 198, 204, 208, 211, 213, 244, 248, 263, 306, 312, 323, 336 |
| src/pyefis/screens/screenbuilder.py                     |      231 |        6 |       74 |        1 |     98% |50-53, 59-60 |
| src/pyefis/screens/screenbuilder\_config.py             |      135 |        0 |       78 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_display.py            |       31 |        0 |       14 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_encoder.py            |      248 |       22 |      112 |       10 |     91% |150-152, 163, 218-\>exit, 231-232, 237-238, 244, 257-258, 288-\>exit, 326-329, 338, 346-347, 357, 366, 379-380 |
| src/pyefis/screens/screenbuilder\_factory.py            |      177 |        5 |       40 |        8 |     94% |102, 193, 203, 204-\>206, 207, 217-\>219, 220, 1776-\>1778 |
| src/pyefis/screens/screenbuilder\_layout.py             |      129 |        0 |       70 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_options.py            |      125 |        5 |       54 |        1 |     97% |61, 68-69, 157-158 |
| src/pyefis/screens/screenbuilder\_overlay.py            |       46 |        0 |       10 |        0 |    100% |           |
| src/pyefis/screens/screenbuilder\_preferences.py        |       39 |        0 |       30 |        0 |    100% |           |
| src/pyefis/startup\_notice.py                           |      129 |        2 |       24 |        2 |     97% |  179, 235 |
| src/pyefis/version.py                                   |        2 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                               | **24953** | **2807** | **7064** |  **724** | **87%** |           |


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