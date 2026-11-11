"""KLinePlayground AI 配置工具

把 base_url / model / api_key 写入主程序读取的加密配置文件：
    <项目根>/data/.ai_tester_config.enc

用法：
    交互式：  python set_ai_config.py
    命令行：  python set_ai_config.py --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key sk-xxx
"""

import argparse
import base64
import getpass
import json
import sys
from pathlib import Path

CONFIG_KEY = "kline_trainer_secret_key"
CONFIG_NAME = ".ai_tester_config.enc"

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def project_root() -> Path:
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return project_root() / "data" / CONFIG_NAME


def xor_crypt(text: str) -> str:
    return "".join(
        chr(ord(c) ^ ord(CONFIG_KEY[i % len(CONFIG_KEY)])) for i, c in enumerate(text)
    )


def save_config(config: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = base64.b64encode(xor_crypt(json.dumps(config, ensure_ascii=False)).encode("utf-8"))
    path.write_text(payload.decode("utf-8"), encoding="utf-8")
    return path


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    obfs = path.read_text(encoding="utf-8").strip()
    if not obfs:
        return {}
    return json.loads(xor_crypt(base64.b64decode(obfs).decode("utf-8")))


def test_connection(base_url: str, model: str, api_key: str) -> str:
    """用一次极小请求验证地址、模型与 Key 是否可用。"""
    try:
        import requests
    except ImportError:
        return "未安装 requests，跳过测试"

    url = base_url.rstrip("/") + "/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "回复两个字：正常"}],
                "max_tokens": 16,
                "temperature": 0,
            },
            timeout=30,
        )
    except Exception as exc:
        return "请求失败：%s" % exc

    if resp.status_code == 200:
        try:
            data = resp.json()
            return "连通成功，模型回复：%s" % data["choices"][0]["message"]["content"].strip()
        except Exception:
            return "返回 200，但响应结构不是 OpenAI 兼容格式，请检查地址"
    if resp.status_code == 401:
        return "Key 无效或未开通（401）。地址与模型名本身是通的"
    return "HTTP %d：%s" % (resp.status_code, resp.text[:200])


def main():
    parser = argparse.ArgumentParser(description="配置 KLinePlayground 的 AI 接口")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--show", action="store_true", help="只打印当前配置")
    args = parser.parse_args()

    if args.show:
        cfg = load_config()
        if not cfg:
            print("当前没有 AI 配置")
            return 0
        for k in ("base_url", "model"):
            print("%s = %s" % (k, cfg.get(k)))
        key = cfg.get("api_key") or ""
        print("api_key = %s" % (key[:6] + "..." + key[-4:] if len(key) > 12 else ("(空)" if not key else key)))
        return 0

    old = load_config()
    base_url = args.base_url or input("接口地址 [%s]: " % (old.get("base_url") or DEFAULT_BASE_URL)).strip()
    if not base_url:
        base_url = old.get("base_url") or DEFAULT_BASE_URL
    model = args.model or input("模型名 [%s]: " % (old.get("model") or DEFAULT_MODEL)).strip()
    if not model:
        model = old.get("model") or DEFAULT_MODEL
    api_key = args.api_key
    if not api_key:
        api_key = getpass.getpass("API Key（输入不显示）: ").strip()
    if not api_key:
        print("没有提供 Key，未写入配置")
        return 1

    cfg = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "bar_count": old.get("bar_count", 80),
        "include_indicator": old.get("include_indicator", True),
        "indicator_type": old.get("indicator_type", "MACD"),
        "include_chip": old.get("include_chip", True),
        "strategy": old.get("strategy", ""),
    }
    path = save_config(cfg)
    print("已写入：%s" % path)
    print("测试连接：%s" % test_connection(base_url, model, api_key))
    print("提示：每次生成复盘报告都会重新读取该文件，无需重启主程序")
    return 0


if __name__ == "__main__":
    sys.exit(main())
