"""大模型厂商预设(OpenAI Chat Completions 兼容)

2026-09 联网核实:以下接口均为 POST {base_url}/chat/completions + Bearer 鉴权,
差异只在 base_url 的版本路径。模型名随厂商迭代会变,界面里可手改,
下拉预设只负责把 base_url 与常用模型填对。
"""
from __future__ import annotations

# (分组, [预设...]) —— 预设字段: id/name/base_url/models/key_url/note
PRESET_GROUPS: list[tuple[str, list[dict]]] = [
    ("国内厂商", [
        {
            "id": "deepseek", "name": "DeepSeek 深度求索",
            "base_url": "https://api.deepseek.com",
            "models": ["deepseek-v4-pro", "deepseek-flash", "deepseek-chat"],
            "key_url": "https://platform.deepseek.com/api_keys",
            "note": "",
        },
        {
            "id": "zhipu", "name": "智谱 AI (GLM)",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "models": ["glm-5.3-flash", "glm-5.3", "glm-5.2"],
            "key_url": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
            "note": "",
        },
        {
            "id": "qwen", "name": "阿里 通义千问 (百炼)",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "models": ["qwen3.8-flash", "qwen3.7-plus", "qwen3.8-max"],
            "key_url": "https://bailian.console.aliyun.com/model/settings/api-key",
            "note": "",
        },
        {
            "id": "kimi", "name": "月之暗面 Kimi",
            "base_url": "https://api.moonshot.cn/v1",
            "models": ["kimi-k3", "kimi-k2.6", "moonshot-v1-8k"],
            "key_url": "https://platform.kimi.com/console/api-keys",
            "note": "",
        },
        {
            "id": "doubao", "name": "字节 豆包 (火山方舟)",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "models": ["doubao-seed-2-1-pro", "doubao-seed-2-1-turbo", "doubao-seed-2-0-lite"],
            "key_url": "https://ark.volcengine.com/region:cn-beijing/apiKey",
            "note": "模型名也可填控制台创建的推理接入点 ep-...",
        },
        {
            "id": "ernie", "name": "百度 文心 (千帆)",
            "base_url": "https://qianfan.baidubce.com/v2",
            "models": ["ernie-5.1", "ernie-4.5-turbo-32k", "ernie-5.0-thinking-preview"],
            "key_url": "https://console.bce.baidu.com/qianfan/ais/console/apiKey",
            "note": "千帆的 OpenAI 兼容路径是 /v2",
        },
        {
            "id": "spark", "name": "讯飞 星火 Spark",
            "base_url": "https://spark-api-open.xf-yun.com/v1",
            "models": ["4.0Ultra", "generalv3.5", "lite"],
            "key_url": "https://console.xfyun.cn/services/bmx1",
            "note": "密钥即 APIPassword;模型名大小写敏感",
        },
        {
            "id": "hunyuan", "name": "腾讯 混元",
            "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
            "models": ["hunyuan-turbos-latest", "hunyuan-lite"],
            "key_url": "https://console.cloud.tencent.com/hunyuan/start",
            "note": "",
        },
        {
            "id": "minimax", "name": "MiniMax",
            "base_url": "https://api.minimaxi.com/v1",
            "models": ["MiniMax-M2.5-highspeed", "MiniMax-Text-01"],
            "key_url": "https://platform.minimaxi.com/user-center/basic-information/interface-key",
            "note": "以控制台模型列表为准",
        },
        {
            "id": "baichuan", "name": "百川智能",
            "base_url": "https://api.baichuan-ai.com/v1",
            "models": ["Baichuan-M3", "Baichuan-M3-Plus"],
            "key_url": "https://platform.baichuan-ai.com/console/apikey",
            "note": "",
        },
    ]),
    ("聚合/开源平台", [
        {
            "id": "siliconflow", "name": "硅基流动 SiliconFlow",
            "base_url": "https://api.siliconflow.cn/v1",
            "models": [
                "deepseek-ai/DeepSeek-V4-Flash",
                "Pro/deepseek-ai/DeepSeek-R1",
                "moonshotai/Kimi-K2.7-Code",
            ],
            "key_url": "https://cloud.siliconflow.cn/account/ak",
            "note": "模型名带组织前缀",
        },
    ]),
    ("本地部署", [
        {
            "id": "ollama", "name": "Ollama (本地模型)",
            "base_url": "http://127.0.0.1:11434/v1",
            "models": ["qwen3", "deepseek-r1", "llama3.1"],
            "key_url": "",
            "note": "无需申请密钥,api_key 随意填非空值",
        },
    ]),
    ("其他", [
        {
            "id": "openai", "name": "OpenAI 及兼容服务",
            "base_url": "https://api.openai.com/v1",
            "models": ["gpt-4o-mini", "gpt-4o"],
            "key_url": "https://platform.openai.com/api-keys",
            "note": "",
        },
        {
            "id": "custom", "name": "自定义 (任意 OpenAI 兼容)",
            "base_url": "",
            "models": [],
            "key_url": "",
            "note": "手填接口地址与模型",
        },
    ]),
]


def all_presets() -> list[dict]:
    """展平的全部预设。"""
    return [p for _, items in PRESET_GROUPS for p in items]


def match_preset(base_url: str) -> str | None:
    """按 base_url 反查预设 id(用于界面回显选中项),匹配不到返回 None。

    对结尾的 /v1 别名归一化(如 https://api.deepseek.com 与 .../v1 等价)。
    """
    def _norm(u: str) -> str:
        u = (u or "").strip().rstrip("/")
        return u[:-3] if u.endswith("/v1") else u

    url = _norm(base_url)
    if not url:
        return None
    for p in all_presets():
        if p["base_url"] and url == _norm(p["base_url"]):
            return p["id"]
    return None
