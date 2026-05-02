"""
出行计划生成 Prompt
用于将结构化的规划信息转换为自然语言计划文案
支持：多方案展示、用户称呼、时间线、多活动安排、路程时间
"""

PLAN_SYSTEM_PROMPT = """你是美团App里的智能出行规划助手，语气亲切活泼。
根据用户提供的出行规划信息，生成一段完整的「出行计划方案」。
要求：
- 用 {user_name} 称呼用户（如"小张！这是为您准备的..."），如果 user_name 为"用户"则省略称呼直接开始
- 按时间线展示完整行程（出发→路程→活动1→...→等待→路程→用餐→...→结束）
- 每段路程要标注交通方式（🚶步行/🚲骑行/🚇地铁/🚗打车）和预计耗时
- 如果有"等待就餐"信息，必须在时间线中展示等待段落，格式如：
  ⏳ 等待就餐（约N分钟）
  💡 推荐以下方式消磨时间：
    （列出建议，每条带emoji）
  然后是"出发前往餐厅"
- 用 emoji 装饰，让方案看起来生动有趣
- 体现对群体特殊需求的关怀（如减肥、小孩、团建等）
- 结尾附一句温馨提示
- 全程中文，不超过800字"""


def build_plan_user_prompt(context: dict) -> str:
    """
    根据规划结果上下文构建用户侧 Prompt。

    :param context: 包含场景、用户名、活动列表、餐厅、路程等信息的字典
    :return: 格式化后的用户 Prompt 字符串
    """
    scene_label = "家庭亲子" if context.get("scene") == "family" else "朋友聚会"
    user_name = context.get("user_name", "")
    special_note = context.get("special_note", "无")
    route_summary = context.get("route_summary", "")

    # 构建活动时间线
    activities = context.get("activities", [])
    activity_lines = []
    for i, act in enumerate(activities, 1):
        activity_lines.append(
            f"活动{i}：{act['name']}"
            f"（{act['duration_hours']}h，地址：{act.get('address', '')}）"
            f"，{act.get('start_time', '')} 开始"
            f"，{act.get('end_time', '')} 结束"
        )

    # 餐厅信息
    restaurant = context.get("restaurant", {})
    rest_text = ""
    if restaurant:
        rest_text = (
            f"用餐安排：{restaurant.get('name', '')}（{restaurant.get('cuisine', '')}，"
            f"地址：{restaurant.get('address', '')}）"
            f"，{restaurant.get('meal_time', '')} 就餐"
            f"，{restaurant.get('meal_label', '')}"
        )

    prompt = (
        f"用户姓名：{user_name if user_name else '未指定'}\n"
        f"场景：{scene_label}\n"
        f"人数：{context['people']} 人\n"
        f"出发时间：{context.get('start_time', '')}\n"
        f"活动总时长：{context.get('total_activity_hours', 0)}小时\n"
        f"特殊备注：{special_note}\n\n"
    )

    # 路程信息（如果有）
    if route_summary:
        prompt += f"路程信息：\n{route_summary}\n\n"

    prompt += (
        f"活动安排（按时间顺序）：\n" + "\n".join(activity_lines) + "\n\n"
        f"{rest_text}\n\n"
    )

    # 等待就餐信息（用户选择等到就餐时间时）
    wait_info = context.get("wait_info")
    if context.get("has_wait") and wait_info:
        wait_text = (
            f"等待就餐：{wait_info.get('label', '')}\n"
            f"等待开始：{wait_info.get('start', '')}，等待结束：{wait_info.get('end', '')}\n"
        )
        suggestions = wait_info.get("suggestions", [])
        if suggestions:
            wait_text += f"打发时间建议（请在行程中展示以下内容）：\n"
            for s in suggestions:
                wait_text += f"  {s}\n"
        prompt += wait_text + "\n"

    prompt += (
        f"预订信息：\n"
        f"- 活动预订号：{context.get('ticket_ids', [])}\n"
        f"- 餐厅预订号：{context.get('booking_id', '')}"
    )

    return prompt
