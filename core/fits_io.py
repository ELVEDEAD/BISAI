"""
fits_io.py —— FITS 文件读写（观测数据处理模块，纯 numpy 实现）

不依赖 astropy，按 FITS Standard 4.0 自研解析器，覆盖天文观测数据中最常用
的子集（NASA Exoplanet Archive / MAST / SDSS 光谱等主流产品）：

* 主 HDU + 任意多个扩展 HDU
* IMAGE（BITPIX = 8/16/32/64/−32/−64，BSCALE/BZERO 定标，无符号整数走零拷贝视图）
* BINTABLE（TFORM：L/B/I/J/K/A/E/D/C/M/X，TSCAL/TZERO，重复计数）
* ASCII TABLE（TBCOL + Fw.d / Ew.d / Iw / Aw 列）
* 长字符串 CONTINUE 拼接、.fits.gz gzip 透明解压

已知边界（科学诚实性）：
* 变长数组列（TFORM 'P'/'Q'）不解析，抛 NotImplementedError（需 astropy）
* 随机组 / 压缩图像（RICE、HCOMPRESS）不支持
* 写入仅覆盖数值图像与 BINTABLE；HIERARCH 卡不保留

FITS 规定大端字节序，读取后统一转为本机序数组。
"""
import gzip
import math
import re

import numpy as np

BLOCK = 2880          # FITS 逻辑块大小（字节）
CARD = 80             # 头卡片宽度（字符）

BITPIX_DTYPES = {8: ">u1", 16: ">i2", 32: ">i4", 64: ">i8", -32: ">f4", -64: ">f8"}
DTYPES_BITPIX = {">u1": 8, ">i2": 16, ">i4": 32, ">i8": 64, ">f4": -32, ">f8": -64}

# BINTABLE 类型码 → (大端 dtype, 元素字节数)
TFORM_DTYPES = {
    "L": (">u1", 1), "B": (">u1", 1), "I": (">i2", 2),
    "J": (">i4", 4), "K": (">i8", 8), "E": (">f4", 4), "D": (">f8", 8),
    "C": (">c8", 8), "M": (">c16", 16),
}
_TFORM_RE = re.compile(r"^(\d*)([LXBIJKAEDCMPQ])(.*)$")
_ASCII_FORM_RE = re.compile(r"^([AIEDF])(\d+)")


class HDU:
    """单个 HDU：header（dict）+ data（ndarray 或 None）+ columns（表列 dict）"""

    __slots__ = ("header", "data", "columns")

    def __init__(self, header, data, columns=None):
        self.header = header
        self.data = data
        self.columns = columns

    @property
    def name(self):
        """扩展名（EXTNAME），主 HDU 返回 'PRIMARY'"""
        return self.header.get("EXTNAME", "PRIMARY")

    def __repr__(self):
        kind = str(self.header.get("XTENSION", "IMAGE")).strip()
        return f"<HDU {self.name!r} {kind} shape={getattr(self.data, 'shape', None)}>"


# ---------- 头解析 ----------
def _parse_value(raw: str):
    """解析卡片值（'' 转义 → 字符串；T/F → bool；数字 → int/float）"""
    s = raw.strip()
    if not s:
        return None
    if s[0] == "'":
        out, i = [], 1
        while i < len(s):
            if s[i] == "'":
                if i + 1 < len(s) and s[i + 1] == "'":     # '' 转义为 '
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(s[i])
            i += 1
        return "".join(out).rstrip()
    if s == "T":
        return True
    if s == "F":
        return False
    try:
        if re.fullmatch(r"[+-]?\d+", s):
            return int(s)
        return float(s.replace("D", "E").replace("d", "e"))
    except ValueError:
        return s


def _read_header_cards(buf: bytes, offset: int):
    """读一个完整头（若干 2880 字节块），返回 (有效卡片列表, 新 offset)"""
    cards = []
    while True:
        if offset + BLOCK > len(buf):
            raise ValueError("FITS 头未找到 END 卡片（文件截断？）")
        block = buf[offset:offset + BLOCK]
        offset += BLOCK
        for k in range(36):
            card = block[k * CARD:(k + 1) * CARD].decode("latin-1")
            key = card[:8].rstrip()
            if key == "END":
                return cards, offset
            if key in ("COMMENT", "HISTORY", "") or \
                    (card[8:10] != "= " and not card.startswith("CONTINUE")):
                continue          # 注释卡与 HIERARCH 跳过；CONTINUE 卡留给长字符串拼接
            cards.append(card)


