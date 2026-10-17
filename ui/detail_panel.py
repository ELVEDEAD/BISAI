"""
detail_panel.py —— 天体详情面板（模块 H）

显示选中天体的完整数据（缺失字段显示"未知"，不伪造）：
    名称/类型/精度等级、轨道根数（a/e/i/Ω/ω/周期）、
    物理参数（半径/质量）、发现信息（年份/方法）、距离、数据来源
并提供：聚焦 / 加入对比 / 尺寸对比（模块 M）入口
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QGridLayout,
                             QLabel, QPushButton, QFrame, QScrollArea)
from data.loader import BODY_TYPE_LABELS
from core.constants import (GRADE_DESCRIPTION, format_distance, AU_KM,
                            R_EARTH_KM, M_EARTH_KG)
from ui import style
from core.i18n import tr

M_SUN_PER_EARTH = 332946.0


def _fmt(v, fmt="{:.6g}", suffix=""):
    if v is None:
        return tr("未知")
    try:
        return fmt.format(v) + suffix
    except (TypeError, ValueError):
        return tr("未知")


class DetailPanel(QWidget):
    """天体详情面板"""

    def __init__(self, viewport=None, compare_panel=None, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self.compare_panel = compare_panel
        self.exo_obs_panel = None      # 由主窗口注入（观测特征面板）
        self.sky_panel = None          # 由主窗口注入（地面视角面板）
        self.surface_panel = None      # 由主窗口注入（地表视角面板）
        self.right_tabs = None         # 由主窗口注入（右侧标签容器）
        self._body = None
        self.setMinimumWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_title = QLabel(tr("未选中天体"))
        layout.addWidget(self.lbl_title)

        self.lbl_grade = QLabel("")
        self.lbl_grade.setWordWrap(True)
        layout.addWidget(self.lbl_grade)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        self._line = line
        layout.addWidget(line)

        self.grid = QGridLayout()
        self.grid.setVerticalSpacing(3)
        layout.addLayout(self.grid)
        layout.addStretch()

        btns = QGridLayout()
        btns.setHorizontalSpacing(6)
        btns.setVerticalSpacing(4)
        self.btn_focus = QPushButton(tr("聚焦"))
        self.btn_focus.clicked.connect(self._focus)
        self.btn_compare = QPushButton(tr("加入对比"))
        self.btn_compare.clicked.connect(self._compare)
        self.btn_exo = QPushButton(tr("观测特征"))
        self.btn_exo.setToolTip(tr(
            "打开「观测特征」标签页：凌星光变曲线 / 视向速度曲线 / 宜居带\n"
            "（太阳系天体仅有宜居带与光通量）"))
        self.btn_exo.clicked.connect(self._show_exo_obs)
        self.btn_sky = QPushButton(tr("地面视角"))
        self.btn_sky.setToolTip(tr(
            "打开「地面视角」标签页：站在选定地点抬头看天的星空图\n"
            "（行星/太阳/亮星的地平坐标 + 当日日轨线与升落时刻）\n"
            "当前选中天体若在地平线上方会高亮标注"))
        self.btn_sky.clicked.connect(self._show_sky)
        self.btn_surface = QPushButton(tr("地表视角"))
        self.btn_surface.setToolTip(tr(
            "打开「地表视角」标签页：站到该行星/卫星表面，第一人称环视天空\n"
            "（天空底色随太阳高度变化，亮星为柔和光晕，地平线为静态地形剪影）\n"
            "仅对具备自转轴数据的天体可用"))
        self.btn_surface.clicked.connect(self._show_surface)
        self.btn_size = QPushButton(tr("尺寸对比"))
        self.btn_size.clicked.connect(self._size_compare)
        btns.addWidget(self.btn_focus, 0, 0)
        btns.addWidget(self.btn_compare, 0, 1)
        btns.addWidget(self.btn_exo, 1, 0)
        btns.addWidget(self.btn_sky, 1, 1)
        btns.addWidget(self.btn_surface, 2, 0)
        btns.addWidget(self.btn_size, 2, 1)
        layout.addLayout(btns)

        self.restyle()

    # ---------- 语言 / 主题 ----------
    def retranslate(self):
        """语言变化：重建按钮/提示，并重绘当前内容。"""
        if self._body is None:
            self.lbl_title.setText(tr("未选中天体"))
        self.btn_focus.setText(tr("聚焦"))
        self.btn_compare.setText(tr("加入对比"))
        self.btn_exo.setText(tr("观测特征"))
        self.btn_exo.setToolTip(tr(
            "打开「观测特征」标签页：凌星光变曲线 / 视向速度曲线 / 宜居带\n"
            "（太阳系天体仅有宜居带与光通量）"))
        self.btn_sky.setText(tr("地面视角"))
        self.btn_sky.setToolTip(tr(
            "打开「地面视角」标签页：站在选定地点抬头看天的星空图\n"
            "（行星/太阳/亮星的地平坐标 + 当日日轨线与升落时刻）\n"
            "当前选中天体若在地平线上方会高亮标注"))
        self.btn_surface.setText(tr("地表视角"))
        self.btn_surface.setToolTip(tr(
            "打开「地表视角」标签页：站到该行星/卫星表面，第一人称环视天空\n"
            "（天空底色随太阳高度变化，亮星为柔和光晕，地平线为静态地形剪影）\n"
            "仅对具备自转轴数据的天体可用"))
        self.btn_size.setText(tr("尺寸对比"))
        if self._body is not None:
            self.show_body(self._body)

    def restyle(self):
        """主题变化：重建依赖调色板的内联样式。"""
        p = style.palette()
        self.lbl_title.setStyleSheet(
            f"color: {p['TEXT_MAIN']}; font-size: {style.fs(15)}px; font-weight: bold;")
        self.lbl_grade.setStyleSheet(f"color: {p['TEXT_DIM']}; font-size: {style.fs(11)}px;")
        self._line.setStyleSheet(f"color: {p['BORDER']};")

    # ---------- 显示 ----------
    def show_body(self, body):
        """显示天体详情（缺失显示'未知'）"""
        self._body = body
        self.lbl_title.setText(body.name)
        self.lbl_grade.setText(
            f"类型: {BODY_TYPE_LABELS.get(body.body_type, body.body_type)}   "
            f"精度等级: {body.grade}\n{GRADE_DESCRIPTION.get(body.grade, '')}")
        self._clear_grid()
        rows = []
        rows.append(("英文名", body.en_name or "—"))

        # 黑洞：特殊字段优先
        if body.body_type == "blackhole":
            if body.bh_type:
                rows.append(("黑洞类型", body.bh_type))
            if body.mass_earth:
                rows.append(("质量", f"{body.mass_solar:.4g} M☉（太阳质量）"))
            if body.radius_km:
                rows.append(("史瓦西半径", f"{body.radius_km:,.3g} km"))
            rows.append(("距地球距离", self._dist_text(body)))
            if body.ra_deg is not None:
                rows.append(("天球位置", f"RA {body.ra_deg:.3f}°, Dec {body.dec_deg:.3f}°"))
            rows.append(("发现年份", _fmt(body.disc_year, "{:.0f}")))
            rows.append(("数据来源", body.data_source or "未知"))
            rows.append(("观测说明", "黑洞本身不可见，仅通过引力效应/X射线辐射间接探测；"
                                "在引力系统模式下可观察其时空扭曲效果"))
            self._render_rows(rows)
            return

        # 宿主恒星 / 近邻恒星
        if body.body_type in ("host_star", "nearby_star"):
            if body.body_type == "nearby_star":
                rows.append(("身份", "近邻恒星（太阳系周边恒星，暂无已确认行星）"))
            else:
                rows.append(("身份", "宿主恒星（该恒星系的中心天体）"))
            if body.host_spec:
                rows.append(("光谱型", body.host_spec))
            if body.host_teff:
                rows.append(("有效温度", f"{body.host_teff:.0f} K"))
            if body.host_radius_solar:
                rows.append(("半径", f"{body.host_radius_solar:.3g} R☉（太阳半径）"))
            if body.host_mass_solar:
                rows.append(("质量", f"{body.host_mass_solar:.3g} M☉（太阳质量）"))
            if body.host_lum is not None:
                rows.append(("光度", f"{body.host_lum:.3g} log L☉"))
            if body.host_age:
                rows.append(("年龄", f"{body.host_age:.3g} Gyr"))
            if body.host_met is not None:
                rows.append(("金属丰度", f"{body.host_met:.3g} [Fe/H]"))
            rows.append(("距地球距离", self._dist_text(body)))
            if body.ra_deg is not None:
                rows.append(("天球位置", f"RA {body.ra_deg:.3f}°, Dec {body.dec_deg:.3f}°"))
            if body.sys_planet_count:
                rows.append(("已确认行星数", f"{int(body.sys_planet_count)} 颗"))
            if body.sys_star_count:
                rows.append(("系统恒星数", f"{int(body.sys_star_count)} 颗"))
            rows.append(("数据来源", body.data_source or "未知"))
            if body.visible_mag is not None:
                rows.append(("视星等", f"{body.visible_mag:.2f}"))
            rows.append(("亮度说明", "近邻恒星在场景中以微亮光点显示（远低于太阳亮度），"
                                "避免背景过于耀眼" if body.body_type == "nearby_star"
                                else "宿主恒星在场景中以微亮光点显示（远低于太阳亮度），"
                                "避免背景过于耀眼"))
            self._render_rows(rows)
            return

        # 星际天体（双曲轨道）
        if body.body_type == "interstellar":
            rows.append(("身份", "星际天体（双曲轨道，不受太阳引力束缚）"))
            rows.append(("近日点距离 q", _fmt(body.a_au, "{:.4g}", " AU")))
            rows.append(("偏心率 e", _fmt(body.e)))
            rows.append(("轨道倾角 i", _fmt(body.incl_deg, "{:.4g}", "°")))
            if body.radius_km:
                rows.append(("直径估计", _fmt(body.radius_km * 2, "{:.4g}", " km")))
            rows.append(("发现年份", _fmt(body.disc_year, "{:.0f}")))
            rows.append(("发现方法", body.method or "未知"))
            rows.append(("数据来源", body.data_source or "未知"))
            rows.append(("说明", "轨道偏心率 >1，为双曲型轨道，仅穿越太阳系一次。"
                                "视口中显示为其近日点位置。"))
            self._render_rows(rows)
            return

        rows.append(("宿主恒星", body.host or ("—" if body.body_type == "star" else "未知")))
        if body.parent_name:
            rows.append(("母天体", body.parent_name))
            if body.body_type == "satellite":
                if body.sat_category:
                    rows.append(("轨道类型", body.sat_category))
                if body.agency:
                    rows.append(("运营机构", body.agency))
                if body.a_au:
                    alt = body.a_au * AU_KM - R_EARTH_KM
                    rows.append(("轨道高度", f"{alt:,.0f} km（地表以上）"))
                if body.incl_deg is not None:
                    rows.append(("轨道面", f"地球赤道面 + 倾角 {body.incl_deg:.2f}°"))
                if body.raan_deg:
                    rows.append(("升交点经度 Ω", f"{body.raan_deg:.1f}°（星座代表值）"))
            else:
                plane_txt = "黄道面" if body.plane == "ecliptic" else "母行星赤道面（近似）"
                if body.retro:
                    plane_txt += "，逆行轨道"
                rows.append(("卫星轨道面", plane_txt))
        # 轨道根数
        if body.a_au:
            a_txt = _fmt(body.a_au, "{:.6g}", " AU")
            if body.body_type in ("moon", "satellite"):
                a_txt += f"（{body.a_au * AU_KM:,.0f} km）"
            rows.append(("轨道半长轴 a", a_txt))
        else:
            rows.append(("轨道半长轴 a", "未知"))
        rows.append(("偏心率 e", _fmt(body.e)))
        rows.append(("轨道倾角 i", _fmt(body.incl_deg, "{:.4g}", "°")))
        rows.append(("公转周期", self._period_text(body)))
        # 自转（恒星日）与转轴倾角
        if body.rot_period_days is not None:
            rows.append(("自转周期（恒星日）", self._rot_text(body)))
            rows.append(("自转方向", body.rotation_direction or "未知"))
        if body.axial_tilt_deg is not None:
            rows.append(("转轴倾角", _fmt(body.axial_tilt_deg, "{:.2f}",
                                      "°（自转轴与轨道面法线夹角）")))
        if body.body_type in ("planet_solar", "dwarf", "etno"):
            from core.kepler import position_at_time
            el = body.elements
            rows.append(("升交点经度 Ω", _fmt(el.Omega, "{:.4g}", "°")))
            omega = el.varpi - el.Omega
            rows.append(("近心点幅角 ω", _fmt(omega, "{:.4g}", "°")))
            rows.append(("近日点经度 ϖ", _fmt(el.varpi, "{:.4g}", "°")))
        # 物理
        rows.append(("半径", _fmt(body.radius_km, "{:,.1f}", " km")))
        if body.radius_km:
            rows.append(("半径（地球=1）", _fmt(body.radius_km / R_EARTH_KM, "{:.3g}")))
        rows.append(("质量（地球=1）", _fmt(body.mass_earth)))
        if body.mass_earth:
            rows.append(("质量（木星=1）", _fmt(body.mass_earth / 317.8, "{:.4g}")))
        # 物理约束量（由质量/半径/轨道根数按标准公式推算，见 core/physics.py）
        rows.extend(self._physics_rows(body))
        # 发现信息
        rows.append(("发现年份", _fmt(body.disc_year, "{:.0f}")))
        rows.append(("发现方法", body.method or "未知"))
        rows.append(("距地球距离", self._dist_text(body)))
        rows.append(("数据来源", body.data_source or "未知"))
        if body.assumed_phase:
            rows.append(("轨道相位", "假设值（M(J2000)=0，可复现；瞬时位置无预测意义）"))
        # 坐标（系外行星/恒星）
        if body.ra_deg is not None:
            rows.append(("宿主星 RA/Dec", f"{body.ra_deg:.3f}°, {body.dec_deg:.3f}°"))
        self._render_rows(rows)

    # ---------- 恒星系概览（点击左侧恒星系节点） ----------
    def show_system(self, group):
        """显示恒星系概览：宿主恒星参数 + 成员行星清单（不伪造缺失值）"""
        self._body = None
        self.lbl_title.setText("太阳系" if group.is_solar else f"{group.host} 系")
        self.lbl_grade.setText(
            f"恒星系（系群）   成员行星 {group.n_planets} 颗"
            + (f"   天然卫星 {len(group.moons)} 颗" if group.moons else ""))
        self._clear_grid()
        rows = [("宿主恒星", "太阳" if group.is_solar else group.host)]
        rows.append(("恒星光度型", group.spec or "未知"))
        rows.append(("有效温度", _fmt(group.host_teff, "{:.0f}", " K")))
        rows.append(("恒星质量", _fmt(group.host_mass_solar, "{:.3g}", " M☉")))
        rows.append(("恒星半径", _fmt(group.host_radius_solar, "{:.3g}", " R☉")))
        if group.dist_pc:
            rows.append(("距地球距离",
                         f"{group.dist_pc:.4g} pc ≈ {group.dist_pc / 0.3066:.4g} 光年"))
        else:
            rows.append(("距地球距离", "—（太阳系：本星系）" if group.is_solar else "未知"))
        rows.append(("系统恒星数", _fmt(group.star_count, "{:.0f}")))
        if group.planet_count is not None and group.planet_count != group.n_planets:
            rows.append(("官方已确认行星数", _fmt(group.planet_count, "{:.0f}")))
        rows.append(("成员行星", "、".join(b.name for b in group.planets) or "未知"))
        if group.moons:
            rows.append(("天然卫星", "、".join(m.name for m in group.moons)))
        rows.append(("数据来源", "NASA Exoplanet Archive（宿主恒星参数）"
                     if not group.is_solar else "JPL 近似轨道根数 + IAU 物理参数"))
        self._render_rows(rows)

    # ---------- 内部渲染 ----------
    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_rows(self, rows):
        p = style.palette()
        for i, (k, v) in enumerate(rows):
            kl = QLabel(str(k))
            kl.setStyleSheet(f"color: {p['TEXT_DIM']};")
            vl = QLabel(str(v))
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            vl.setStyleSheet(f"color: {p['TEXT_MAIN']};")
            vl.setWordWrap(True)
            self.grid.addWidget(kl, i, 0, Qt.AlignTop)
            self.grid.addWidget(vl, i, 1, Qt.AlignTop)
        self.grid.setColumnStretch(1, 1)

    def _period_text(self, body):
        p = body.period
        if not p:
            return "未知"
        if p < 0.25:
            return f"{p * 1440.0:.1f} 分钟（{p:.4f} 天）"
        if p < 400:
            return f"{p:.2f} 天"
        yr = p / 365.25
        if yr < 1000:
            return f"{p:.2f} 天（{yr:.2f} 年）"
        return f"{yr:,.0f} 年（{p:,.0f} 天）"

    def _physics_rows(self, body):
        """由质量/半径/轨道推算的物理约束量（标准天体力学公式）。

        公式实现见 core/physics.py：
            表面重力 g=GM/R²、逃逸速度 v=√(2GM/R)、平均密度 ρ=3M/(4πR³)、
            轨道速度 v=√(μ/a)、希尔球 r_H=a(m/3M)^(1/3)、
            洛希极限 d=R(2ρ_M/ρ_m)^(1/3)、同步轨道半径 r=(μ(T/2π)²)^(1/3)
        """
        from core import physics as ph
        from core.constants import M_SUN_PER_EARTH
        rows = []
        if body.radius_km and body.mass_earth:
            g = ph.surface_gravity_ms2(body.radius_km, body.mass_earth)
            rows.append(("表面重力 g", f"{g:.3g} m/s²（地球 9.81 m/s²）"))
            vesc = ph.escape_velocity_kms(body.radius_km, body.mass_earth)
            rows.append(("逃逸速度 v_esc", f"{vesc:.3g} km/s"))
            rho = ph.mean_density_gcm3(body.radius_km, body.mass_earth)
            rows.append(("平均密度 ρ", f"{rho:.3g} g/cm³"))

        # 环绕速度（相对中心天体）：太阳系天体绕太阳，卫星/人造卫星绕母天体
        mu = None
        if body.body_type in ("planet_solar", "dwarf", "etno"):
            mu = ph.mu_solar(1.0)
        elif body.body_type in ("moon", "satellite") and body.parent is not None \
                and body.parent.mass_earth:
            mu = ph.mu_earth(body.parent.mass_earth)
        if mu and body.a_au:
            a_km = body.a_au * AU_KM
            vc = ph.circular_velocity_kms(a_km, mu)
            rows.append(("平均轨道速度", f"{vc:.3g} km/s（圆轨道近似 √(μ/a)）"))
            # 开普勒第三定律校验（与实测周期对照）
            if body.period_days:
                tk = ph.kepler_period_days(a_km, mu)
                err = abs(tk - body.period_days) / body.period_days * 100.0
                rows.append(("开普勒定律校验",
                             f"理论周期 {tk * 1440.0:.2f} 分钟，与实测偏差 {err:.2f}%"))

        # 希尔球半径（行星/矮行星，判断卫星系引力范围）
        if body.body_type in ("planet_solar", "dwarf") and body.a_au and body.mass_earth:
            rh = ph.hill_sphere_km(body.a_au * AU_KM, body.mass_earth, M_SUN_PER_EARTH)
            rows.append(("希尔球半径 r_H", f"{rh:,.0f} km（引力主导区边界）"))

        # 洛希极限（带环行星：环外缘应位于流体洛希极限附近）
        if body.radius_km and body.mass_earth:
            from data.solar_system import RINGS
            if body.name in RINGS:
                rho_p = ph.mean_density_gcm3(body.radius_km, body.mass_earth)
                rho_m = 1.0                    # 环粒密度取 1 g/cm³（冰/岩碎屑典型值）
                d_rigid = ph.roche_limit_km(body.radius_km, rho_p, rho_m)
                d_fluid = ph.roche_limit_fluid_km(body.radius_km, rho_p, rho_m)
                rows.append(("洛希极限（刚体）", f"{d_rigid:,.0f} km（{d_rigid / body.radius_km:.3f} R）"))
                rows.append(("洛希极限（流体）", f"{d_fluid:,.0f} km（{d_fluid / body.radius_km:.3f} R）"))
                outer = RINGS[body.name]["outer"]
                rows.append(("环系外缘",
                             f"{outer * body.radius_km:,.0f} km（{outer:.3f} R，"
                             + ("位于流体洛希极限内 ✓" if outer * body.radius_km <= d_fluid
                                else "接近流体洛希极限")))

        # 同步轨道半径（自转周期决定）
        if body.rot_period_days and body.mass_earth and body.radius_km:
            mu_b = ph.mu_earth(body.mass_earth)
            r_sync = ph.synchronous_radius_km(mu_b, abs(body.rot_period_days))
            rows.append(("同步轨道半径",
                         f"{r_sync:,.0f} km（周期等于自转周期，"
                         f"{r_sync / body.radius_km:.2f} R）"))
        return rows

    def _rot_text(self, body):
        """自转周期文本：短周期补小时，逆行加标注"""
        p = body.rot_period_days
        if p is None:
            return "未知"
        ap = abs(p)
        txt = f"{ap:.4f} 天" if ap >= 2.0 else f"{ap:.6f} 天（{ap * 24.0:.4f} 小时）"
        if p < 0:
            txt += "，逆行"
        return txt

    def _dist_text(self, body):
        if body.dist_pc is None and body.body_type not in (
                "planet_solar", "dwarf", "etno", "moon", "star"):
            return "未知"
        if body.body_type == "star":
            return "—（太阳系中心，坐标原点）"
        if body.body_type in ("host_star", "nearby_star", "blackhole"):
            if body.dist_pc is None:
                return "未知"
            ly = body.dist_pc / 0.3066
            return f"{body.dist_pc:.3g} pc ≈ {ly:.3g} 光年"
        if body.dist_pc is None:
            # 太阳系天体（行星/矮行星/卫星）：当前时刻地心距离（由视口时钟）
            if self.viewport is not None and self.viewport._body_pos is not None:
                try:
                    names = list(map(lambda x: x.name, self.viewport.bodies))
                    i = names.index(body.name)
                    jd = self.viewport.clock.jd
                    earth = next((x for x in self.viewport.bodies if x.name == "地球"), None)
                    if earth:
                        names2 = list(map(lambda x: x.name, self.viewport.bodies))
                        j = names2.index("地球")
                        pe = self.viewport.bodies[j].position_at_jd(jd)
                        pb = body.position_at_jd(jd)
                        d_au = float(((pe - pb) ** 2).sum() ** 0.5)
                        return f"{format_distance(d_au)}（当前地心距离）"
                except Exception:
                    pass
            return "未知"
        ly = body.dist_pc / 0.3066
        return f"{body.dist_pc:.3g} pc ≈ {ly:.3g} 光年"

    # ---------- 动作 ----------
    def _focus(self):
        if self._body and self.viewport:
            self.viewport.focus_body_by_name(self._body.name)

    def _compare(self):
        if self._body and self.compare_panel:
            # 加入对比的第二格（B），A 保持或取当前
            cur_b = self.compare_panel.combo_b.currentText()
            if cur_b == self._body.name and self.compare_panel._body_a != self._body:
                pass
            self.compare_panel.set_pair(
                self.compare_panel._body_a.name if self.compare_panel._body_a and
                self.compare_panel._body_a.name != self._body.name else
                (self.compare_panel.combo_a.currentText()
                 if self.compare_panel.combo_a.currentText() != self._body.name
                 else (self._body.host if self._body.host != "太阳" else "地球")),
                self._body.name)

    def _size_compare(self):
        if not self._body:
            return
        from ui.size_compare import SizeCompareDialog
        dlg = SizeCompareDialog(self._body, self)
        dlg.exec_()

    def _show_exo_obs(self):
        """切换到「观测特征」标签页并载入当前天体"""
        if not self._body or self.exo_obs_panel is None:
            return
        self.exo_obs_panel.set_body(self._body)
        if self.right_tabs is not None:
            self.right_tabs.setCurrentWidget(self.exo_obs_panel)

    def _show_sky(self):
        """切换到「地面视角」标签页（高亮当前选中天体，若有）"""
        if self.sky_panel is None:
            return
        self.sky_panel.refresh()
        if self.right_tabs is not None:
            self.right_tabs.setCurrentWidget(self.sky_panel)

    def _show_surface(self):
        """切换到「地表视角」标签页并站到当前天体表面（不支持则提示）"""
        if self.surface_panel is None:
            return
        ok = True
        if self._body is not None:
            ok = self.surface_panel.set_body(self._body)
        self.surface_panel.refresh()
        if self.right_tabs is not None:
            self.right_tabs.setCurrentWidget(self.surface_panel)
        if not ok and self._body is not None:
            self.lbl_grade.setText(
                self.lbl_grade.text() + "\n（该天体缺少自转轴数据，无法提供地表视角）")