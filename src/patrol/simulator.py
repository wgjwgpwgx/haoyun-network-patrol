"""模拟设备服务器 CLI 入口

用法:
    python -m patrol.simulator --seed huawei            # 内置华为样例
    python -m patrol.simulator --knowledge 客户/设备     # 知识库快照
    python -m patrol.simulator --port 9123 --seed zte

启动后:本项目设备档案 → 登录方式 Telnet、IP 127.0.0.1、端口见输出、
账号密码任意 → 发起巡检即可全流程演示。
Ctrl+C 停止。
"""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="模拟网络设备(Telnet)")
    parser.add_argument("--seed", help="内置样例厂商: huawei/h3c/zte/"
                        "maipu/ruijie")
    parser.add_argument("--knowledge", help="知识库 客户/设备 名")
    parser.add_argument("--port", type=int, default=9123)
    args = parser.parse_args()

    from patrol.simulator_core import (
        SimDeviceServer, responses_from_knowledge, responses_from_seed,
    )

    responses: dict[str, str] = {}
    label = ""
    if args.seed:
        responses = responses_from_seed(args.seed)
        label = f"内置样例:{args.seed}"
    elif args.knowledge:
        try:
            customer, device = args.knowledge.split("/", 1)
        except ValueError:
            print("错误: --knowledge 格式为 客户/设备")
            return 1
        responses = responses_from_knowledge(customer, device)
        label = f"知识库:{args.knowledge}"
    if not responses:
        print("错误: 未取得命令响应表(--seed 或 --knowledge 至少其一)")
        return 1

    server = SimDeviceServer(port=args.port, responses=responses)
    port = server.start()
    print(f"模拟设备({label})已启动")
    print(f"  地址: 127.0.0.1:{port}  协议: Telnet  账号密码: 任意")
    print(f"  命令数: {len(responses)}")
    print("设备档案填写示例 → 登录方式: Telnet / IP: 127.0.0.1 / "
          f"端口: {port} / 用户名密码任意。Ctrl+C 停止。")
    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
        print("\n模拟设备已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