def _header_to_dict(cards):
    """卡片列表 → dict，含 CONTINUE 长字符串拼接"""
    header = {}
    i = 0
    while i < len(cards):
        card = cards[i]
        key = card[:8].rstrip()
        if key == "CONTINUE":
            i += 1
            continue              # 已被前一张长字符串卡吸收
        val = _parse_value(card[10:])
        if isinstance(val, str) and val.endswith("&") and \
                i + 1 < len(cards) and cards[i + 1].startswith("CONTINUE"):
            val = val[:-1]
            while i + 1 < len(cards) and cards[i + 1].startswith("CONTINUE"):
                cont = _parse_value(cards[i + 1][10:])
                if cont is None:
                    break
                val += cont[:-1] if cont.endswith("&") else cont
                i += 1
        header[key] = val
        i += 1
    return header


# ---------- 数据区解析 ----------
def _padded(n_bytes: int) -> int:
    """数据区占用字节数（向上取整到 2880 块）"""
    return int(math.ceil(n_bytes / BLOCK)) * BLOCK


def _apply_scale(data, bzero, bscale):
    """BZERO/BSCALE 定标：物理值 = 磁盘值·BSCALE + BZERO（FITS 标准语义）。

    无符号特例（BSCALE=1、BZERO=2^(bits−1)）转无符号 dtype 输出；
    int8/16/32 经 int64 中转避免溢出，int64 用位重解释（模 2⁶⁴ 等价）。
    """
    if bzero == 0 and bscale == 1:
        return data
    if bscale == 1 and data.dtype.kind == "i":
        unsigned = {2: (32768, np.uint16), 4: (2147483648, np.uint32),
                    8: (9223372036854775808, np.uint64)}
        if data.dtype.itemsize in unsigned and bzero == unsigned[data.dtype.itemsize][0]:
            if data.dtype.itemsize == 8:
                return data.view(np.uint64)          # mod 2⁶⁴ 与 +BZERO 等价
            return (data.astype(np.int64) + bzero).astype(unsigned[data.dtype.itemsize][1])
    return data.astype(np.float64) * bscale + bzero


def _read_image(header, buf, offset):
    """读 IMAGE 数据区 → (ndarray 或 None, 新 offset)"""
    naxis = int(header.get("NAXIS", 0))
    if naxis == 0:
        return None, offset
    axes = [int(header[f"NAXIS{k}"]) for k in range(1, naxis + 1)]
    if any(a < 0 for a in axes):
        raise ValueError(f"非法 NAXISn：{axes}")
    dtype = np.dtype(BITPIX_DTYPES[int(header["BITPIX"])])
    n = int(np.prod(axes))
    raw = np.frombuffer(buf, dtype=dtype, count=n, offset=offset)
    offset += _padded(n * dtype.itemsize)
    # FITS 轴序与 C 相反；FITS 大端 → 本机序拷贝
    data = raw.reshape(axes[::-1]).astype(raw.dtype.newbyteorder("="))
    return _apply_scale(data, header.get("BZERO", 0), header.get("BSCALE", 1)), offset


def _parse_tform(form: str):
    """TFORMn → (repeat, 类型码)。'0D' 表示零长度列。"""
    m = _TFORM_RE.match(form.strip().upper())
    if not m:
        raise ValueError(f"无法解析的 TFORM：{form!r}")
    return (int(m.group(1)) if m.group(1) else 1), m.group(2)


