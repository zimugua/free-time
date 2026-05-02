"""
Web UI 入口
基于 Gradio 构建，全自动流水线：
  输入需求 → 自动执行所有步骤 → 需要确认时暂停 → 用户确认后自动继续

流程顺序（共9步）：
1. 解析意图 + 用户信息
2. 搜索活动方案
3. 搜索餐厅 → 暂停让用户选择餐厅
4. 为各方案匹配餐厅座位
5. 检查餐前空隙 → 暂停让用户选择餐前活动（可多选，不选则不加）
6. 用餐时间确认 → 如不在常规窗口，暂停让用户确认
7. 告知结束时间 + 检查餐后空隙 → 暂停让用户选择餐后活动
8. 方案对比 → 暂停让用户选方案
9. 预订 + 生成完整行程
"""
import gradio as gr
from agent import ActivityPlannerAgent
from llm import load_config
from datetime import datetime, timedelta

# 预设示例
EXAMPLES = [
    ["今天下午是空的，想和老婆孩子出去玩几个小时，别离家太远，帮我安排。孩子5岁，老婆最近在减肥。"],
    ["今天下午想和4个朋友出去玩，2男2女，帮我规划一下，总共4-5小时。"],
    ["明天上午想带孩子去自然博物馆，孩子5岁，然后找个能吃低卡餐的地方。"],
    ["我叫小张，周末下午和朋友出去玩，4个人，想玩密室逃脱再吃火锅。"],
    ["晚上6点出去玩，3个小时，和朋友一起。"],
    ["明天下午想去密室逃脱，4个朋友，然后一起吃烤肉。"],
]

# 全局 agent 实例（跨按钮调用保持状态）
_agent_instance = None


def get_agent() -> ActivityPlannerAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ActivityPlannerAgent()
    return _agent_instance


def reset_agent():
    global _agent_instance
    _agent_instance = ActivityPlannerAgent()
    return (
        "",
        gr.update(visible=False),                            # act_section
        gr.update(value=None, choices=[], visible=False),    # act_choice
        gr.update(visible=False),                            # confirm_act_btn
        gr.update(visible=False),                            # premeal_section
        gr.update(value=[], choices=[], visible=False),      # premeal_choice
        gr.update(visible=False),                            # confirm_premeal_btn
        gr.update(visible=False),                            # meal_section
        gr.update(value=[], choices=[], visible=False),      # meal_choice
        gr.update(visible=False),                            # confirm_meal_btn
        gr.update(visible=False),                            # rest_section
        gr.update(value=None, choices=[], visible=False),    # rest_choice
        gr.update(visible=False),                            # confirm_rest_btn
        gr.update(visible=False),                            # postmeal_section
        gr.update(value=[], choices=[], visible=False),      # postmeal_choice
        gr.update(visible=False),                            # confirm_postmeal_btn
        gr.update(visible=False),                            # plan_section
        gr.update(value=None, choices=[], visible=False),    # plan_choice
        gr.update(visible=False),                            # confirm_plan_btn
    )


def get_config_status() -> str:
    try:
        cfg = load_config()
        llm_cfg = cfg.get("llm", {})
        api_key = llm_cfg.get("api_key", "")
        model = llm_cfg.get("model", "")
        base_url = llm_cfg.get("base_url", "")
        if not api_key or api_key.startswith("sk-your"):
            return (
                f"**LLM 未配置**（规则模式运行）\n"
                f"如需启用智能解析，请编辑 `config.yaml` 填入你的 API Key。"
            )
        masked_key = api_key[:8] + "****" + api_key[-4:] if len(api_key) > 12 else "****"
        return (
            f"**LLM 已配置**\n"
            f"  - 模型：`{model}`\n"
            f"  - 接口：`{base_url}`\n"
            f"  - API Key：`{masked_key}`"
        )
    except Exception as e:
        return f"config.yaml 读取失败：{e}"


# ==================================================================
# 主流程：一个按钮全自动
# ==================================================================
def run_plan_auto(user_input: str):
    """
    自动执行全部规划流程，只在需要用户确认时暂停。
    
    新流程（共9步）：
    1. 解析意图 + 用户信息
    2. 搜索活动方案
    3. 搜索餐厅 → 暂停让用户选择
    4. 匹配餐厅座位
    5. 餐前空隙检查 → 暂停让用户选择餐前活动
    6. 用餐时间确认 → 如果不在常规窗口，暂停
    7. 告知结束时间 + 餐后空隙检查 → 暂停让用户选择餐后活动
    8. 方案对比 → 如果多个方案，暂停让用户选
    9. 预订 + 生成计划
    """
    if not user_input.strip():
        yield (
            "请输入你的出行需求！",
            *_hide_all_ui()
        )
        return

    agent = get_agent()
    output = ""

    # ========== Step 1/9: 解析意图 + 用户信息 ==========
    output += "== Step 1/9: 解析出行需求 ==\n\n"
    yield output, *_hide_all_ui()

    result = agent.stage_parse(user_input)
    output += result["summary"] + "\n"
    yield output, *_hide_all_ui()

    # ========== Step 2/9: 搜索活动 ==========
    output += "\n== Step 2/9: 搜索适合活动 ==\n\n"
    yield output, *_hide_all_ui()

    result = agent.stage_search_activities()
    output += result["summary"] + "\n"
    yield output, *_hide_all_ui()

    # 搜索不到指定活动 → 终止
    if result.get("not_found"):
        output += f"\n❌ 规划终止：{result['summary']}\n请重新输入需求。\n"
        yield output, *_hide_all_ui()
        return

    # 需要用户从候选活动中选一个
    if result.get("needs_activity_choice"):
        plans = result["plans"]
        act_labels = [
            f"{p['name']}（{p['duration_hours']}h，人均{p.get('price', 0)}元）"
            for p in plans
        ]
        agent._activity_candidates = plans
        output += "\n请选择您想参加的活动，然后点击「确认活动」继续："
        yield (
            output,
            gr.update(visible=True),                                  # act_section
            gr.update(value=None, choices=act_labels, visible=True),  # act_choice
            gr.update(visible=True),                                   # confirm_act_btn
            *_hide_all_ui()[3:]                                       # 其余隐藏
        )
        return  # 暂停，等用户选活动

    # 活动已确定（单一匹配 or 自动推荐），直接进入搜索餐厅
    for step_output in _continue_after_activity(agent, output):
        yield step_output


def _hide_meal_ui():
    """隐藏用餐确认区：meal_choice, confirm_meal_btn"""
    return gr.update(choices=[], visible=False), gr.update(visible=False)


def _hide_plan_ui():
    """隐藏方案选择区：plan_section, plan_choice, confirm_plan_btn"""
    return gr.update(visible=False), gr.update(choices=[], visible=False), gr.update(visible=False)


