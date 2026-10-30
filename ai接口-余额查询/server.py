# -*- coding: utf-8 -*-
"""
AI API 余额聚合查询 —— 本地小工具
只用 Python 标准库，零依赖。

用法：python server.py  然后浏览器打开 http://127.0.0.1:7788
密钥只保存在本机 keys.json，不会上传到任何地方。
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"          # 只监听本机回环，不对外暴露
PORT = int(os.environ.get("AI_BALANCE_PORT", "7788"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(BASE_DIR, "keys.json")
UA = "ai-balance-local/1.0"


# ---------------------------------------------------------------- 服务商目录
# group: auto=能自动查 / manual=无公开接口，靠手动记账
# kind:  balance=余额 / quota=套餐配额 / spend=花费（官方不提供余额）/ manual=手填 / custom=自定义站点
PROVIDERS = [
    # ================= 能自动查询 =================
    {
        "id": "deepseek", "group": "auto", "kind": "balance", "name": "DeepSeek", "currency": "CNY",
        "url": "https://api.deepseek.com/user/balance",
        "console": "https://platform.deepseek.com",
        "hint": "官方余额接口，最省事的一家",
    },
    {
        "id": "moonshot", "group": "auto", "kind": "balance", "name": "Moonshot / Kimi", "currency": "CNY",
        "url": "https://api.moonshot.cn/v1/users/me/balance",
        "console": "https://platform.moonshot.cn",
        "hint": "区分现金余额与代金券",
    },
    {
        "id": "siliconflow_cn", "group": "auto", "kind": "balance", "name": "硅基流动 (国内站)", "currency": "CNY",
        "url": "https://api.siliconflow.cn/v1/user/info",
        "console": "https://cloud.siliconflow.cn",
        "hint": "接口不返回币种，按国内站惯例视为 CNY",
    },
    {
        "id": "siliconflow_global", "group": "auto", "kind": "balance", "name": "SiliconFlow (国际站)", "currency": "USD",
        "url": "https://api.siliconflow.com/v1/user/info",
        "console": "https://cloud.siliconflow.com",
        "hint": "国际站按美元计价",
    },
    {
        "id": "stepfun", "group": "auto", "kind": "balance", "name": "阶跃星辰 StepFun", "currency": "CNY",
        "url": "https://api.stepfun.com/v1/accounts",
        "console": "https://platform.stepfun.com",
        "hint": "按量计费账户；Step Plan 套餐无公开接口",
    },
    {
        "id": "anthropic", "group": "auto", "kind": "spend", "name": "Claude / Anthropic", "currency": "USD",
        "console": "https://platform.claude.com/settings/billing",
        "hint": "官方无余额接口，用 Admin Key 查本月花费",
        "key_hint": "Admin Key（sk-ant-admin01-…）",
    },
    {
        "id": "openai", "group": "auto", "kind": "spend", "name": "OpenAI", "currency": "USD",
        "console": "https://platform.openai.com/settings/organization/billing/overview",
        "hint": "官方无余额接口，用 Admin Key 查本月花费",
        "key_hint": "Admin Key（sk-admin-…）",
    },
    {
        "id": "openrouter", "group": "auto", "kind": "balance", "name": "OpenRouter", "currency": "USD",
        "url": "https://openrouter.ai/api/v1/credits",
        "console": "https://openrouter.ai/settings/credits",
        "hint": "余额 = 总充值 − 总消耗，需 Management Key",
        "alt_url": "https://openrouter.ai/api/v1/key",
    },
    {
        "id": "novita", "group": "auto", "kind": "balance", "name": "Novita AI", "currency": "USD",
        "url": "https://api.novita.ai/v3/user/balance",
        "console": "https://novita.ai/settings/key-management",
        "hint": "字段以实际返回为准",
    },
    {
        "id": "xai", "group": "auto", "kind": "balance", "name": "xAI (Grok)", "currency": "USD",
        "url": "https://api.x.ai/v1/billing/credits",
        "console": "https://console.x.ai",
        "hint": "字段以实际返回为准",
    },
    {
        "id": "zhipu", "group": "auto", "kind": "quota", "name": "智谱 GLM", "currency": "CNY",
        "url": "https://open.bigmodel.cn/api/monitor/usage/quota/limit",
        "console": "https://bigmodel.cn/usercenter/financial",
        "hint": "无余额接口，只能查资源包配额",
    },
    {
        "id": "zai", "group": "auto", "kind": "quota", "name": "Z.AI (GLM 国际)", "currency": "USD",
        "url": "https://api.z.ai/api/monitor/usage/quota/limit",
        "console": "https://z.ai/manage-apikey/apikey-list",
        "hint": "同上，返回配额窗口",
    },
    {
        "id": "minimax_cn", "group": "auto", "kind": "quota", "name": "MiniMax (国内)", "currency": "CNY",
        "url": "https://api.minimaxi.com/v1/token_plan/remains",
        "console": "https://platform.minimaxi.com",
        "hint": "Coding 套餐余量（5 小时窗口）",
    },
    {
        "id": "kimi_coding", "group": "auto", "kind": "quota", "name": "Kimi Coding 套餐", "currency": "CNY",
        "url": "https://api.kimi.com/coding/v1/usages",
        "console": "https://platform.moonshot.cn",
        "hint": "编程套餐的 5 小时 / 每周窗口用量",
    },
    {
        "id": "custom", "group": "auto", "kind": "custom", "name": "自定义 / 中转站", "currency": "CNY",
        "url": "", "console": "",
        "hint": "302.AI、AiHubMix、new-api 等站点填 baseURL",
        "custom": True,
    },

    # ================= 官方无接口，手动记账 =================
    {
        "id": "gemini", "group": "manual", "kind": "manual", "name": "Google Gemini", "currency": "USD",
        "console": "https://aistudio.google.com/apikey",
        "hint": "额度绑 GCP 结算账号，需 Cloud Billing 凭据",
    },
    {
        "id": "aliyun", "group": "manual", "kind": "manual", "name": "阿里云百炼 / 通义千问", "currency": "CNY",
        "console": "https://bailian.console.aliyun.com",
        "hint": "余额在阿里云账户，需 BSS OpenAPI + AK/SK",
    },
    {
        "id": "volcengine", "group": "manual", "kind": "manual", "name": "火山方舟 (豆包)", "currency": "CNY",
        "console": "https://console.volcengine.com/ark",
        "hint": "需火山引擎 AK/SK 签名调用 OpenAPI",
    },
    {
        "id": "hunyuan", "group": "manual", "kind": "manual", "name": "腾讯混元", "currency": "CNY",
        "console": "https://console.cloud.tencent.com/hunyuan",
        "hint": "余额走腾讯云账户，需 SecretId/Key",
    },
    {
        "id": "qianfan", "group": "manual", "kind": "manual", "name": "百度千帆 / 文心", "currency": "CNY",
        "console": "https://console.bce.baidu.com/qianfan",
        "hint": "需百度云 AK/SK 查财务接口",
    },
    {
        "id": "xfyun", "group": "manual", "kind": "manual", "name": "讯飞星火", "currency": "CNY",
        "console": "https://console.xfyun.cn",
        "hint": "控制台查看剩余额度，无公开余额接口",
    },
    {
        "id": "lingyi", "group": "manual", "kind": "manual", "name": "零一万物 Yi", "currency": "CNY",
        "console": "https://platform.lingyiwanwu.com",
        "hint": "控制台查看",
    },
    {
        "id": "baichuan", "group": "manual", "kind": "manual", "name": "百川智能", "currency": "CNY",
        "console": "https://platform.baichuan-ai.com",
        "hint": "控制台查看",
    },
    {
        "id": "mistral", "group": "manual", "kind": "manual", "name": "Mistral AI", "currency": "USD",
        "console": "https://console.mistral.ai/billing",
        "hint": "余额接口需浏览器 Cookie，官方无 API Key 通道",
    },
    {
        "id": "together", "group": "manual", "kind": "manual", "name": "Together AI", "currency": "USD",
        "console": "https://api.together.ai/settings/billing",
        "hint": "控制台查看余额",
    },
    {
        "id": "groq", "group": "manual", "kind": "manual", "name": "Groq", "currency": "USD",
        "console": "https://console.groq.com/settings/billing",
        "hint": "免费额度按天刷新，无余额概念",
    },
    {
        "id": "deepinfra", "group": "manual", "kind": "manual", "name": "DeepInfra", "currency": "USD",
        "console": "https://deepinfra.com/dash/billing",
        "hint": "控制台查看",
    },
    {
        "id": "fireworks", "group": "manual", "kind": "manual", "name": "Fireworks AI", "currency": "USD",
        "console": "https://fireworks.ai/account/billing",
        "hint": "控制台查看",
    },
    {
        "id": "cerebras", "group": "manual", "kind": "manual", "name": "Cerebras", "currency": "USD",
        "console": "https://cloud.cerebras.ai",
        "hint": "免费层按天计数，无余额接口",
    },
    {
        "id": "perplexity", "group": "manual", "kind": "manual", "name": "Perplexity", "currency": "USD",
        "console": "https://www.perplexity.ai/settings/api",
        "hint": "控制台查看额度",
    },
    {
        "id": "cohere", "group": "manual", "kind": "manual", "name": "Cohere", "currency": "USD",
        "console": "https://dashboard.cohere.com/billing",
        "hint": "控制台查看",
    },
    {
        "id": "azure", "group": "manual", "kind": "manual", "name": "Azure OpenAI", "currency": "USD",
        "console": "https://portal.azure.com",
        "hint": "走 Azure 订阅额度，需 Azure 管理凭据",
    },
    {
        "id": "bedrock", "group": "manual", "kind": "manual", "name": "AWS Bedrock", "currency": "USD",
        "console": "https://console.aws.amazon.com/billing",
        "hint": "走 AWS 账单，需 Cost Explorer 权限",
    },
]

PROVIDER_MAP = {p["id"]: p for p in PROVIDERS}


# ---------------------------------------------------------------- HTTP 请求
def http_get(url, key=None, timeout=20, headers=None):
    h = {"Accept": "application/json", "User-Agent": UA}
    if key:
        h["Authorization"] = "Bearer " + key
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, method="GET")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body, int((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, body, int((time.time() - t0) * 1000)
    except Exception as e:  # 网络不通、超时、DNS 等
        return 0, json.dumps({"client_error": str(e)}, ensure_ascii=False), int((time.time() - t0) * 1000)


# ---------------------------------------------------------------- 工具函数
def num(v):
    """把接口返回的钱数统一成好看的字符串。"""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f) and abs(f) < 1e15:
        return f"{int(f):,}"
    return f"{f:,.4f}".rstrip("0").rstrip(".")


def net_error_hint(raw):
    """把底层网络异常翻译成能看懂的提示。"""
    s = str(dig(raw or {}, "client_error", "")).lower()
    if "tunnel" in s or "proxy" in s:
        return "代理连接失败，检查一下代理设置，或先关掉代理再试"
    if "timed out" in s or "timeout" in s:
        return "请求超时，境外接口可能需要稳定代理"
    if "name or service" in s or "getaddrinfo" in s or "name resolution" in s:
        return "域名解析失败，检查网络或 DNS"
    if "ssl" in s or "certificate" in s:
        return "SSL 握手失败，排查代理或防火墙"
    return "连不上接口，检查网络或代理"


def dig(obj, path, default=None):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def scan(obj, hints):
    """兜底：在未知结构的 JSON 里找名字含 balance/remain 之类关键字的数值字段。"""
    out = {}

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                if isinstance(v, (int, float)) and any(h in kl for h in hints):
                    out.setdefault(str(k), v)
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for i in node:
                walk(i)

    walk(obj)
    return out


LABELS = {
    "currentValue": "已用", "totalValue": "总量", "percentage": "使用率",
    "limit": "上限", "used": "已用", "remaining": "剩余", "remain": "剩余",
    "balance": "余额", "total_balance": "总余额", "total": "总额",
    "available": "可用", "credit": "额度", "total_credits": "总额度",
    "total_usage": "已消耗", "is_available": "可调用",
}


def rows_from_scanned(sc, label_map=None):
    rows = []
    for k, v in sc.items():
        name = (label_map or {}).get(k) or LABELS.get(k) or k
        val = num(v)
        if val is not None and "percent" in str(k).lower():
            val = f"{val}%"
        rows.append([name, val])
    return rows[:6]


# ---------------------------------------------------------------- 各家解析器
def p_deepseek(j, raw):
    infos = j.get("balance_infos") or []
    if not infos:
        return None
    item = next((i for i in infos if i.get("currency") == "CNY"), infos[0])
    return {
        "main": num(item.get("total_balance")),
        "currency": item.get("currency") or "CNY",
        "rows": [
            ["充值余额", num(item.get("topped_up_balance"))],
            ["赠送余额", num(item.get("granted_balance"))],
            ["可调用", "是" if j.get("is_available") else "否（余额不足）"],
        ],
    }


def p_moonshot(j, raw):
    d = j.get("data") or {}
    main = d.get("available_balance")
    if main is None:
        return None
    return {
        "main": num(main), "currency": "CNY",
        "rows": [["现金余额", num(d.get("cash_balance"))],
                 ["代金券", num(d.get("voucher_balance"))]],
    }


def p_siliconflow(j, raw):
    d = j.get("data") or {}
    main = d.get("totalBalance")
    if main is None:
        return None
    return {
        "main": num(main), "currency": "CNY",
        "rows": [["充值余额", num(d.get("chargeBalance"))],
                 ["赠送余额", num(d.get("balance"))]],
    }


def p_stepfun(j, raw):
    if j.get("balance") is None:
        return None
    return {
        "main": num(j.get("balance")), "currency": "CNY",
        "rows": [["总充值", num(j.get("total_cash_balance"))],
                 ["总赠送", num(j.get("total_voucher_balance"))],
                 ["账户类型", {"prepaid": "预付费", "postpaid": "后付费"}.get(j.get("type"), j.get("type"))]],
    }


def p_openrouter(j, raw):
    d = j.get("data") or {}
    if "total_credits" in d:
        try:
            left = float(d.get("total_credits") or 0) - float(d.get("total_usage") or 0)
        except (TypeError, ValueError):
            left = None
        return {
            "main": num(left), "currency": "USD",
            "rows": [["总充值", num(d.get("total_credits"))],
                     ["已消耗", num(d.get("total_usage"))],
                     ["说明", "剩余 = 总充值 − 已消耗"]],
        }
    # 普通 API Key 走的 /api/v1/key
    if "limit_remaining" in d or "usage" in d:
        return {
            "main": num(d.get("limit_remaining")), "currency": "USD",
            "rows": [["额度上限", num(d.get("limit"))],
                     ["已用", num(d.get("usage"))],
                     ["说明", "普通 Key 只能看到该 Key 的额度"]],
        }
    return None


def p_custom(j, raw):
    """one-api / new-api：quota 单位是 500000 = $1。"""
    d = j.get("data") or {}
    quota = d.get("quota")
    if quota is None:
        return None
    try:
        left = float(quota) / 500000.0
        used = float(d.get("used_quota") or 0) / 500000.0
    except (TypeError, ValueError):
        return None
    return {
        "main": num(left), "currency": "USD",
        "rows": [["已消耗", num(used)], ["用户名", d.get("username") or "-"],
                 ["说明", "按 500000 quota = $1 折算"]],
    }


def p_generic(j, raw):
    sc = scan(j, ["balance", "remain", "credit", "available", "total"])
    if not sc:
        return None

    def mag(kv):
        try:
            return abs(float(kv[1]))
        except (TypeError, ValueError):
            return 0.0

    label = {"balance": "余额", "total_balance": "总余额", "remaining": "剩余",
             "available": "可用", "total": "总额"}
    items = sorted(sc.items(), key=lambda kv: -mag(kv))
    best_key = None
    for k, _ in items:
        kl = str(k).lower()
        if "balance" in kl or "remain" in kl:
            best_key = (k, sc[k])
            break
    if best_key is None:
        best_key = items[0]
    return {
        "main": num(best_key[1]), "currency": None,
        "rows": rows_from_scanned({k: v for k, v in items[:5]}, label),
        "note": "字段为自动识别，如不准请看原始响应",
    }


def p_quota(j, raw):
    """智谱 / MiniMax 这类配额接口：找出用量百分比或剩余量。"""
    sc = scan(j, ["limit", "used", "remain", "current", "total", "percent"])
    if not sc:
        return None
    return {
        "main": None, "currency": None,
        "rows": rows_from_scanned(sc),
        "note": "这是套餐配额接口，不是余额；数值含义见原始响应",
    }


PARSERS = {
    "deepseek": p_deepseek,
    "moonshot": p_moonshot,
    "siliconflow_cn": p_siliconflow,
    "siliconflow_global": p_siliconflow,
    "stepfun": p_stepfun,
    "openrouter": p_openrouter,
    "custom": p_custom,
    "zhipu": p_quota,
    "zai": p_quota,
    "minimax_cn": p_quota,
    "kimi_coding": p_quota,
}


# ---------------------------------------------------------------- 花费查询
def month_range():
    """本月 1 日 0 点（UTC）到当前时刻。"""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now


def q_spend(pid, key):
    """Claude / OpenAI 官方不提供余额，只能查本月花费。"""
    first, now = month_range()
    if pid == "anthropic":
        url = ("https://api.anthropic.com/v1/organizations/cost_report"
               f"?starting_at={first.strftime('%Y-%m-%dT%H:%M:%SZ')}"
               f"&ending_at={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
               "&bucket_width=1d&limit=31")
        status, body, ms = http_get(url, None, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        url = ("https://api.openai.com/v1/organization/costs"
               f"?start_time={int(first.timestamp())}&bucket_width=1d&limit=31")
        status, body, ms = http_get(url, key)

    try:
        j = json.loads(body)
    except Exception:
        j = None

    if status == 0:
        return {"ok": False, "error": net_error_hint(j), "raw": j}
    if status in (401, 403):
        return {"ok": False, "status": status, "raw": j,
                "error": f"鉴权失败（HTTP {status}）：需要组织管理员创建的 Admin Key，普通项目 Key 不行"}
    if j is None:
        return {"ok": False, "status": status,
                "error": f"返回的不是 JSON（HTTP {status}）", "raw_text": body[:800]}

    total = 0.0
    points = 0
    for bucket in (j.get("data") or []):
        for item in (bucket.get("results") or []):
            amt = item.get("amount")
            if isinstance(amt, dict):                      # OpenAI: {"value": 0.06, "currency": "usd"}
                v = amt.get("value")
                if v is not None:
                    total += float(v)
                    points += 1
            elif amt is not None:                          # Anthropic: 美分字符串
                try:
                    total += float(amt) / 100.0
                    points += 1
                except (TypeError, ValueError):
                    pass

    return {"ok": True, "kind": "spend", "main": num(round(total, 4)), "currency": "USD",
            "rows": [["统计区间", f"{first:%m-%d} 至今"], ["数据点", f"{points} 条"]],
            "note": "这是本月花费，不是余额。官方没有余额接口，剩余额度请在下方手动填",
            "status": status, "elapsed": ms, "raw": j}


# ---------------------------------------------------------------- 查询主逻辑
def query(provider_id, key, base_url=""):
    p = PROVIDER_MAP.get(provider_id)
    if not p:
        return {"ok": False, "error": "未知服务商"}

    kind = p["kind"]
    if kind == "manual":
        return {"ok": False, "manual": True, "error": p["hint"], "console": p.get("console")}
    if kind == "spend":
        if not key:
            return {"ok": False, "error": "还没填 Admin Key"}
        return q_spend(provider_id, key)

    url = p["url"]
    if kind == "custom":
        if not base_url:
            return {"ok": False, "error": "请填写中转站 baseURL，例如 https://api.xxx.com/v1"}
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        url = base + "/api/user/self"

    if not key:
        return {"ok": False, "error": "还没填 API Key"}

    status, body, ms = http_get(url, key)

    try:
        j = json.loads(body)
    except Exception:
        j = None

    # OpenRouter 的 /credits 需要 Management Key，失败时自动退到 /key
    if p["id"] == "openrouter" and (status != 200 or j is None) and p.get("alt_url"):
        s2, b2, m2 = http_get(p["alt_url"], key)
        if s2 == 200:
            try:
                j2 = json.loads(b2)
                r2 = p_openrouter(j2, b2)
                if r2:
                    r2["status"] = s2
                    r2["elapsed"] = ms + m2
                    r2["raw"] = j2
                    r2["note"] = "未用 Management Key，已回退到单 Key 额度查询"
                    return {"ok": True, **r2}
            except Exception:
                pass

    if status == 0:
        return {"ok": False, "error": net_error_hint(j), "raw": j}

    if status in (401, 403):
        return {"ok": False, "status": status,
                "error": f"鉴权失败（HTTP {status}）：Key 无效、过期，或权限不足", "raw": j}

    if j is None:
        return {"ok": False, "status": status,
                "error": f"返回的不是 JSON（HTTP {status}）", "raw_text": body[:800]}

    parser = PARSERS.get(p["id"], p_generic)
    res = parser(j, body)
    if res is None:
        res = p_generic(j, body)
    if res is None:
        return {"ok": False, "status": status,
                "error": "接口有响应，但没认出余额字段（可能是平台改了结构）", "raw": j}

    res["status"] = status
    res["elapsed"] = ms
    res["raw"] = j
    if not res.get("currency"):
        res["currency"] = p.get("currency")
    return {"ok": True, **res}


# ---------------------------------------------------------------- 本地密钥存储
_keys_lock = threading.Lock()


def load_keys():
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_keys(data):
    with _keys_lock:
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(KEYS_FILE, 0o600)
    except Exception:
        pass


def mask(k):
    if not k:
        return ""
    if len(k) <= 10:
        return k[:2] + "*" * (len(k) - 4) + k[-2:]
    return k[:6] + "*" * 6 + k[-4:]


# ---------------------------------------------------------------- Web 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "AIBalance/1.0"

    def log_message(self, fmt, *args):
        pass  # 安静模式，别把 key 之类刷到终端

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            idx = os.path.join(BASE_DIR, "index.html")
            try:
                with open(idx, "r", encoding="utf-8") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, {"error": "index.html 不见了"})
            return

        if self.path == "/api/providers":
            safe = []
            for p in PROVIDERS:
                q = dict(p)
                safe.append(q)
            self._send(200, {"providers": safe})
            return

        if self.path == "/api/keys":
            keys = load_keys()
            self._send(200, {pid: mask(v) for pid, v in keys.items() if v})
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send(400, {"ok": False, "error": "请求体不是合法 JSON"})
            return

        if self.path == "/api/query":
            pid = payload.get("id", "")
            key = (payload.get("key") or "").strip()
            if not key:
                key = load_keys().get(pid, "")
            try:
                self._send(200, query(pid, key, payload.get("baseUrl", "")))
            except Exception as e:
                self._send(200, {"ok": False, "error": f"查询出错：{e}"})
            return

        if self.path == "/api/keys":
            pid = payload.get("id")
            val = (payload.get("key") or "").strip()
            if not pid:
                self._send(400, {"ok": False, "error": "缺少 id"})
                return
            keys = load_keys()
            if val:
                keys[pid] = val
            else:
                keys.pop(pid, None)
            save_keys(keys)
            self._send(200, {"ok": True})
            return

        self._send(404, {"error": "not found"})


def main():
    # 端口被占用就顺延
    global PORT
    srv = None
    for offset in range(12):
        try:
            srv = ThreadingHTTPServer((HOST, PORT + offset), Handler)
            PORT = PORT + offset
            break
        except OSError:
            continue
    if srv is None:
        print("端口 7788-7799 都被占用了，请设置环境变量 AI_BALANCE_PORT 换个端口。")
        sys.exit(1)

    url = f"http://{HOST}:{PORT}"
    print("=" * 52)
    print("  AI API 余额聚合查询")
    print(f"  打开：{url}")
    print("  密钥只存在本机 keys.json，不会发到别处")
    print("  按 Ctrl+C 退出")
    print("=" * 52)
    if not os.environ.get("AI_BALANCE_NO_OPEN"):
        threading.Timer(0.8, lambda: open_browser(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
        srv.server_close()


def open_browser(url):
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    main()
