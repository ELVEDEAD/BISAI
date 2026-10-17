"""llm_client.py —— 大模型 API 调用（OpenAI 兼容 Chat Completions 接口）

只依赖 Python 标准库（urllib + json + ssl），不引入任何第三方包，离线环境亦可运行；
真正的网络请求由调用方（UI 层线程）执行，本模块保持纯同步、无 Qt 依赖，便于单独测试。

支持主流服务商的 OpenAI 兼容端点：
    DeepSeek / Moonshot(月之暗面) / 智谱 GLM / OpenAI / 阿里通义千问 / 自定义。
所有服务商均使用同一请求格式：
    POST {base_url}/chat/completions
    Authorization: Bearer {api_key}
    {"model": ..., "messages": [...], "temperature": ...}
"""
import json
import ssl
import urllib.error
import urllib.request

# (键, 显示名, 默认 API 地址, 默认模型)
PROVIDERS = [
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("moonshot", "Moonshot（月之暗面）", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("zhipu", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ("dashscope", "阿里通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("custom", "自定义（OpenAI 兼容）", "", ""),
]

PROVIDER_KEYS = [k for k, _, _, _ in PROVIDERS]

SYSTEM_PROMPT = (
    "你是「Astrarium」软件内置的天文助手。请用简体中文、准确简洁地回答用户"
    "关于太阳系、系外行星、恒星、天象与天文观测的问题；涉及精确数值时说明数据来源与"
    "不确定性，不臆造数据。若问题与本软件功能相关，可结合软件中的 JPL 星历、"
    "NASA Exoplanet Archive 数据与开普勒轨道模型作答。"
)

DEFAULT_TIMEOUT = 30.0


def provider_defaults(key: str):
    """返回指定服务商的 (默认 API 地址, 默认模型)；未知键返回空串。"""
    for k, _name, url, model in PROVIDERS:
        if k == key:
            return url, model
    return "", ""


def provider_label(key: str) -> str:
    for k, name, _, _ in PROVIDERS:
        if k == key:
            return name
    return key


def build_messages(user_text: str, history=None, system_prompt: str = None):
    """把历史对话与当前提问组装为 messages 列表（OpenAI 格式）。"""
    msgs = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
    if history:
        for role, content in history:
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs


def _normalize_base(base_url: str) -> str:
    """规整 base_url：去掉尾部斜杠；若未含 /chat/completions 则自动补全。"""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def chat(base_url: str, api_key: str, model: str, messages,
         temperature: float = 0.6, timeout: float = DEFAULT_TIMEOUT):
    """发起一次非流式对话补全。

    返回 (ok: bool, text: str, err: str)：
        ok=True  → text 为模型回复，err=""
        ok=False → text=""，err 为可读错误信息（含 HTTP 状态码 / 网络异常）
    """
    endpoint = _normalize_base(base_url)
    if not endpoint:
        return False, "", "未配置 API 地址"
    if not api_key:
        return False, "", "未配置 API Key"
    if not model:
        return False, "", "未配置模型名称"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json")

    # 优先使用系统证书；部分精简环境缺少 CA，则退化为不校验证书（仅影响本次调用）
    try:
        ctx = ssl.create_default_context()
    except Exception:
        ctx = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        msg = _extract_error(detail) or f"HTTP {e.code} {e.reason}"
        return False, "", msg
    except urllib.error.URLError as e:
        return False, "", f"网络不可达：{e.reason}"
    except Exception as e:                                     # 超时 / SSL / 其他
        return False, "", f"{type(e).__name__}: {e}"

    try:
        obj = json.loads(body)
    except Exception:
        return False, "", "响应不是合法 JSON"

    return _extract_text(obj)


def _extract_text(obj: dict):
    """从 OpenAI 兼容响应里取出回复文本。"""
    try:
        choices = obj.get("choices") or []
        if not choices:
            err = (obj.get("error") or {}).get("message") if isinstance(obj.get("error"), dict) else None
            return False, "", err or "响应中没有 choices"
        msg = choices[0].get("message") or {}
        text = msg.get("content")
        if not text:
            text = choices[0].get("text") or ""
        text = (text or "").strip()
        if not text:
            return False, "", "模型返回了空回复"
        return True, text, ""
    except Exception as e:
        return False, "", f"解析响应失败：{e}"


def _extract_error(detail: str) -> str:
    """尽力从错误响应体里提取可读信息。"""
    if not detail:
        return ""
    try:
        obj = json.loads(detail)
        err = obj.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
        if obj.get("message"):
            return str(obj["message"])
    except Exception:
        pass
    return detail[:300]