def _hide_all_ui():
    """隐藏所有交互组件（19个UI组件的完整返回，不含output_box）"""
    return (
        gr.update(visible=False),                            # act_section
        gr.update(value=None, choices=[], visible=False),    # act_choice
        gr.update(visible=False),                            # confirm_act_btn
        gr.update(visible=False),                            # premeal_section
        gr.update(value=[], choices=[], visible=False),      # premeal_choice
        gr.update(visible=False),                            # confirm_premeal_btn
        gr.update(visible=False),                            # meal_section
        gr.update(value=[], choices=[], visible=False),      # meal_choice
        gr.update(visible=False),                            # confirm_meal_btn
        gr.update(visible=False),                            # rest_section
        gr.update(value=None, choices=[], visible=False),    # rest_choice
        gr.update(visible=False),                            # confirm_rest_btn
        gr.update(visible=False),                            # postmeal_section
        gr.update(value=[], choices=[], visible=False),      # postmeal_choice
        gr.update(visible=False),                            # confirm_postmeal_btn
        gr.update(visible=False),                            # plan_section
        gr.update(value=None, choices=[], visible=False),    # plan_choice
        gr.update(visible=False),                            # confirm_plan_btn
    )


def _collect_meal_options(all_meal_results):
    """跨方案汇总用餐选项，按 suggested_time 去重"""
    all_options = []
    seen_times = set()

    for idx, r in enumerate(all_meal_results):
        if r["needs_ask"] and r["options"]:
            for opt in r["options"]:
                time_key = opt["suggested_time"].strftime("%H:%M")
                if time_key not in seen_times:
                    seen_times.add(time_key)
                    all_options.append({
                        "plan_index": idx,
                        "meal_name": opt["meal_name"],
                        "meal_label": opt["meal_label"],
                        "suggested_time": opt["suggested_time"],
                        "display": opt["label"],
                    })

    return all_options


# ==================================================================
# 回调：用户选择活动后继续
# ==================================================================
def on_act_confirmed(selected_act, current_output):
    agent = get_agent()
    output = current_output

    candidates = getattr(agent, "_activity_candidates", [])
    chosen_act = None

    if selected_act and candidates:
        for p in candidates:
            label = f"{p['name']}（{p['duration_hours']}h，人均{p.get('price', 0)}元）"
            if label == selected_act:
                chosen_act = p
                break

    if not chosen_act and candidates:
        chosen_act = candidates[0]

    # 更新 agent 的活动列表为用户选择的那一个
    if chosen_act:
        agent.activities = [chosen_act]
        output += f"\n  ✓ 已选择活动：{chosen_act['name']}\n"
    else:
        output += "\n  ✓ 活动已确认\n"

    for step_output in _continue_after_activity(agent, output):
        yield step_output


def _continue_after_activity(agent, output):
    """活动选择完成后，直接进入搜索餐厅（新流程：先搜餐厅，再做餐前检查）。"""

    # ========== Step 3/9: 搜索餐厅 ==========
    output += "\n== Step 3/9: 搜索餐厅 ==\n\n"
    yield output, *_hide_all_ui()

    rest_result = agent.stage_search_restaurants()
    output += rest_result["summary"] + "\n"
    yield output, *_hide_all_ui()

    # 搜索不到指定餐厅 → 终止
    if rest_result.get("not_found"):
        output += f"\n❌ 规划终止：{rest_result['summary']}\n请重新输入需求。\n"
        yield output, *_hide_all_ui()
        return

    # 只有1家（固定）或自动选定 → 跳过选餐厅
    if rest_result.get("has_fixed_restaurant"):
        chosen_rest = agent.restaurants[0]
        agent._chosen_restaurant = chosen_rest
        output += f"\n  [固定] 已确定餐厅：{chosen_rest['name']}，跳过选择\n"
        for step_output in _continue_after_restaurant(agent, output, chosen_rest):
            yield step_output
        return

    # 展示餐厅列表，让用户选择
    restaurants = agent.restaurants
    rest_choice_labels = [
        f"{r['name']}（{r['cuisine']}，人均{r['price_per_person']}元）"
        for r in restaurants
    ]
    agent._restaurants_cached = restaurants

    output += "\n请选择您想去的餐厅，然后点击「确认餐厅」继续："
    yield (
        output,
        gr.update(visible=False),                                # act_section
        gr.update(value=None, choices=[], visible=False),        # act_choice
        gr.update(visible=False),                                # confirm_act_btn
        gr.update(visible=False),                                # premeal_section
        gr.update(value=[], choices=[], visible=False),          # premeal_choice
        gr.update(visible=False),                                # confirm_premeal_btn
        gr.update(visible=False),                                # meal_section
        gr.update(value=[], choices=[], visible=False),          # meal_choice
        gr.update(visible=False),                                # confirm_meal_btn
        gr.update(visible=True),                                 # rest_section
        gr.update(choices=rest_choice_labels, visible=True),     # rest_choice
        gr.update(visible=True),                                 # confirm_rest_btn
        gr.update(visible=False),                                # postmeal_section
        gr.update(value=[], choices=[], visible=False),          # postmeal_choice
        gr.update(visible=False),                                # confirm_postmeal_btn
        gr.update(visible=False),                                # plan_section
        gr.update(value=None, choices=[], visible=False),        # plan_choice
        gr.update(visible=False),                                # confirm_plan_btn
    )
    return  # 暂停，等用户选餐厅


# ==================================================================
# 回调：用户确认用餐时间后继续
# ==================================================================
def on_meal_confirmed(selected_choices, current_output):
    agent = get_agent()

    # 直接使用 run_plan_auto 缓存的选项（不重新计算，避免选项列表不一致）
    all_options = getattr(agent, "_meal_options_cached", [])

    # 应用用户选择
    user_meal_choices = {}
    if selected_choices:
        for choice in selected_choices:
            for opt in all_options:
                if opt["display"] == choice:
                    user_meal_choices[opt["plan_index"]] = opt
                    break

    agent._user_meal_choices = user_meal_choices

    output = current_output
    output += "\n  ✓ 用餐时间已确认\n"

    # 从 agent 缓存中获取 plan_configs（在 Step 4 匹配座位时已保存）
    plan_configs = getattr(agent, "_plan_configs_before_premeal", [])

    for step_output in _continue_after_meal(agent, output, plan_configs):
        yield step_output


# ==================================================================
# 回调：用户选择餐厅后继续
# ==================================================================
def on_rest_confirmed(selected_rest, current_output):
    agent = get_agent()

    # 从缓存中找到用户选的餐厅
    restaurants = getattr(agent, "_restaurants_cached", [])
    chosen_rest = None
    if selected_rest and restaurants:
        for r in restaurants:
            label = f"{r['name']}（{r['cuisine']}，人均{r['price_per_person']}元）"
            if label == selected_rest:
                chosen_rest = r
                break

    output = current_output
    if chosen_rest:
        output += f"\n  ✓ 已选择餐厅：{chosen_rest['name']}\n"
    else:
        chosen_rest = restaurants[0] if restaurants else None
        output += f"\n  ✓ 默认选择第一家餐厅：{chosen_rest['name']}\n" if chosen_rest else ""

    agent._chosen_restaurant = chosen_rest

    for step_output in _continue_after_restaurant(agent, output, chosen_rest):
        yield step_output