def _read_bintable(header, buf, offset):
    """读 BINTABLE 数据区 → (structured array, 列 dict, 新 offset)"""
    tfields = int(header.get("TFIELDS", 0))
    row_bytes = int(header.get("NAXIS1", 0))
    n_rows = int(header.get("NAXIS2", 0))

    names, formats, offsets = [], [], []
    pos = 0
    for k in range(1, tfields + 1):
        name = str(header.get(f"TTYPE{k}", f"col{k}"))
        repeat, code = _parse_tform(str(header[f"TFORM{k}"]))
        if code in ("P", "Q"):
            raise NotImplementedError(
                f"列 {name!r} 为变长数组（TFORM={header[f'TFORM{k}']!r}），请安装 astropy 读取")
        if code == "X":                      # 位域：按原始字节返回
            byte_len = max((repeat + 7) // 8, 1)
            names.append(name); formats.append(f"V{byte_len}"); offsets.append(pos)
            pos += byte_len
        elif code == "A":                   # 字符串
            width = max(repeat, 1)
            names.append(name); formats.append(f"S{width}"); offsets.append(pos)
            pos += width
        else:
            dt, item = TFORM_DTYPES[code]
            names.append(name)
            formats.append(dt if repeat == 1 else f"{repeat}{dt}")
            offsets.append(pos)
            pos += repeat * item
    if pos != row_bytes:
        raise ValueError(f"TFORM 总宽 {pos} ≠ NAXIS1 = {row_bytes}")

    dtype = np.dtype({"names": names, "formats": formats,
                      "offsets": offsets, "itemsize": row_bytes})
    raw = np.frombuffer(buf, dtype=np.uint8, count=row_bytes * n_rows, offset=offset)
    offset += _padded(row_bytes * n_rows)
    rec = raw.view(dtype) if n_rows else np.empty(0, dtype=dtype)

    columns = {}
    for k, name in enumerate(names, start=1):
        col = rec[name]
        code = _parse_tform(str(header[f"TFORM{k}"]))[1]
        if code == "A":
            col = np.array([b.tobytes().decode("latin-1").rstrip("\x00 ").rstrip()
                            for b in col], dtype=object)
        elif code == "L":                   # 'T'/'F' 字节 → bool
            col = col.astype(np.uint8) == ord("T")
        elif code == "X":
            col = col.copy()
        else:
            col = col.astype(col.dtype.newbyteorder("="))
            col = _apply_scale(col, header.get(f"TZERO{k}", 0), header.get(f"TSCALE{k}", 1))
        columns[name] = col
    return rec, columns, offset


def _read_asciitable(header, buf, offset):
    """读 ASCII TABLE：固定行宽、无换行符，按 TBCOLn 切片 → 列 dict"""
    tfields = int(header.get("TFIELDS", 0))
    row_bytes = int(header.get("NAXIS1", 0))
    n_rows = int(header.get("NAXIS2", 0))
    raw = np.frombuffer(buf, dtype=np.uint8, count=row_bytes * n_rows, offset=offset)
    offset += _padded(row_bytes * n_rows)
    text = raw.reshape(n_rows, row_bytes).tobytes().decode("latin-1")
    lines = [text[i * row_bytes:(i + 1) * row_bytes] for i in range(n_rows)]

    columns = {}
    for k in range(1, tfields + 1):
        name = str(header.get(f"TTYPE{k}", f"col{k}"))
        form = str(header.get(f"TFORM{k}", "A1")).upper()
        m = _ASCII_FORM_RE.match(form)
        if not m:
            raise ValueError(f"无法解析的 ASCII 表 TFORM：{form!r}")
        code, width = m.group(1), int(m.group(2))
        tbcol = int(header.get(f"TBCOL{k}", 1)) - 1
        if code == "A":
            conv = lambda s: s.strip()
        elif code == "I":
            conv = lambda s: int(s) if s.strip() else 0
        else:                                  # D/E/F → float
            conv = lambda s: float(s) if s.strip() else float("nan")
        columns[name] = np.array(
            [conv(line[tbcol:tbcol + width]) for line in lines])
    return columns, offset


# ---------- 读取接口 ----------
def read_fits(path) -> list:
    """读取 FITS 文件（支持 .fits / .fits.gz），返回 HDU 列表。

    HDU.header  : dict（SIMPLE / BITPIX / NAXIS … 及用户关键字）
    HDU.data    : IMAGE → ndarray；BINTABLE → structured array；ASCII 表 → None
    HDU.columns : 表类 HDU → {列名: 数组}（'A' 字符串列为 object 数组）
    """
    path = str(path)
    if path.lower().endswith(".gz"):
        with gzip.open(path, "rb") as f:
            buf = f.read()
    else:
        with open(path, "rb") as f:
            buf = f.read()
    if len(buf) < BLOCK or not buf.startswith(b"SIMPLE  ="):
        raise ValueError(f"不是合法的 FITS 文件：{path}")

    hdus, offset = [], 0
    while offset < len(buf):
        if buf[offset:offset + 8].strip(b" ") == b"":
            break                              # 尾部空白填充块
        cards, offset = _read_header_cards(buf, offset)
        header = _header_to_dict(cards)
        xt = str(header.get("XTENSION", "IMAGE")).strip().upper()
        if xt == "IMAGE":
            data, offset = _read_image(header, buf, offset)
            hdus.append(HDU(header, data))
        elif xt == "BINTABLE":
            rec, columns, offset = _read_bintable(header, buf, offset)
            hdus.append(HDU(header, rec, columns))
        elif xt == "TABLE":
            columns, offset = _read_asciitable(header, buf, offset)
            hdus.append(HDU(header, None, columns))
        else:
            raise NotImplementedError(f"不支持的扩展类型：{xt}")
    return hdus


def read_primary_data(path):
    """便捷接口：主 HDU 数据（图像 ndarray 或 None）"""
    return read_fits(path)[0].data


def read_table(path, ext=1) -> dict:
    """便捷接口：第 ext 个 HDU 的表列 dict"""
    hdu = read_fits(path)[ext]
    if not hdu.columns:
        raise ValueError(f"HDU #{ext} 不是表扩展")
    return hdu.columns


def is_fits(path) -> bool:
    """快速判断文件是否为 FITS（含 gzip 压缩 FITS）"""
    path = str(path)
    try:
        opener = gzip.open if path.lower().endswith(".gz") else open
        with opener(path, "rb") as f:
            return f.read(9).startswith(b"SIMPLE  =")
    except OSError:
        return False


# ---------- 写入 ----------
def _fmt_card(key: str, value) -> str:
    """构造 80 列标准头卡片（值右对齐到 11–30 列）"""
    if isinstance(value, bool):
        body = f"{key:<8}= {'T' if value else 'F':>20}"
    elif isinstance(value, int):
        body = f"{key:<8}= {value:>20}"
    elif isinstance(value, float):
        body = f"{key:<8}= {value:>20.12G}"
    elif value is None:
        body = f"{key:<8}="
    else:
        s = str(value).replace("'", "''")[:60]
        body = f"{key:<8}= '{s:<18}'"
    return body[:CARD].ljust(CARD)


def _cards_to_bytes(cards) -> bytes:
    """卡片列表 → 补空格到 2880 块边界的字节流"""
    raw = "".join(cards).encode("latin-1")
    return raw + b" " * ((-len(raw)) % BLOCK)


def write_fits_image(path, data, extra_header=None):
    """图像 ndarray → 单 HDU FITS 文件。

    支持 uint8 / int16 / int32 / int64 / float32 / float64（其余数值类型转
    float64 后按 BITPIX=−64 写入）；extra_header 追加用户关键字（不得与
    标准头同名）。
    """
    data = np.asarray(data)
    native = {"u1": ">u1", "i2": ">i2", "i4": ">i4", "i8": ">i8",
              "f4": ">f4", "f8": ">f8"}
    key = data.dtype.str[1:]
    if key not in native:
        data = data.astype(np.float64)
        key = "f8"
    be = data.astype(native[key])
    bitpix = DTYPES_BITPIX[native[key]]

    cards = [_fmt_card("SIMPLE", True), _fmt_card("BITPIX", bitpix),
             _fmt_card("NAXIS", be.ndim)]
    for k, n in enumerate(be.shape[::-1], start=1):     # FITS 轴序与 C 相反
        cards.append(_fmt_card(f"NAXIS{k}", int(n)))
    extra = dict(extra_header or {})
    std_keys = {"SIMPLE", "BITPIX", "NAXIS"} | {f"NAXIS{k}" for k in range(1, be.ndim + 1)}
    clash = std_keys & set(extra)
    if clash:
        raise ValueError(f"extra_header 与标准头关键字冲突：{sorted(clash)}")
    cards += [_fmt_card(k, v) for k, v in extra.items()]
    cards.append("END".ljust(CARD))

    with open(path, "wb") as f:
        f.write(_cards_to_bytes(cards))
        f.write(be.tobytes())
        f.write(b"\x00" * ((-be.nbytes) % BLOCK))
    return path


def write_fits_table(path, columns: dict, extra_header=None):
    """列 dict → 「空主 HDU + BINTABLE 扩展」FITS 文件。

    列类型映射：float32→E，float64→D，int16→I，int32→J，int64→K，
    uint8→B（其余整型升格为 int64→K），str→A{最长宽度}。各列须等长。
    """
    names = list(columns.keys())
    if not names:
        raise ValueError("columns 为空")
    arrays = [np.asarray(columns[n]) for n in names]
    n_rows = len(arrays[0])
    if any(len(a) != n_rows for a in arrays):
        raise ValueError("各列长度不一致")

    # (TFORM, 大端字节流, 每行字节数)
    blobs = []
    for a in arrays:
        if a.dtype.kind == "b":                   # 逻辑列：'T'/'F' 字节
            blobs.append(("L", np.where(a, ord("T"), ord("F")).astype(">u1"), 1))
        elif a.dtype.kind == "f":
            if a.dtype.itemsize <= 4:
                blobs.append(("E", a.astype(">f4"), 4))
            else:
                blobs.append(("D", a.astype(">f8"), 8))
        elif a.dtype.kind in ("i", "u"):
            if a.dtype.kind == "u" and a.dtype.itemsize == 1:
                blobs.append(("B", a.astype(">u1"), 1))
            elif a.dtype.kind == "u":
                blobs.append(("K", a.astype(">i8"), 8))
            else:
                form = {1: "B", 2: "I", 4: "J", 8: "K"}[a.dtype.itemsize]
                dt = {"B": ">u1", "I": ">i2", "J": ">i4", "K": ">i8"}[form]
                blobs.append((form, a.astype(dt), a.dtype.itemsize))
        elif a.dtype.kind in ("U", "S") or a.dtype == object:
            width = max((len(str(x)) for x in a), default=0) or 1
            blobs.append((f"{width}A",
                          np.array([str(x).ljust(width) for x in a], dtype="S"), width))
        else:
            raise TypeError(f"不支持的列类型：{a.dtype}")

    row_bytes = sum(b[2] for b in blobs)
    pri = [_fmt_card("SIMPLE", True), _fmt_card("BITPIX", 8),
           _fmt_card("NAXIS", 0), "END".ljust(CARD)]
    ext = [_fmt_card("XTENSION", "BINTABLE"), _fmt_card("BITPIX", 8),
           _fmt_card("NAXIS", 2), _fmt_card("NAXIS1", row_bytes),
           _fmt_card("NAXIS2", n_rows), _fmt_card("TFIELDS", len(names)),
           _fmt_card("EXTNAME", "TABLE")]
    for k, (name, (form, _, _)) in enumerate(zip(names, blobs), start=1):
        ext.append(_fmt_card(f"TTYPE{k}", name))
        ext.append(_fmt_card(f"TFORM{k}", form))
    ext += [_fmt_card(k, v) for k, v in (extra_header or {}).items()]
    ext.append("END".ljust(CARD))

    rows = bytearray()
    for i in range(n_rows):
        for _, arr, _ in blobs:
            # 用切片视图而非标量取字节：numpy 标量会丢失大端 dtype 信息
            rows += arr[i:i + 1].tobytes()

    with open(path, "wb") as f:
        f.write(_cards_to_bytes(pri))
        f.write(_cards_to_bytes(ext))
        f.write(bytes(rows))
        f.write(b"\x00" * ((-len(rows)) % BLOCK))
    return path