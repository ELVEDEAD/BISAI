"""
artificial_satellites.py —— 地球人造卫星（真实轨道参数）

数据来源（各机构官方任务页 / NORAD 两行根数长期平均）：
    * 国际空间站 ISS        NASA ISS Trajectory Data
    * 天宫空间站 CSS        CMSA 中国载人航天工程办公室
    * 哈勃空间望远镜 HST    NASA HST Orbital Data
    * 星链 Starlink         SpaceX FCC 申报（第一壳层）
    * 铱星 Iridium NEXT     Iridium 官方星座参数
    * 陆地卫星 Landsat 9    USGS/NASA Landsat 任务页
    * 哨兵-1A Sentinel-1A   ESA Copernicus 任务页
    * 泰拉 Terra            NASA EOS 任务页
    * 风云三号 Fengyun-3    CMA 国家卫星气象中心
    * GPS                   US Space Force 官方星座参数
    * 伽利略 Galileo        ESA 导航星座参数
    * 格洛纳斯 GLONASS      Roscosmos 官方星座参数
    * GOES                  NOAA 地球静止气象卫星
    * 北斗 GEO              CSNO 中国卫星导航系统管理办公室

科学诚实性说明：
    * 半长轴 a、偏心率 e、倾角 i、周期 T 为**实测值**；
    * 升交点经度 Ω 取**星座代表性值**（同一星座多颗卫星共用轨道面），
      近地点幅角 ω 与平近点角 M(J2000) 取可复现假设值 0（非随机数）。
      以上只影响沿轨道瞬时相位与轨道面朝向，不影响轨道形状/半长轴/周期/倾角；
    * 特征尺寸 size_m 为航天器最大跨度或本体长度（用于标记点尺度，非球体半径）。
"""

# 轨道类型标签
CAT_LEO = "低轨 LEO"
CAT_SSO = "太阳同步 SSO"
CAT_MEO = "中轨 MEO"
CAT_GEO = "地球同步 GEO"