# ==================================================================
# 共享逻辑：餐厅确认后 → 匹配座位 → 追加活动 → 方案对比
# ==================================================================
def _continue_after_restaurant(agent, output, chosen_rest):
    """用户选定餐厅后，匹配座位 → 检查餐前空隙 → 让用户选择餐前活动。"""

    # ========== Step 4/9: 匹配餐厅座位 ==========
    output += "\n== Step 4/9: 匹配餐厅座位 ==\n\n"
    yield output, *_hide_all_ui()

    plan_configs = []
    for i in range(len(agent.activities)):
        act = agent.activities[i]
        meal = agent.meal_calc.calculate_meal_arrangement(
            agent.start_time + timedelta(hours=act["duration_hours"])
        )

        meal_results = getattr(agent, "_meal_results", [])
        route_to_act = {}
        activity_actual_start = agent.start_time
        if i < len(meal_results):
            route_to_act = meal_results[i].get("route_to_activity", {})
            activity_actual_start = meal_results[i].get("activity_actual_start", agent.start_time)

        if meal["in_meal_slot"] or not meal["needs_ask"]:
            meal_time = meal["meal_time"]
            meal_label = (
                (meal["meal_slot"].get("meal_label") or meal["meal_slot"].get("label", "用餐"))
                if meal["meal_slot"] else "用餐"
            )
        elif meal["options"]:
            meal_time = meal["options"][0]["suggested_time"]
            meal_label = meal["options"][0]["meal_label"]
        else:
            slot = agent.meal_calc.get_next_meal_slot(
                agent.start_time + timedelta(hours=act["duration_hours"])
            )
            meal_time = datetime.combine(
                (agent.start_time + timedelta(hours=act["duration_hours"])).date(),
                __import__("datetime").time(hour=int(slot["start_hour"]), minute=int((slot["start_hour"] % 1) * 60))
            )
            meal_label = slot["label"]

        match_result = agent.stage_match_restaurant(meal_time, restaurant=chosen_rest, activity=act)
        output += f"\n--- 方案{i+1} ---\n"
        output += match_result["summary"] + "\n"

        plan_configs.append({
            "activity": act,
            "meal_time": meal_time,
            "meal_label": meal_label,
            "restaurant": match_result["restaurant"],
            "route_to_activity": route_to_act,
            "route_to_restaurant": match_result.get("route_to_restaurant", {}),
            "adjusted_meal_time": match_result.get("adjusted_meal_time", meal_time),
            "activity_actual_start": activity_actual_start,
        })

    yield output, *_hide_all_ui()

    # ========== Step 5/9: 餐前空隙检查 ==========
    output += "\n== Step 5/9: 检查餐前空隙 ==\n\n"
    yield output, *_hide_all_ui()

    pre_meal_has_candidates = False
    has_fixed_activity = agent.specified_activity and len(agent.activities) >= 1

    if has_fixed_activity:
        output += "--- 餐前空隙检查 ---\n"

        for i, cfg in enumerate(plan_configs):
            act = cfg["activity"]
            meal_time = cfg.get("adjusted_meal_time") or cfg["meal_time"]
            activity_actual_start = cfg.get("activity_actual_start", agent.start_time)
            act_end = activity_actual_start + timedelta(hours=act["duration_hours"])

            gap_minutes = (meal_time - act_end).total_seconds() / 60

            if gap_minutes >= 30:
                gap_hours = gap_minutes / 60.0
                output += (
                    f"  [提示] 方案{i+1}：{act['name']}在{act_end.strftime('%H:%M')}结束，"
                    f"{meal_time.strftime('%H:%M')}用餐，中间有{gap_minutes:.0f}分钟空闲。\n"
                )

                from data.activities import MOCK_ACTIVITIES
                used_names = {a["name"] for a in agent.activities}
                candidates = [
                    a for a in MOCK_ACTIVITIES
                    if a["name"] not in used_names
                    and a.get("scene") in (agent.scene, "all")
                ]

                # ===== 核心改动：餐前活动必须满足总时间校验 =====
                # 条件：活动A结束 + 缓冲15min + A→B路程 + B时长 + B→餐厅路程 ≤ 餐前空隙
                valid_candidates = []
                for cand in candidates:
                    route_a_to_b = agent.tools["route_time"].run(
                        from_address=act.get("address", ""),
                        to_address=cand.get("address", ""),
                    )
                    route_b_to_rest = agent.tools["route_time"].run(
                        from_address=cand.get("address", ""),
                        to_address=cfg["restaurant"].get("address", ""),
                    )
                    total_needed = 15 + route_a_to_b["duration_minutes"] + cand["duration_hours"] * 60 + route_b_to_rest["duration_minutes"]
                    if total_needed <= gap_minutes:
                        valid_candidates.append({
                            "activity": cand,
                            "route_to_premeal": route_a_to_b,
                            "route_premeal_to_rest": route_b_to_rest,
                            "total_minutes": total_needed,
                        })
                    # 接近但超出不超过30分钟的也保留，标记为 △
                    elif (total_needed - gap_minutes) <= 30:
                        valid_candidates.append({
                            "activity": cand,
                            "route_to_premeal": route_a_to_b,
                            "route_premeal_to_rest": route_b_to_rest,
                            "total_minutes": total_needed,
                            "over_minutes": total_needed - gap_minutes,
                        })

                valid_candidates.sort(key=lambda x: x["total_minutes"])

                if valid_candidates:
                    pre_meal_has_candidates = True
                    output += f"  以下活动可填入空闲时段（已扣除转场时间）：\n"
                    top_fill = valid_candidates[:5]
                    cfg["pre_meal_fill_candidates"] = top_fill
                    for item in top_fill:
                        a = item["activity"]
                        over = item.get("over_minutes", 0)
                        if over > 0:
                            output += f"    △ {a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟，超出{over:.0f}分钟）—— {a.get('description', '')}\n"
                        else:
                            output += f"    ✓ {a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟）—— {a.get('description', '')}\n"
                else:
                    output += f"  暂无能在{gap_hours:.1f}h以内完成（含转场时间）的活动推荐。\n"
            else:
                output += f"  [OK] 方案{i+1}：活动结束到用餐间隔{gap_minutes:.0f}分钟，时间紧凑，无需追加。\n"

        if not pre_meal_has_candidates and not any(cfg.get("pre_meal_fill_candidates") for cfg in plan_configs):
            output += "  [OK] 所有方案活动结束后与用餐时间衔接紧密，无需追加活动。\n"

        output += "\n"

    yield output, *_hide_all_ui()

    # ========== Step 5.5: 餐前活动选择 ==========
    if pre_meal_has_candidates:
        agent._plan_configs_before_premeal = plan_configs
        all_premeal_options = []
        seen_premeal = set()
        for cfg in plan_configs:
            for item in cfg.get("pre_meal_fill_candidates", []):
                name = item["activity"]["name"]
                if name not in seen_premeal:
                    seen_premeal.add(name)
                    all_premeal_options.append(item)

        agent._premeal_candidates = all_premeal_options

        premeal_labels = []
        for item in all_premeal_options:
            a = item["activity"]
            over = item.get("over_minutes", 0)
            if over > 0:
                premeal_labels.append(f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟，超出{over:.0f}分钟）—— {a.get('description', '')}")
            else:
                premeal_labels.append(f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟）—— {a.get('description', '')}")

        output += "请选择是否添加餐前活动（可多选，不勾选则不添加），然后点击「确认餐前安排」继续："
        yield (
            output,
            gr.update(visible=False),                                # act_section
            gr.update(value=None, choices=[], visible=False),        # act_choice
            gr.update(visible=False),                                # confirm_act_btn
            gr.update(visible=True),                                 # premeal_section
            gr.update(value=[], choices=premeal_labels, visible=True), # premeal_choice
            gr.update(visible=True),                                 # confirm_premeal_btn
            gr.update(visible=False),                                # meal_section
            gr.update(value=[], choices=[], visible=False),          # meal_choice
            gr.update(visible=False),                                # confirm_meal_btn
            gr.update(visible=False),                                # rest_section
            gr.update(value=None, choices=[], visible=False),        # rest_choice
            gr.update(visible=False),                                # confirm_rest_btn
            gr.update(visible=False),                                # postmeal_section
            gr.update(value=[], choices=[], visible=False),          # postmeal_choice
            gr.update(visible=False),                                # confirm_postmeal_btn
            gr.update(visible=False),                                # plan_section
            gr.update(value=None, choices=[], visible=False),        # plan_choice
            gr.update(visible=False),                                # confirm_plan_btn
        )
        return  # 暂停，等用户确认餐前安排

    # 无餐前活动可选，保存 plan_configs 并直接进入用餐时间确认
    agent._plan_configs_before_premeal = plan_configs
    for step_output in _continue_after_premeal(agent, output, plan_configs):
        yield step_output


# ==================================================================
# 共享逻辑：餐前活动确认后 → 用餐时间确认 → 餐后活动 → 方案对比
# ==================================================================
def _continue_after_premeal(agent, output, plan_configs):
    """餐前活动选择完成后，进入用餐时间确认阶段。"""

    # ========== Step 6/9: 用餐时间确认 ==========
    output += "\n== Step 6/9: 用餐时间确认 ==\n\n"
    yield output, *_hide_all_ui()

    # 先为每个方案计算用餐安排（用于判断是否需要询问用户）
    all_meal_results = []
    for i in range(len(agent.activities)):
        r = agent.stage_calculate_meal(i)
        all_meal_results.append(r)
    agent._meal_results = all_meal_results

    any_needs_ask = any(r["needs_ask"] for r in all_meal_results)

    if any_needs_ask:
        all_options = _collect_meal_options(all_meal_results)
        agent._meal_options_cached = all_options

        choice_labels = [opt["display"] for opt in all_options]
        output += "请选择您偏好的用餐安排，然后点击「确认」继续："
        yield (
            output,
            gr.update(visible=False),                                # act_section
            gr.update(value=None, choices=[], visible=False),        # act_choice
            gr.update(visible=False),                                # confirm_act_btn
            gr.update(visible=False),                                # premeal_section
            gr.update(value=[], choices=[], visible=False),          # premeal_choice
            gr.update(visible=False),                                # confirm_premeal_btn
            gr.update(visible=True),                                 # meal_section
            gr.update(choices=choice_labels, visible=True),          # meal_choice
            gr.update(visible=True),                                 # confirm_meal_btn
            gr.update(visible=False),                                # rest_section
            gr.update(value=None, choices=[], visible=False),        # rest_choice
            gr.update(visible=False),                                # confirm_rest_btn
            gr.update(visible=False),                                # postmeal_section
            gr.update(value=[], choices=[], visible=False),          # postmeal_choice
            gr.update(visible=False),                                # confirm_postmeal_btn
            gr.update(visible=False),                                # plan_section
            gr.update(value=None, choices=[], visible=False),        # plan_choice
            gr.update(visible=False),                                # confirm_plan_btn
        )
        return

    agent._meal_options_cached = []
    agent._user_meal_choices = {}

    for step_output in _continue_after_meal(agent, output, plan_configs):
        yield step_output


def _continue_after_meal(agent, output, plan_configs):
    """用餐时间确认后，告知结束时间 + 检查餐后空隙。"""

    # ========== Step 7/9: 告知结束时间 + 餐后空隙检查 ==========
    output += "\n== Step 7/9: 检查餐后空隙 ==\n\n"
    yield output, *_hide_all_ui()

    # 计算当前活动总时长，判断是否需要餐后活动
    post_meal_has_candidates = False
    user_meal_choices = getattr(agent, "_user_meal_choices", {})

    # ===== 关键修复：将用户选择的用餐时间回写到 plan_config =====
    # on_meal_confirmed 把选择存到了 agent._user_meal_choices，
    # 但没有更新 plan_config 的 meal_time/adjusted_meal_time，
    # 导致等待时间计算时仍使用默认的"立即用餐"时间
    for plan_idx, chosen_opt in user_meal_choices.items():
        if plan_idx < len(plan_configs):
            new_meal_time = chosen_opt["suggested_time"]
            plan_configs[plan_idx]["meal_time"] = new_meal_time
            # 重新计算 adjusted_meal_time（用餐时间 + 路程时间）
            route_rest = plan_configs[plan_idx].get("route_to_restaurant", {})
            travel_min = route_rest.get("duration_minutes", 0)
            plan_configs[plan_idx]["adjusted_meal_time"] = new_meal_time
            plan_configs[plan_idx]["meal_label"] = chosen_opt["meal_label"]

    for i, cfg in enumerate(plan_configs):
        act = cfg["activity"]
        pre_meal_act = cfg.get("pre_meal_fill_chosen")
        meal_time = cfg.get("adjusted_meal_time") or cfg["meal_time"]
        activity_actual_start = cfg.get("activity_actual_start", agent.start_time)

        # 计算活动实际结束时间（含餐前活动）
        act_end = activity_actual_start + timedelta(hours=act["duration_hours"])
        if pre_meal_act:
            # 有餐前活动时，活动结束时间 = 餐前活动结束时间
            act_end = cfg.get("premeal_end", act_end)

        # ===== 计算等待就餐时间 =====
        # 等待开始 = 活动实际结束时间
        # 等待结束 = 用餐时间 - 到餐厅路程时间
        route_to_rest = cfg.get("route_to_restaurant", {})
        if pre_meal_act:
            route_to_rest = cfg.get("route_premeal_to_rest", {})

        travel_to_rest_min = route_to_rest.get("duration_minutes", 0)
        need_leave_time = meal_time - timedelta(minutes=travel_to_rest_min)

        # 等待时间 = 需要出发去餐厅的时间 - 活动结束时间
        wait_minutes = (need_leave_time - act_end).total_seconds() / 60

        if wait_minutes > 15:
            # 有实质性等待（>15分钟才展示）
            cfg["has_wait"] = True
            cfg["wait_start"] = act_end
            cfg["wait_end"] = need_leave_time
            cfg["wait_minutes"] = wait_minutes
            cfg["wait_label"] = f"等待就餐（{act_end.strftime('%H:%M')}~{need_leave_time.strftime('%H:%M')}，约{wait_minutes:.0f}分钟）"
            # 更新 adjusted_meal_time 表示包含等待的总用餐时间
            cfg["meal_time_with_wait"] = meal_time
        else:
            cfg["has_wait"] = False

        # 计算实际活动时长（含餐前活动）
        actual_activity_hours = act["duration_hours"]
        if pre_meal_act:
            actual_activity_hours += pre_meal_act["duration_hours"]

        # 计算出发→活动→(餐前活动→)用餐的总时长
        route_to_act = cfg.get("route_to_activity", {})
        travel_to_act = route_to_act.get("duration_minutes", 0)
        total_minutes = travel_to_act + act["duration_hours"] * 60

        if pre_meal_act:
            route_to_premeal = cfg.get("route_to_premeal", {})
            route_premeal_rest = cfg.get("route_premeal_to_rest", {})
            total_minutes += 15 + route_to_premeal.get("duration_minutes", 0)
            total_minutes += pre_meal_act["duration_hours"] * 60
            total_minutes += route_premeal_rest.get("duration_minutes", 0)
        else:
            # 无餐前活动：活动→餐厅路程
            total_minutes += travel_to_rest_min

        # 等待时间
        wait_info_str = ""
        if cfg.get("has_wait"):
            total_minutes += cfg["wait_minutes"]
            wait_info_str = f" + 等待：{cfg['wait_minutes']:.0f}min"

        # 用餐时长约60分钟
        meal_duration = 60
        total_with_meal = total_minutes + meal_duration

        # 结束时间 = 出发时间 + 总时长
        end_time = agent.start_time + timedelta(minutes=total_with_meal)
        target_end = agent.start_time + timedelta(hours=agent.duration)

        output += f"--- 方案{i+1} ---\n"
        output += f"  活动时长：{actual_activity_hours:.1f}h + 路程：{total_minutes - actual_activity_hours * 60 - (cfg.get('wait_minutes', 0)):.0f}min{wait_info_str} + 用餐：{meal_duration}min\n"
        output += f"  预计结束时间：{end_time.strftime('%H:%M')}（目标时长 {agent.duration}h，目标结束：{target_end.strftime('%H:%M')}）\n"
        if cfg.get("has_wait"):
            output += f"  [等待] {cfg['wait_label']}\n"

        remaining_minutes = (target_end - end_time).total_seconds() / 60

        if remaining_minutes >= 30:
            # 有餐后空隙，搜索适合的餐后活动
            output += f"  [提示] 活动结束后还有 {remaining_minutes:.0f} 分钟空闲，可以安排餐后活动。\n"

            from data.activities import MOCK_ACTIVITIES
            used_names = {a["name"] for a in agent.activities}
            if pre_meal_act:
                used_names.add(pre_meal_act["name"])

            remaining_hours = remaining_minutes / 60.0

            # 搜索餐后活动：需要考虑从餐厅到餐后活动的路程
            postmeal_candidates = []
            for cand in MOCK_ACTIVITIES:
                if cand["name"] in used_names:
                    continue
                if cand.get("scene") not in (agent.scene, "all"):
                    continue
                # 计算总时间：餐厅→活动路程 + 缓冲15min + 活动时长
                route_rest_to_act = agent.tools["route_time"].run(
                    from_address=cfg["restaurant"].get("address", ""),
                    to_address=cand.get("address", ""),
                )
                total_needed = route_rest_to_act["duration_minutes"] + 15 + cand["duration_hours"] * 60
                if total_needed <= remaining_minutes:
                    postmeal_candidates.append({
                        "activity": cand,
                        "route_rest_to_postmeal": route_rest_to_act,
                        "total_minutes": total_needed,
                    })
                elif (total_needed - remaining_minutes) <= 30:
                    postmeal_candidates.append({
                        "activity": cand,
                        "route_rest_to_postmeal": route_rest_to_act,
                        "total_minutes": total_needed,
                        "over_minutes": total_needed - remaining_minutes,
                    })

            postmeal_candidates.sort(key=lambda x: x["total_minutes"])

            if postmeal_candidates:
                post_meal_has_candidates = True
                output += f"  以下活动可作为餐后活动（已扣除转场时间）：\n"
                for item in postmeal_candidates[:5]:
                    a = item["activity"]
                    over = item.get("over_minutes", 0)
                    if over > 0:
                        output += f"    △ {a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟，超出{over:.0f}分钟）—— {a.get('description', '')}\n"
                    else:
                        output += f"    ✓ {a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟）—— {a.get('description', '')}\n"
                cfg["post_meal_fill_candidates"] = postmeal_candidates[:5]
            else:
                output += f"  暂无能在{remaining_hours:.1f}h内完成（含转场时间）的餐后活动推荐。\n"
        else:
            output += f"  [OK] 活动总时长已满足目标，无需追加餐后活动。\n"

        output += "\n"

    yield output, *_hide_all_ui()

    # ========== Step 7.5: 餐后活动选择 ==========
    if post_meal_has_candidates:
        agent._plan_configs_before_postmeal = plan_configs
        all_postmeal_options = []
        seen_postmeal = set()
        for cfg in plan_configs:
            for item in cfg.get("post_meal_fill_candidates", []):
                name = item["activity"]["name"]
                if name not in seen_postmeal:
                    seen_postmeal.add(name)
                    all_postmeal_options.append(item)

        agent._postmeal_candidates = all_postmeal_options

        postmeal_labels = []
        for item in all_postmeal_options:
            a = item["activity"]
            over = item.get("over_minutes", 0)
            if over > 0:
                postmeal_labels.append(f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟，超出{over:.0f}分钟）—— {a.get('description', '')}")
            else:
                postmeal_labels.append(f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟）—— {a.get('description', '')}")

        output += "请选择是否添加餐后活动（可多选，不勾选则不添加），然后点击「确认餐后安排」继续："
        yield (
            output,
            gr.update(visible=False),                                # act_section
            gr.update(value=None, choices=[], visible=False),        # act_choice
            gr.update(visible=False),                                # confirm_act_btn
            gr.update(visible=False),                                # premeal_section
            gr.update(value=[], choices=[], visible=False),          # premeal_choice
            gr.update(visible=False),                                # confirm_premeal_btn
            gr.update(visible=False),                                # meal_section
            gr.update(value=[], choices=[], visible=False),          # meal_choice
            gr.update(visible=False),                                # confirm_meal_btn
            gr.update(visible=False),                                # rest_section
            gr.update(value=None, choices=[], visible=False),        # rest_choice
            gr.update(visible=False),                                # confirm_rest_btn
            gr.update(visible=True),                                 # postmeal_section
            gr.update(value=[], choices=postmeal_labels, visible=True), # postmeal_choice
            gr.update(visible=True),                                 # confirm_postmeal_btn
            gr.update(visible=False),                                # plan_section
            gr.update(value=None, choices=[], visible=False),        # plan_choice
            gr.update(visible=False),                                # confirm_plan_btn
        )
        return  # 暂停，等用户确认餐后安排

    # 无餐后活动可选，直接进入方案对比
    for step_output in _continue_to_plan_comparison(agent, output, plan_configs):
        yield step_output


# ==================================================================
# 回调：用户确认餐前安排后继续 → 用餐时间确认
# ==================================================================
def on_premeal_confirmed(selected_choices, current_output):
    agent = get_agent()
    output = current_output

    candidates = getattr(agent, "_premeal_candidates", [])
    chosen_premeal = None

    # 用户可能勾选了多个，取第一个（因为空闲时段只够一个）
    if selected_choices and candidates:
        for item in candidates:
            a = item["activity"]
            over = item.get("over_minutes", 0)
            if over > 0:
                label = f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟，超出{over:.0f}分钟）—— {a.get('description', '')}"
            else:
                label = f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟）—— {a.get('description', '')}"
            if label in selected_choices:
                chosen_premeal = item
                break

    if chosen_premeal:
        act_name = chosen_premeal["activity"]["name"]
        output += f"\n  ✓ 已选择餐前活动：{act_name}（{chosen_premeal['activity']['duration_hours']}h）\n"
    else:
        output += "\n  ✓ 不添加餐前活动\n"

    agent._chosen_premeal_activity = chosen_premeal

    plan_configs = getattr(agent, "_plan_configs_before_premeal", [])

    # 更新 plan_configs：如果用户选了餐前活动，重新计算时间和路程
    for cfg in plan_configs:
        cfg["pre_meal_fill_chosen"] = chosen_premeal["activity"] if chosen_premeal else None
        if chosen_premeal:
            act = cfg["activity"]
            restaurant = cfg.get("restaurant", {})
            activity_actual_start = cfg.get("activity_actual_start", agent.start_time)
            act_end = activity_actual_start + timedelta(hours=act["duration_hours"])

            # 使用之前已计算好的路程数据（在餐前空隙检查时已经算过）
            route_to_premeal = chosen_premeal["route_to_premeal"]
            route_premeal_to_rest = chosen_premeal["route_premeal_to_rest"]
            premeal_travel = route_to_premeal["duration_minutes"]
            premeal_to_rest_travel = route_premeal_to_rest["duration_minutes"]

            premeal_start = act_end + timedelta(minutes=15 + premeal_travel)
            premeal_end = premeal_start + timedelta(hours=chosen_premeal["activity"]["duration_hours"])
            adjusted_meal_time = premeal_end + timedelta(minutes=premeal_to_rest_travel)

            output += (
                f"\n  {route_to_premeal['transport_icon']} {act['name']}→{act_name}，"
                f"{route_to_premeal['transport']}约{premeal_travel}分钟\n"
                f"  {act_name}：{premeal_start.strftime('%H:%M')}~{premeal_end.strftime('%H:%M')}\n"
                f"  {route_premeal_to_rest['transport_icon']} {act_name}→{restaurant['name']}，"
                f"{route_premeal_to_rest['transport']}约{premeal_to_rest_travel}分钟\n"
                f"  预计用餐时间调整到：{adjusted_meal_time.strftime('%H:%M')}\n"
            )

            cfg["route_to_premeal"] = route_to_premeal
            cfg["route_premeal_to_rest"] = route_premeal_to_rest
            cfg["premeal_start"] = premeal_start
            cfg["premeal_end"] = premeal_end
            cfg["adjusted_meal_time"] = adjusted_meal_time

    for step_output in _continue_after_premeal(agent, output, plan_configs):
        yield step_output


# ==================================================================
# 回调：用户确认餐后安排后继续
# ==================================================================
def on_postmeal_confirmed(selected_choices, current_output):
    agent = get_agent()
    output = current_output

    candidates = getattr(agent, "_postmeal_candidates", [])
    chosen_postmeal = None

    if selected_choices and candidates:
        for item in candidates:
            a = item["activity"]
            over = item.get("over_minutes", 0)
            if over > 0:
                label = f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟，超出{over:.0f}分钟）—— {a.get('description', '')}"
            else:
                label = f"{a['name']}（{a['duration_hours']}h，含转场共需{item['total_minutes']:.0f}分钟）—— {a.get('description', '')}"
            if label in selected_choices:
                chosen_postmeal = item
                break

    if chosen_postmeal:
        act_name = chosen_postmeal["activity"]["name"]
        output += f"\n  ✓ 已选择餐后活动：{act_name}（{chosen_postmeal['activity']['duration_hours']}h）\n"
    else:
        output += "\n  ✓ 不添加餐后活动\n"

    agent._chosen_postmeal_activity = chosen_postmeal

    plan_configs = getattr(agent, "_plan_configs_before_postmeal", [])

    # 更新 plan_configs
    for cfg in plan_configs:
        cfg["post_meal_fill_chosen"] = chosen_postmeal["activity"] if chosen_postmeal else None
        if chosen_postmeal:
            cfg["route_rest_to_postmeal"] = chosen_postmeal["route_rest_to_postmeal"]
            # 计算餐后活动时间
            meal_time = cfg.get("adjusted_meal_time") or cfg["meal_time"]
            meal_duration = 60  # 用餐约60分钟
            postmeal_start = meal_time + timedelta(minutes=meal_duration + chosen_postmeal["route_rest_to_postmeal"]["duration_minutes"])
            postmeal_end = postmeal_start + timedelta(hours=chosen_postmeal["activity"]["duration_hours"])
            cfg["postmeal_start"] = postmeal_start
            cfg["postmeal_end"] = postmeal_end

            output += (
                f"\n  {chosen_postmeal['route_rest_to_postmeal']['transport_icon']} 用餐地点→{act_name}，"
                f"{chosen_postmeal['route_rest_to_postmeal']['transport']}约{chosen_postmeal['route_rest_to_postmeal']['duration_minutes']}分钟\n"
                f"  {act_name}：{postmeal_start.strftime('%H:%M')}~{postmeal_end.strftime('%H:%M')}\n"
                f"  预计最终结束时间：{postmeal_end.strftime('%H:%M')}\n"
            )

    for step_output in _continue_to_plan_comparison(agent, output, plan_configs):
        yield step_output


# ==================================================================
# 共享逻辑：餐后活动确认后 → 方案对比
# ==================================================================
def _continue_to_plan_comparison(agent, output, plan_configs):
    """餐前/餐后活动选择完成后，继续执行方案对比流程。"""

    # ========== Step 8/9: 方案对比 ==========
    output += "\n== Step 8/9: 方案对比 ==\n\n"
    yield output, *_hide_all_ui()

    comparison_result = agent.stage_build_plan_comparison(plan_configs)
    output += comparison_result["summary"] + "\n"
    plan_labels = [c["label"] for c in comparison_result["comparison"]]

    # 存 plan_configs 到 agent 供回调使用
    agent._plan_configs = plan_configs
    agent._comparison = comparison_result["comparison"]

    has_fixed_activity = agent.specified_activity and len(agent.activities) >= 1
    has_fixed_restaurant = agent.specified_restaurant and getattr(agent, "_chosen_restaurant", None)

    # 如果用户同时指定了活动和餐厅，直接使用第一个方案（固定活动），跳过选择
    _skip_plan_choice = (
        has_fixed_activity
        and has_fixed_restaurant
        and len(plan_labels) >= 1
    )

    if _skip_plan_choice:
        output += "\n[自动确认] 您已指定活动和餐厅，自动选择方案1...\n"
        yield output, *_hide_all_ui()

        plan_config = _build_plan_config(agent, plan_configs, comparison_result["comparison"], 0)
        for step_output in _do_book_and_generate(agent, output, plan_config):
            yield step_output
    elif len(plan_labels) <= 1:
        # 只有1个方案，直接预订
        output += "\n仅有一个方案，自动确认并预订...\n"
        yield output, *_hide_all_ui()

        plan_config = _build_plan_config(agent, plan_configs, comparison_result["comparison"], 0)
        for step_output in _do_book_and_generate(agent, output, plan_config):
            yield step_output
    else:
        # 多个方案，让用户选
        output += "\n请选择一个方案，然后点击「确认方案」继续："
        yield (
            output,
            gr.update(visible=False),                                # act_section
            gr.update(value=None, choices=[], visible=False),        # act_choice
            gr.update(visible=False),                                # confirm_act_btn
            gr.update(visible=False),                                # premeal_section
            gr.update(value=[], choices=[], visible=False),          # premeal_choice
            gr.update(visible=False),                                # confirm_premeal_btn
            gr.update(visible=False),                                # meal_section
            gr.update(value=[], choices=[], visible=False),          # meal_choice
            gr.update(visible=False),                                # confirm_meal_btn
            gr.update(visible=False),                                # rest_section
            gr.update(value=None, choices=[], visible=False),        # rest_choice
            gr.update(visible=False),                                # confirm_rest_btn
            gr.update(visible=False),                                # postmeal_section
            gr.update(value=[], choices=[], visible=False),          # postmeal_choice
            gr.update(visible=False),                                # confirm_postmeal_btn
            gr.update(visible=True),                                 # plan_section
            gr.update(value=None, choices=plan_labels, visible=True), # plan_choice
            gr.update(visible=True),                                 # confirm_plan_btn
        )


# ==================================================================
# 回调：用户选择方案后预订
# ==================================================================
def on_plan_confirmed(selected_plan, current_output):
    agent = get_agent()
    output = current_output

    plan_configs = getattr(agent, "_plan_configs", [])
    comparison = getattr(agent, "_comparison", [])

    # 找到用户选的方案索引
    idx = 0
    for i, c in enumerate(comparison):
        if c["label"] == selected_plan:
            idx = i
            break

    output += f"\n  ✓ 已选择方案{idx + 1}\n"

    plan_config = _build_plan_config(agent, plan_configs, comparison, idx)
    for step_output in _do_book_and_generate(agent, output, plan_config):
        yield step_output


# ==================================================================
# 辅助函数
# ==================================================================
def _build_plan_config(agent, plan_configs, comparison, idx):
    """从 plan_configs 和 comparison 构建完整的 plan_config"""
    raw = plan_configs[idx] if idx < len(plan_configs) else plan_configs[0]
    comp = comparison[idx] if idx < len(comparison) else comparison[0]

    fill_activity = None
    fill_check = raw.get("fill_check", {})
    if fill_check.get("needs_fill") and fill_check.get("fill_activities"):
        fill_activity = fill_check["fill_activities"][0]

    # 如果有补充活动（活动时长不足），计算活动间的路程
    route_to_fill = None
    if fill_activity:
        route_to_fill = agent.tools["route_time"].run(
            from_address=raw["activity"].get("address", ""),
            to_address=fill_activity.get("address", ""),
        )

    # 餐前活动（用户在餐前空隙中选择的）
    pre_meal_activity = raw.get("pre_meal_fill_chosen")
    route_to_premeal = raw.get("route_to_premeal")
    route_premeal_to_rest = raw.get("route_premeal_to_rest")

    # 餐后活动（用户在用餐后空隙中选择的）
    post_meal_activity = raw.get("post_meal_fill_chosen")
    route_rest_to_postmeal = raw.get("route_rest_to_postmeal")

    return {
        "activity": raw["activity"],
        "meal_time": raw["meal_time"],
        "adjusted_meal_time": raw.get("adjusted_meal_time"),
        "meal_label": raw["meal_label"],
        "restaurant": raw["restaurant"],
        "fill_activity": fill_activity,
        "pre_meal_activity": pre_meal_activity,
        "post_meal_activity": post_meal_activity,
        "route_to_activity": raw.get("route_to_activity", {}),
        "route_to_restaurant": raw.get("route_to_restaurant", {}),
        "route_to_fill": route_to_fill,
        "route_to_premeal": route_to_premeal,
        "route_premeal_to_rest": route_premeal_to_rest,
        "route_rest_to_postmeal": route_rest_to_postmeal,
        "activity_actual_start": raw.get("activity_actual_start"),
        "premeal_start": raw.get("premeal_start"),
        "premeal_end": raw.get("premeal_end"),
        "postmeal_start": raw.get("postmeal_start"),
        "postmeal_end": raw.get("postmeal_end"),
        "has_wait": raw.get("has_wait", False),
        "wait_start": raw.get("wait_start"),
        "wait_end": raw.get("wait_end"),
        "wait_minutes": raw.get("wait_minutes", 0),
        "wait_label": raw.get("wait_label", ""),
    }


def _do_book_and_generate(agent, output, plan_config):
    """执行预订 + 生成最终计划（流式输出）"""

    output += "\n== Step 9/9: 执行预订 & 生成出行计划 ==\n\n"
    yield output, *_hide_all_ui()

    # 预订
    book_result = agent.stage_book(plan_config)
    output += book_result["summary"] + "\n"
    yield output, *_hide_all_ui()

    # 流式生成计划
    for plan_chunk in agent.stage_generate_plan(plan_config):
        yield output + "\n" + plan_chunk, *_hide_all_ui()


# ==================================================================
# 构建 UI
# ==================================================================
with gr.Blocks(
    title="美团智能出行规划 Agent",
    theme=gr.themes.Soft(
        primary_hue="orange",
        secondary_hue="yellow",
    ),
    css="""
    .output-box textarea { font-family: 'Segoe UI', sans-serif; line-height: 1.6; }
    .header-box { text-align: center; padding: 10px 0; }
    .confirm-row { margin-top: 12px; }
    """,
) as demo:

    # --- 标题 ---
    with gr.Row(elem_classes="header-box"):
        gr.Markdown(
            """
# 美团智能出行规划 Agent
**帮你把事情做完** · 输入一句话，自动规划活动+餐厅方案，需要确认时会暂停询问
            """
        )

    # --- 配置状态 ---
    with gr.Row():
        with gr.Column(scale=1):
            config_md = gr.Markdown(get_config_status())
            refresh_btn = gr.Button("刷新配置状态", size="sm", variant="secondary")

    gr.Markdown("---")

    # --- 主交互区 ---
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 输入你的出行需求")
            user_input = gr.Textbox(
                label="",
                placeholder="例如：今天下午想带老婆孩子出去玩几小时，孩子5岁，老婆在减肥\n或者：晚上6点出去玩，3个小时，和朋友一起",
                lines=4,
                max_lines=6,
            )

            with gr.Row():
                submit_btn = gr.Button("开始规划", variant="primary")
                clear_btn = gr.Button("清空重置", variant="secondary")

            gr.Markdown("#### 示例需求（点击填入）")
            example_selector = gr.Examples(
                examples=EXAMPLES,
                inputs=user_input,
                label="",
            )

        with gr.Column(scale=2):
            gr.Markdown("### 执行过程 & 结果")
            output_box = gr.Textbox(
                label="",
                lines=35,
                max_lines=80,
                interactive=False,
                elem_classes="output-box",
                placeholder="输入需求后点击「开始规划」，系统将自动执行所有步骤...",
            )

    # --- 用餐时间确认区（默认隐藏） ---
    gr.Markdown("---")

    # --- 活动选择区（默认隐藏，用户指定活动且搜到多个时出现） ---
    act_section = gr.Markdown("### 活动选择", visible=False)
    with gr.Row():
        act_choice = gr.Radio(
            choices=[],
            label="请选择您想参加的活动",
            visible=False,
        )
    with gr.Row():
        confirm_act_btn = gr.Button("确认活动", variant="primary", visible=False)

    # --- 用餐时间确认区（默认隐藏） ---
    meal_section = gr.Markdown("### 用餐时间确认", visible=False)
    with gr.Row():
        meal_choice = gr.CheckboxGroup(
            choices=[],
            label="请选择您偏好的用餐时间",
            visible=False,
        )
    with gr.Row():
        confirm_meal_btn = gr.Button("确认用餐时间", variant="primary", visible=False)

    # --- 餐厅选择区（默认隐藏） ---
    rest_section = gr.Markdown("### 餐厅选择", visible=False)
    with gr.Row():
        rest_choice = gr.Radio(
            choices=[],
            label="请选择您想去的餐厅",
            visible=False,
        )
    with gr.Row():
        confirm_rest_btn = gr.Button("确认餐厅", variant="primary", visible=False)

    # --- 餐前活动确认区（默认隐藏，餐前有空隙时出现） ---
    premeal_section = gr.Markdown("### 餐前活动选择", visible=False)
    with gr.Row():
        premeal_choice = gr.CheckboxGroup(
            choices=[],
            label="是否添加餐前活动？（不勾选则不添加）",
            visible=False,
        )
    with gr.Row():
        confirm_premeal_btn = gr.Button("确认餐前安排", variant="primary", visible=False)

    # --- 餐后活动确认区（默认隐藏，餐后有空隙时出现） ---
    postmeal_section = gr.Markdown("### 餐后活动选择", visible=False)
    with gr.Row():
        postmeal_choice = gr.CheckboxGroup(
            choices=[],
            label="是否添加餐后活动？（不勾选则不添加）",
            visible=False,
        )
    with gr.Row():
        confirm_postmeal_btn = gr.Button("确认餐后安排", variant="primary", visible=False)

    # --- 方案选择区（默认隐藏） ---
    plan_section = gr.Markdown("### 方案选择", visible=False)
    with gr.Row():
        plan_choice = gr.Radio(
            choices=[],
            label="请选择一个方案",
            visible=False,
        )
    with gr.Row():
        confirm_plan_btn = gr.Button("确认方案并预订", variant="primary", visible=False)

    # --- 说明 ---
    gr.Markdown(
        """
---
### 使用说明
1. 输入出行需求 → 点击「开始规划」
2. 系统自动生成活动方案，搜索餐厅
3. 搜索到多家餐厅后 → 暂停，选择餐厅后点「确认餐厅」
4. 如果活动结束到用餐之间有空闲 → 暂停，勾选餐前活动后点「确认餐前安排」（不勾选则不添加）
5. 如果用餐时间不在常规时间段 → 暂停，选择用餐时间后点「确认」
6. 如果活动结束后仍有空闲 → 暂停，勾选餐后活动后点「确认餐后安排」（不勾选则不添加）
7. 如果有多个方案 → 暂停，选择方案后点「确认方案并预订」
8. 其余步骤全部自动完成

### 核心规则
- **活动时长不含用餐**：用户说的"5小时"指纯活动时长
- **用餐时间窗口**：早餐 7:00-8:00 / 午餐 11:30-12:30 / 晚餐 17:30-18:30
- **用餐冲突处理**：活动结束时不在用餐窗口 → 弹出选项让用户选择
- **餐厅选择**：找到多家餐厅后由用户选择，所有方案统一使用该餐厅
- **餐前活动**：活动结束后到用餐之间有空闲时，可选是否添加餐前活动（已扣除转场时间）
- **餐后活动**：用餐结束后仍有空闲时，可选是否添加餐后活动（已扣除转场时间）

> 当前为 **Mock 模式**，所有预订均为模拟数据，不会产生真实订单。
        """
    )

    # --- 事件绑定 ---
    # 19个UI输出组件（含 output_box）顺序：
    # output_box, act_section, act_choice, confirm_act_btn,
    # premeal_section, premeal_choice, confirm_premeal_btn,
    # meal_section, meal_choice, confirm_meal_btn,
    # rest_section, rest_choice, confirm_rest_btn,
    # postmeal_section, postmeal_choice, confirm_postmeal_btn,
    # plan_section, plan_choice, confirm_plan_btn
    _all_outputs = [
        output_box,
        act_section, act_choice, confirm_act_btn,
        premeal_section, premeal_choice, confirm_premeal_btn,
        meal_section, meal_choice, confirm_meal_btn,
        rest_section, rest_choice, confirm_rest_btn,
        postmeal_section, postmeal_choice, confirm_postmeal_btn,
        plan_section, plan_choice, confirm_plan_btn,
    ]

    submit_btn.click(
        fn=run_plan_auto,
        inputs=user_input,
        outputs=_all_outputs,
        show_progress=False,
    )

    confirm_act_btn.click(
        fn=on_act_confirmed,
        inputs=[act_choice, output_box],
        outputs=_all_outputs,
        show_progress=False,
    )

    confirm_meal_btn.click(
        fn=on_meal_confirmed,
        inputs=[meal_choice, output_box],
        outputs=_all_outputs,
        show_progress=False,
    )

    confirm_rest_btn.click(
        fn=on_rest_confirmed,
        inputs=[rest_choice, output_box],
        outputs=_all_outputs,
        show_progress=False,
    )

    confirm_premeal_btn.click(
        fn=on_premeal_confirmed,
        inputs=[premeal_choice, output_box],
        outputs=_all_outputs,
        show_progress=False,
    )

    confirm_postmeal_btn.click(
        fn=on_postmeal_confirmed,
        inputs=[postmeal_choice, output_box],
        outputs=_all_outputs,
        show_progress=False,
    )

    confirm_plan_btn.click(
        fn=on_plan_confirmed,
        inputs=[plan_choice, output_box],
        outputs=_all_outputs,
        show_progress=False,
    )

    clear_btn.click(
        fn=reset_agent,
        outputs=_all_outputs,
    )

    refresh_btn.click(
        fn=get_config_status,
        outputs=config_md,
    )


# ---------- 启动入口 ----------
if __name__ == "__main__":
    cfg = load_config()
    app_cfg = cfg.get("app", {})
    port = app_cfg.get("port", 7860)
    share = app_cfg.get("share", False)

    print(f"启动美团智能出行规划 Agent Web UI")
    print(f"  访问地址: http://localhost:{port}")
    print(f"  配置文件: config.yaml")

    demo.queue()
    demo.launch(
        server_port=port,
        share=share,
        inbrowser=True,
    )
