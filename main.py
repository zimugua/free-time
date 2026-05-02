"""
命令行入口（备用）
推荐使用 Web UI：python app.py
"""
from agent import ActivityPlannerAgent


def main():
    agent = ActivityPlannerAgent()
    print("美团智能出行规划 Agent（命令行模式）")
    print("输入出行需求，回车开始规划（输入 q 退出）\n")

    while True:
        user_input = input("请输入需求 > ").strip()
        if user_input.lower() in ("q", "quit", "exit"):
            print("再见！")
            break
        if not user_input:
            continue
        for chunk in agent.plan_and_execute_stream(user_input):
            # 命令行模式：打印最后一段（覆盖式打印）
            import os
            os.system("cls" if os.name == "nt" else "clear")
            print(chunk)
        print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    main()