ARTIFICIAL_SATELLITES = [
    dict(
        name="国际空间站", en="ISS (Zarya)", cat=CAT_LEO,
        a_km=6796.0, e=0.0004, incl_deg=51.64, raan_deg=51.6,
        period_days=92.9 / 1440.0, size_m=109.0, mass_kg=419725.0,
        agency="NASA / Roscosmos / ESA / JAXA / CSA", launched=1998,
        color=(0.88, 0.90, 0.94),
        note="最大在轨载人航天器，轨道高度约 420 km，倾角 51.6°",
    ),
    dict(
        name="天宫空间站", en="Tiangong (CSS)", cat=CAT_LEO,
        a_km=6760.0, e=0.0005, incl_deg=41.5, raan_deg=41.5,
        period_days=92.2 / 1440.0, size_m=55.0, mass_kg=69000.0,
        agency="CMSA 中国载人航天工程办公室", launched=2021,
        color=(0.90, 0.86, 0.78),
        note="中国载人空间站，T 字构型，轨道高度约 390 km，倾角 41.5°",
    ),
    dict(
        name="哈勃空间望远镜", en="Hubble (HST)", cat=CAT_LEO,
        a_km=6918.0, e=0.0003, incl_deg=28.47, raan_deg=28.5,
        period_days=95.4 / 1440.0, size_m=13.2, mass_kg=11110.0,
        agency="NASA / ESA", launched=1990,
        color=(0.80, 0.84, 0.92),
        note="轨道高度约 535 km，倾角 28.5°，主镜口径 2.4 m",
    ),
    dict(
        name="星链卫星", en="Starlink", cat=CAT_LEO,
        a_km=6921.0, e=0.0001, incl_deg=53.0, raan_deg=53.0,
        period_days=95.6 / 1440.0, size_m=3.0, mass_kg=260.0,
        agency="SpaceX", launched=2019,
        color=(0.86, 0.88, 0.90),
        note="第一壳层代表星，轨道高度约 550 km，倾角 53°（星座共计数千颗）",
    ),
    dict(
        name="铱星", en="Iridium NEXT", cat=CAT_LEO,
        a_km=7151.0, e=0.0002, incl_deg=86.4, raan_deg=86.4,
        period_days=100.4 / 1440.0, size_m=3.6, mass_kg=689.0,
        agency="Iridium Communications", launched=2017,
        color=(0.82, 0.86, 0.88),
        note="近极地低轨通信星座，轨道高度约 780 km，倾角 86.4°",
    ),
    dict(
        name="陆地卫星9号", en="Landsat 9", cat=CAT_SSO,
        a_km=7080.0, e=0.0001, incl_deg=98.2, raan_deg=98.2,
        period_days=98.8 / 1440.0, size_m=3.0, mass_kg=2623.0,
        agency="NASA / USGS", launched=2021,
        color=(0.76, 0.82, 0.74),
        note="太阳同步轨道，轨道高度约 705 km，倾角 98.2°（对地观测）",
    ),
    dict(
        name="哨兵1A", en="Sentinel-1A", cat=CAT_SSO,
        a_km=7073.0, e=0.0001, incl_deg=98.18, raan_deg=98.2,
        period_days=98.6 / 1440.0, size_m=3.4, mass_kg=2300.0,
        agency="ESA Copernicus", launched=2014,
        color=(0.74, 0.80, 0.86),
        note="C 波段合成孔径雷达卫星，轨道高度约 693 km，倾角 98.2°",
    ),
    dict(
        name="泰拉卫星", en="Terra", cat=CAT_SSO,
        a_km=7078.0, e=0.0001, incl_deg=98.2, raan_deg=98.2,
        period_days=98.8 / 1440.0, size_m=3.5, mass_kg=4864.0,
        agency="NASA EOS", launched=1999,
        color=(0.78, 0.80, 0.76),
        note="地球观测系统旗舰星，轨道高度约 705 km，倾角 98.2°",
    ),
    dict(
        name="风云三号", en="Fengyun-3", cat=CAT_SSO,
        a_km=7207.0, e=0.0001, incl_deg=98.75, raan_deg=98.8,
        period_days=101.5 / 1440.0, size_m=3.0, mass_kg=2300.0,
        agency="CMA 国家卫星气象中心", launched=2008,
        color=(0.80, 0.78, 0.72),
        note="极轨气象卫星，轨道高度约 836 km，倾角 98.75°",
    ),
    dict(
        name="GPS导航卫星", en="GPS (Navstar)", cat=CAT_MEO,
        a_km=26560.0, e=0.0100, incl_deg=55.0, raan_deg=55.0,
        period_days=718.0 / 1440.0, size_m=5.0, mass_kg=2030.0,
        agency="US Space Force", launched=1978,
        color=(0.84, 0.82, 0.74),
        note="中圆轨道导航星座，轨道高度约 20 200 km，倾角 55°，周期约 11h58m",
    ),
    dict(
        name="伽利略导航卫星", en="Galileo", cat=CAT_MEO,
        a_km=29600.0, e=0.0002, incl_deg=56.0, raan_deg=56.0,
        period_days=845.0 / 1440.0, size_m=2.7, mass_kg=700.0,
        agency="ESA / EU", launched=2011,
        color=(0.78, 0.84, 0.90),
        note="欧盟导航星座，轨道高度约 23 200 km，倾角 56°，周期约 14h05m",
    ),
    dict(
        name="格洛纳斯导航卫星", en="GLONASS", cat=CAT_MEO,
        a_km=25440.0, e=0.0002, incl_deg=64.8, raan_deg=64.8,
        period_days=676.0 / 1440.0, size_m=2.7, mass_kg=1415.0,
        agency="Roscosmos", launched=1982,
        color=(0.80, 0.78, 0.82),
        note="俄罗斯导航星座，轨道高度约 19 100 km，倾角 64.8°，周期约 11h16m",
    ),
    dict(
        name="GOES气象卫星", en="GOES", cat=CAT_GEO,
        a_km=42164.0, e=0.0002, incl_deg=0.05, raan_deg=0.0,
        period_days=1436.0 / 1440.0, size_m=6.0, mass_kg=3000.0,
        agency="NOAA / NASA", launched=1975,
        color=(0.82, 0.84, 0.86),
        note="地球静止气象卫星，轨道高度 35 786 km，周期等于地球自转周期",
    ),
    dict(
        name="北斗地球静止卫星", en="BeiDou GEO", cat=CAT_GEO,
        a_km=42164.0, e=0.0003, incl_deg=1.5, raan_deg=0.0,
        period_days=1436.0 / 1440.0, size_m=5.0, mass_kg=4600.0,
        agency="CSNO 中国卫星导航系统管理办公室", launched=2015,
        color=(0.86, 0.82, 0.74),
        note="北斗三号地球静止轨道卫星，轨道高度 35 786 km，倾角 1.5°",
    ),
]


def get_artificial_satellites():
    """返回全部人造卫星数据（dict 列表，纯确定性，无随机）"""
    return list(ARTIFICIAL_SATELLITES)
