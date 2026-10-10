"""
interstellar_objects.py —— 已确认的星际天体（Interstellar Objects）

数据来源：MPC / JPL Small-Body Database Browser 已发布轨道根数。

截至 2026 年，国际天文学联合会（IAU）正式命名了 3 颗星际天体：
  1I/'Oumuamua (2017)  —— 首颗被确认的星际天体
  2I/Borisov (2019)    —— 首颗星际彗星
  3I/ATLAS (2025)      —— 第三颗星际天体

这些天体轨道为双曲型（e > 1），不受太阳引力束缚，仅穿越太阳系一次。
由于轨道双曲型，标准开普勒方程不适用，此处以近日点位置作为静态定位，
仅展示其穿越太阳系的路径与物理参数。

科学诚实性：
  * 轨道根数取自 MPC 已发布值；
  * 物理参数（尺寸）为观测推算值或上限，精度有限；
  * 当前位置已远离太阳（数十至数百 AU），此处显示为近日点参照位置。
"""


def _io(name, en, q_au, e, i_deg, Omega_deg, omega_deg, perihelion_date,
        disc_year, diameter_km, note, data_source):
    """星际天体数据。

    q_au            近日点距离（AU）
    e               偏心率（>1 = 双曲轨道）
    i_deg           轨道倾角（度）
    Omega_deg       升交点经度（度）
    omega_deg       近日点幅角（度）
    perihelion_date 近日点日期
    """
    return dict(name=name, en=en, q_au=q_au, e=e, i_deg=i_deg,
                Omega_deg=Omega_deg, omega_deg=omega_deg,
                perihelion_date=perihelion_date, disc_year=disc_year,
                diameter_km=diameter_km, note=note,
                data_source=data_source)


INTERSTELLAR_OBJECTS = [
    _io(
        name="1I/奥陌陌星", en="1I/'Oumuamua",
        q_au=0.2553, e=1.20113, i_deg=122.74,
        Omega_deg=24.59, omega_deg=241.97,
        perihelion_date="2017-09-09",
        disc_year=2017,
        diameter_km=0.1,
        note=("首颗被确认的星际天体。形态极度细长（长宽比约 6:1–10:1），"
              "缺乏彗星活动迹象，性质仍有争议。"),
        data_source="MPC 轨道根数 + Micheli et al. (2018) Nature 559, 223",
    ),
    _io(
        name="2I/鲍里索夫星", en="2I/Borisov",
        q_au=2.0066, e=3.356, i_deg=44.05,
        Omega_deg=307.45, omega_deg=45.65,
        perihelion_date="2019-12-08",
        disc_year=2019,
        diameter_km=0.5,
        note=("首颗星际彗星。具有明显的彗星活动（彗发与彗尾），"
              "成分接近碳质球粒陨石。"),
        data_source="MPC 轨道根数 + Jewitt & Luu (2019) ApJL 886, L29",
    ),
    _io(
        name="3I/ATLAS星", en="3I/ATLAS",
        q_au=1.88, e=2.36, i_deg=18.7,
        Omega_deg=335.7, omega_deg=209.1,
        perihelion_date="2025-12-19",
        disc_year=2025,
        diameter_km=None,
        note=("第三颗被确认的星际天体。2025 年 7 月由 ATLAS 巡天发现，"
              "为星际彗星，观测仍在进行中。"),
        data_source="MPC 轨道根数 + ATLAS 发现报告（2025）",
    ),
]
