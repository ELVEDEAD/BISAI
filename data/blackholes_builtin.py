"""
blackholes_builtin.py —— 已知黑洞精选数据集

来源：NASA/Chandra X-ray Center、ESA Gaia、LIGO/Virgo 等公开数据
用途：作为「黑洞」类型天体加入场景，参与引力网格下陷（时空扭曲效果）
字段：(名称, 英文名, 质量[太阳质量], 距离[pc], RA[度], Dec[度], 发现年份, 类型, 数据来源)

说明：所有数据为公开确认值；缺失项标 None，不伪造。
"""

BUILTIN_BLACKHOLES = [
    # —— 恒星级黑洞 ——
    {
        "name": "天鹅座 X-1",
        "en_name": "Cygnus X-1",
        "mass_solar": 21.2,
        "dist_pc": 2120.0,
        "ra_deg": 299.59,
        "dec_deg": 35.20,
        "disc_year": 1971,
        "bh_type": "恒星级黑洞（X射线双星）",
        "data_source": "NASA/Chandra + Gaia DR3（21.2 M☉，2.12 kpc）",
    },
    {
        "name": "麒麟座 V616",
        "en_name": "V616 Monocerotis (A0620-00)",
        "mass_solar": 11.0,
        "dist_pc": 990.0,
        "ra_deg": 97.67,
        "dec_deg": -9.93,
        "disc_year": 1975,
        "bh_type": "恒星级黑洞（X射线暂现源）",
        "data_source": "NASA/Chandra（~11 M☉，~1 kpc）",
    },
    {
        "name": "Gaia BH1",
        "en_name": "Gaia BH1",
        "mass_solar": 9.78,
        "dist_pc": 480.0,
        "ra_deg": 277.41,
        "dec_deg": -6.16,
        "disc_year": 2022,
        "bh_type": "恒星级黑洞（休眠双星）",
        "data_source": "ESA Gaia DR3（9.78 M☉，480 pc，已知最近黑洞之一）",
    },
    {
        "name": "Gaia BH2",
        "en_name": "Gaia BH2",
        "mass_solar": 8.93,
        "dist_pc": 1160.0,
        "ra_deg": 130.06,
        "dec_deg": -57.15,
        "disc_year": 2023,
        "bh_type": "恒星级黑洞（休眠双星）",
        "data_source": "ESA Gaia DR3（8.93 M☉，1.16 kpc）",
    },
    {
        "name": "GRO J1655-40",
        "en_name": "GRO J1655-40",
        "mass_solar": 6.3,
        "dist_pc": 1100.0,
        "ra_deg": 254.29,
        "dec_deg": -39.85,
        "disc_year": 1994,
        "bh_type": "恒星级黑洞（微类星体）",
        "data_source": "NASA/Chandra（6.3 M☉，~1.1 kpc）",
    },
    # —— 中等质量黑洞候选 ——
    {
        "name": "M82 X-1",
        "en_name": "M82 X-1",
        "mass_solar": 400.0,
        "dist_pc": 3500000.0,
        "ra_deg": 148.97,
        "dec_deg": 69.68,
        "disc_year": 2001,
        "bh_type": "中等质量黑洞候选（超亮X射线源）",
        "data_source": "NASA/Chandra（~400 M☉，~3.5 Mpc，M82 星系）",
    },
    # —— 超大质量黑洞 ——
    {
        "name": "人马座 A*",
        "en_name": "Sagittarius A* (Sgr A*)",
        "mass_solar": 4300000.0,
        "dist_pc": 8122.0,
        "ra_deg": 266.42,
        "dec_deg": -29.01,
        "disc_year": 1974,
        "bh_type": "超大质量黑洞（银河系中心）",
        "data_source": "ESO/VLT GRAVITY + EHT（4.3×10⁶ M☉，8.122 kpc）",
    },
    {
        "name": "M87*",
        "en_name": "M87*",
        "mass_solar": 6500000000.0,
        "dist_pc": 16400000.0,
        "ra_deg": 187.71,
        "dec_deg": 12.39,
        "disc_year": 1918,
        "bh_type": "超大质量黑洞（EHT 首张黑洞照片）",
        "data_source": "EHT Event Horizon Telescope（6.5×10⁹ M☉，16.4 Mpc，M87 星系）",
    },
]
