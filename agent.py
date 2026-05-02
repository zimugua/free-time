"""
活动规划 Agent 核心逻辑
流程：获取用户信息 → 解析出行需求 → 搜索活动 → 用餐时间判断 → 搜索餐厅 →
      匹配座位 → 用餐时间确认 → 追加活动（如需）→ 用户确认方案 → 预订 → 生成计划

Agent 拆分为多阶段方法，每阶段返回中间结果，由 app.py 控制交互流程。
"""
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple, Optional, Generator

from tools import (
    SearchActivitiesTool,
    SearchRestaurantsTool,
    CheckReservationTool,
    BookActivityTool,
    BookRestaurantTool,
    GetUserInfoTool,
    RouteTimeTool,
)
from tools.meals import MealTimeCalculator
from tools.restaurants import MOCK_RESTAURANTS
from llm import get_llm_client


class ActivityPlannerAgent:
    """
    美团本地出行规划 Agent
    - 支持 LLM / 规则 双模式意图解析
    - 优先匹配用户指定活动，再生成差异化方案
    - 活动时长独立于用餐时间，用餐安排在餐段内
    - 多轮交互：用餐时间确认、方案选择
    """

    def __init__(self):
        self.tools = {
            "get_user_info": GetUserInfoTool(),
            "search_activities": SearchActivitiesTool(),
            "search_restaurants": SearchRestaurantsTool(),
            "check_reservation": CheckReservationTool(),
            "book_activity": BookActivityTool(),
            "book_restaurant": BookRestaurantTool(),
            "route_time": RouteTimeTool(),
        }
        self.meal_calc = MealTimeCalculator()
        self.llm = get_llm_client()

        # 中间状态（跨阶段共享）
        self.intent: Dict = {}
        self.user_name: str = ""
        self.user_phone: str = ""
        self.user_address: str = ""        # 用户常住地址（用于路程计算）
        self.scene: str = "family"
        self.people: int = 3
        self.low_calorie: bool = False
        self.start_time: datetime = None
        self.duration: float = 3
        self.specified_activity: str = ""
        self.activities: List[Dict] = []       # 初步搜索到的活动方案
        self.restaurants: List[Dict] = []      # 搜索到的餐厅
        self.final_plan: Dict = {}             # 最终选定的方案

    # ------------------------------------------------------------------
    # 时间解析辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_start_time(date_kw: str, hour: int) -> datetime:
        now = datetime.now()

        if date_kw == "明天":
            base = now + timedelta(days=1)
        elif date_kw == "后天":
            base = now + timedelta(days=2)
        elif date_kw in ("周六", "星期六"):
            days_until_sat = (5 - now.weekday()) % 7
            if days_until_sat == 0 and now.hour >= hour:
                days_until_sat = 7
            base = now + timedelta(days=days_until_sat)
        elif date_kw in ("周日", "星期日"):
            days_until_sun = (6 - now.weekday()) % 7
            if days_until_sun == 0 and now.hour >= hour:
                days_until_sun = 7
            base = now + timedelta(days=days_until_sun)
        else:
            base = now

        result = base.replace(hour=hour, minute=0, second=0, microsecond=0)
        if result <= now and date_kw == "今天":
            result += timedelta(days=1)
        return result

    # ------------------------------------------------------------------
    # 意图解析
    # ------------------------------------------------------------------
    def _rule_parse_intent(self, user_input: str) -> Dict:
        """规则模式意图解析"""
        text = user_input.lower()

        if "孩子" in text or "小孩" in text or "宝宝" in text or "亲子" in text:
            scene, people, low_calorie = "family", 3, True
        elif "朋友" in text or "兄弟" in text or "闺蜜" in text:
            scene, people, low_calorie = "friends", 4, False
        else:
            scene, people, low_calorie = "family", 3, True

        date_kw = "今天"
        if "明天" in text:
            date_kw = "明天"
        elif "后天" in text:
            date_kw = "后天"

        from llm import load_config
        cfg = load_config()
        app_cfg = cfg.get("app", {})

        start_hour = app_cfg.get("default_start_hour", 14)
        if "上午" in text or "早上" in text:
            start_hour = 10
        elif "中午" in text:
            start_hour = 12
        elif "下午" in text:
            start_hour = 14
        elif "晚上" in text:
            start_hour = 18

        duration = app_cfg.get("default_duration_hours", 5)

        specified_activity = ""
        for kw in ["自然博物馆", "恐龙", "博物馆", "烘焙", "亲子乐园", "密室", "脱口秀",
                    "保龄球", "剧本杀", "798", "水族馆", "海洋馆", "游乐区"]:
            if kw in text:
                specified_activity = kw
                break

        specified_restaurant = ""
        for kw in ["火锅", "烤肉", "日料", "西餐", "披萨", "海鲜", "小龙虾",
                    "川菜", "粤菜", "云南菜", "烧烤", "串串", "麻辣烫", "奶茶", "咖啡",
                    "海底捞", "必胜客", "星巴克", "肯德基", "麦当劳", "西贝"]:
            if kw in text:
                specified_restaurant = kw
                break

        user_name = ""
        import re
        m = re.search(r"(?:我叫|我是|我是说|名字是)([^\s，。,\.]{1,4})", text)
        if m:
            user_name = m.group(1)
        elif "小明" in text:
            user_name = "小明"
        elif "小张" in text:
            user_name = "小张"

        start_time = self._resolve_start_time(date_kw, start_hour)

        return {
            "scene": scene,
            "people": people,
            "low_calorie": low_calorie,
            "date_kw": date_kw,
            "start_hour": start_hour,
            "start_time": start_time,
            "duration_hours": duration,
            "specified_activity": specified_activity,
            "specified_restaurant": specified_restaurant,
            "user_name": user_name,
            "constraints": "",
        }

    def parse_intent(self, user_input: str) -> Tuple[Dict, str]:
        """解析用户意图，优先 LLM，失败则降级规则"""
        llm_result = self.llm.parse_intent(user_input)
        if llm_result and "scene" in llm_result:
            date_kw = llm_result.get("date", "今天")
            start_hour = int(llm_result.get("start_hour", 14))
            start_time = self._resolve_start_time(date_kw, start_hour)
            intent = {
                "scene": llm_result.get("scene", "family"),
                "people": int(llm_result.get("people", 3)),
                "low_calorie": bool(llm_result.get("low_calorie", False)),
                "date_kw": date_kw,
                "start_hour": start_hour,
                "start_time": start_time,
                "duration_hours": int(llm_result.get("duration_hours", 5)),
                "specified_activity": llm_result.get("specified_activity", ""),
                "specified_restaurant": llm_result.get("specified_restaurant", ""),
                "user_name": llm_result.get("user_name", ""),
                "constraints": llm_result.get("constraints", ""),
            }
            return intent, "LLM"
        else:
            return self._rule_parse_intent(user_input), "Rules"

    # ------------------------------------------------------------------
    # 阶段1：获取用户信息 + 解析意图（合并为一步）
    # ------------------------------------------------------------------
    def stage_parse(self, user_input: str) -> Dict:
        """
        阶段1：获取用户信息 + 解析出行需求
        :return: {
            "user_info": dict,
            "intent": dict,
            "mode": str,
            "summary": str (展示用),
        }
        """
        intent, mode = self.parse_intent(user_input)
        self.intent = intent

        # 获取用户信息
        user_name_hint = intent.get("user_name", "")
        user_info = self.tools["get_user_info"].run(user_name_hint)
        self.user_name = user_info["name"]
        self.user_phone = user_info["phone"]

        # 存储关键字段
        self.scene = intent["scene"]
        self.people = intent["people"]
        self.low_calorie = intent["low_calorie"]
        self.start_time = intent["start_time"]
        self.duration = intent["duration_hours"]
        self.specified_activity = intent.get("specified_activity", "")
        self.specified_restaurant = intent.get("specified_restaurant", "")
        self.user_address = user_info.get("address", "")

        scene_label = "家庭亲子" if self.scene == "family" else "朋友聚会"

        summary = (
            f"[{mode}] 解析完成\n"
            f"  场景：{scene_label}\n"
            f"  人数：{self.people} 人\n"
            f"  出发时间：{self.start_time.strftime('%Y-%m-%d %H:%M')}（{intent.get('date_kw','今天')}）\n"
            f"  活动总时长：{self.duration} 小时（不含用餐）\n"
            f"  低卡需求：{'是' if self.low_calorie else '否'}\n"
            f"  指定活动：{self.specified_activity if self.specified_activity else '未指定（自动推荐）'}\n"
            f"  指定餐饮：{self.specified_restaurant if self.specified_restaurant else '未指定（自动推荐）'}\n"
            f"  用户：{self.user_name}（{self.user_phone}）\n"
            f"  出发地址：{self.user_address}"
        )

        return {
            "user_info": user_info,
            "intent": intent,
            "mode": mode,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # 阶段2：搜索活动方案
    # ------------------------------------------------------------------
    def stage_search_activities(self) -> Dict:
        """
        阶段2：搜索适合活动，生成差异化方案。

        行为规则：
        - 用户指定了活动关键词：
            - 搜索不到 → not_found=True，plans=[]，由 app.py 终止并告知用户
            - 搜索到1个 → 直接使用，跳过用户选择
            - 搜索到2-3个 → 让用户从中选一个（在 app.py 展示单选列表）
        - 用户未指定 → 自动推荐3个差异化方案，走方案对比流程

        :return: {
            "plans": list,
            "specified_found": bool,
            "not_found": bool,          # 用户有指定但搜不到
            "needs_activity_choice": bool,  # 是否需要用户从候选中选活动
            "has_fixed_activity": bool,     # 有且只有1个匹配，直接固定
            "summary": str,
        }
        """
        act_result = self.tools["search_activities"].run(
            self.scene, self.start_time, self.duration, self.specified_activity
        )

        # 搜索不到指定活动
        if act_result.get("not_found"):
            return {
                "plans": [],
                "specified_found": False,
                "not_found": True,
                "needs_activity_choice": False,
                "has_fixed_activity": False,
                "summary": f"  [未找到] 暂未搜索到与「{self.specified_activity}」相关的活动，请换个关键词试试。",
            }

        plans = act_result["plans"]
        specified_found = act_result["specified_found"]

        # 用户未指定（自动推荐模式）
        if not specified_found:
            if not plans:
                plans = [{
                    "name": "朝阳公园散步",
                    "duration_hours": 1.5,
                    "address": "朝阳公园东门",
                    "description": "免费绿地公园",
                    "tags": ["户外", "散步"],
                    "scene": self.scene,
                    "price": 0,
                }]
            self.activities = plans
            lines = []
            for i, p in enumerate(plans, 1):
                lines.append(f"  方案{i}：{p['name']}（{p['duration_hours']}h）—— {p.get('description', '')}")
            return {
                "plans": plans,
                "specified_found": False,
                "not_found": False,
                "needs_activity_choice": False,
                "has_fixed_activity": False,
                "summary": "\n".join(lines),
            }

        # 用户指定了，且搜到了结果
        n = len(plans)

        if n == 1:
            # 只有1个匹配，直接固定
            self.activities = plans
            act = plans[0]
            return {
                "plans": plans,
                "specified_found": True,
                "not_found": False,
                "needs_activity_choice": False,
                "has_fixed_activity": True,
                "summary": (
                    f"  [固定] 搜索到唯一匹配活动：{act['name']}（{act['duration_hours']}h）\n"
                    f"  地址：{act.get('address', '待定')}\n"
                    f"  {act.get('description', '')}"
                ),
            }
        else:
            # 2-3个匹配，需要用户选择
            self.activities = plans  # 先存着，等用户选后再更新
            lines = [f"  搜索到 {n} 个与「{self.specified_activity}」相关的活动，请选择一个："]
            for i, p in enumerate(plans, 1):
                lines.append(f"  {i}. {p['name']}（{p['duration_hours']}h，人均{p.get('price', 0)}元）—— {p.get('description', '')}")
            return {
                "plans": plans,
                "specified_found": True,
                "not_found": False,
                "needs_activity_choice": True,
                "has_fixed_activity": False,
                "summary": "\n".join(lines),
            }

    # ------------------------------------------------------------------
    # 阶段3：计算路程 + 用餐安排
    # ------------------------------------------------------------------
    def stage_calculate_meal(self, plan_index: int = 0) -> Dict:
        """
        阶段3：根据活动安排计算路程时间和用餐安排。

        计算顺序：
        1. 出发地址 → 活动地址（出发路程）
        2. 活动 → 餐厅（到店路程，如有补充活动则先算活动间路程）

        用餐时间基准 = 活动结束时间 + 到餐厅路程时间

        :param plan_index: 当前方案索引（0-2）
        :return: {
            "activity": dict,
            "activity_end": datetime,
            "route_to_activity": dict,     # 出发→活动 的路程信息
            "route_to_restaurant": dict,   # 活动→餐厅 的路程信息
            "arrival_at_restaurant": datetime,  # 到达餐厅时间
            "meal_arrangement": dict,
            "summary": str,
            "needs_ask": bool,
            "options": list,
        }
        """
        activity = self.activities[plan_index]
        act_end = self.start_time + timedelta(hours=activity["duration_hours"])

        # 1. 计算出发地址 → 活动地址的路程
        route_to_activity = self.tools["route_time"].run(
            from_address=self.user_address or "朝阳区望京西园四区",
            to_address=activity.get("address", ""),
        )
        # 活动实际开始时间 = 出发时间 + 到活动的路程
        travel_to_act_minutes = route_to_activity["duration_minutes"]
        activity_actual_start = self.start_time + timedelta(minutes=travel_to_act_minutes)

        # 检查活动是否与用餐窗口冲突（基于实际开始时间）
        conflicts = self.meal_calc.check_activity_meal_conflict(
            activity_actual_start, activity["duration_hours"]
        )

        # 2. 计算活动结束 → 餐厅的路程（此时餐厅可能还没搜到，用占位）
        #    餐厅搜索在 Step 4，这里先用活动地址本身估算（后续 Step 5 会用真实餐厅重算）
        #    为了给用户一个预估，这里不阻塞流程
        route_to_restaurant = None
        arrival_at_restaurant = None

        summary_lines = [
            f"  方案{plan_index+1} 活动信息：{activity['name']}（{activity['duration_hours']}h）",
            f"  {route_to_activity['transport_icon']} 出发路程：{self.user_address or '家'} → {activity.get('address', '')}，"
            f"{route_to_activity['transport']}约{travel_to_act_minutes}分钟",
            f"  活动开始时间：{activity_actual_start.strftime('%H:%M')}，"
            f"结束时间：{activity_actual_start.strftime('%H:%M')} + {activity['duration_hours']}h = {act_end.strftime('%H:%M')}",
        ]

        if conflicts:
            conflict_names = "、".join([c["label"] for c in conflicts])
            summary_lines.append(f"  [注意] 活动时段与 {conflict_names} 时间有重叠")

        # 用餐安排暂时基于活动结束时间计算（后续 Step 5 会加上路程时间调整）
        meal = self.meal_calc.calculate_meal_arrangement(act_end)

        if meal["in_meal_slot"]:
            slot = meal["meal_slot"]
            summary_lines.append(
                f"  [OK] 活动结束时恰好在{slot['label']}时间（{meal['meal_time'].strftime('%H:%M')}），"
                f"直接安排用餐（路程时间将在选定餐厅后更新）"
            )
        elif meal["needs_ask"]:
            summary_lines.append(f"  [需要确认] 活动结束时间不在常规用餐时间内，请选择用餐安排：")
        elif meal["meal_slot"]:
            slot = meal["meal_slot"]
            label = slot.get("meal_label") or slot.get("label", "用餐")
            summary_lines.append(
                f"  [OK] 活动结束后约30分钟内{label}（{meal['meal_time'].strftime('%H:%M')}），自动安排"
            )
        else:
            summary_lines.append(
                f"  [OK] 自动安排用餐（{meal['meal_time'].strftime('%H:%M')}）"
            )

        # 构建选项（用于 UI 复选框）
        options_for_ui = []
        if meal["needs_ask"]:
            for opt in meal["options"]:
                options_for_ui.append({
                    "label": opt["description"],
                    "meal_name": opt["meal_name"],
                    "meal_label": opt["meal_label"],
                    "suggested_time": opt["suggested_time"],
                })

        return {
            "activity": activity,
            "activity_end": act_end,
            "activity_actual_start": activity_actual_start,
            "route_to_activity": route_to_activity,
            "route_to_restaurant": route_to_restaurant,
            "arrival_at_restaurant": arrival_at_restaurant,
            "meal_arrangement": meal,
            "summary": "\n".join(summary_lines),
            "needs_ask": meal["needs_ask"],
            "options": options_for_ui,
        }

    # ------------------------------------------------------------------
    # 阶段4：搜索餐厅 + 匹配座位
    # ------------------------------------------------------------------
    def stage_search_restaurants(self) -> Dict:
        """
        阶段4：搜索合适餐厅。

        行为规则：
        - 用户指定了餐饮关键词：
            - 搜索不到 → not_found=True，restaurants=[]，由 app.py 终止并告知用户
            - 搜索到1家 → 直接固定使用，跳过选择
            - 搜索到2-3家 → 展示给用户选一家
        - 用户未指定 → 按场景自动推荐

        :return: {
            "restaurants": list,
            "specified_found": bool,
            "not_found": bool,
            "needs_rest_choice": bool,    # 是否需要用户在候选中选餐厅
            "has_fixed_restaurant": bool, # 有且只有1家匹配，直接固定
            "user_specified": bool,       # 兼容旧字段
            "summary": str,
        }
        """
        rest_result = self.tools["search_restaurants"].run(
            self.scene, self.people, self.low_calorie,
            specified_keyword=self.specified_restaurant,
        )

        # 搜索不到指定餐厅
        if rest_result.get("not_found"):
            return {
                "restaurants": [],
                "specified_found": False,
                "not_found": True,
                "needs_rest_choice": False,
                "has_fixed_restaurant": False,
                "user_specified": False,
                "summary": f"  [未找到] 暂未搜索到与「{self.specified_restaurant}」相关的餐厅，请换个关键词试试。",
            }

        restaurants = rest_result["restaurants"]
        specified_found = rest_result.get("specified_found", False)

        if not restaurants:
            # 兜底（理论上不会走到这里）
            from data.restaurants import MOCK_RESTAURANTS as _MR
            restaurants = _MR["family"]

        self.restaurants = restaurants

        n = len(restaurants)

        if specified_found and n == 1:
            # 只搜到1家，直接固定
            r = restaurants[0]
            return {
                "restaurants": restaurants,
                "specified_found": True,
                "not_found": False,
                "needs_rest_choice": False,
                "has_fixed_restaurant": True,
                "user_specified": True,
                "summary": (
                    f"  [固定] 搜索到唯一匹配餐厅：{r['name']}（{r['cuisine']}，人均{r['price_per_person']}元）\n"
                    f"  地址：{r['address']}\n"
                    f"  {r.get('description', '')}"
                ),
            }
        elif specified_found and n >= 2:
            # 2-3家，需要用户选
            lines = [f"  搜索到 {n} 家与「{self.specified_restaurant}」相关的餐厅，请选择："]
            for i, r in enumerate(restaurants, 1):
                lines.append(f"  {i}. {r['name']}（{r['cuisine']}，人均{r['price_per_person']}元）—— {r.get('description', '')}")
            return {
                "restaurants": restaurants,
                "specified_found": True,
                "not_found": False,
                "needs_rest_choice": True,
                "has_fixed_restaurant": False,
                "user_specified": True,
                "summary": "\n".join(lines),
            }
        else:
            # 未指定，自动推荐模式，显示列表让用户选
            lines = [f"  为您推荐 {n} 家餐厅："]
            for i, r in enumerate(restaurants, 1):
                lines.append(f"  {i}. {r['name']}（{r['cuisine']}，人均{r['price_per_person']}元）")
            return {
                "restaurants": restaurants,
                "specified_found": False,
                "not_found": False,
                "needs_rest_choice": n > 1,
                "has_fixed_restaurant": n == 1,
                "user_specified": False,
                "summary": "\n".join(lines),
            }

    def stage_match_restaurant(self, meal_time: datetime, restaurant: Dict = None, activity: Dict = None) -> Dict:
        """
        阶段4b：为指定用餐时间匹配餐厅并检查座位，同时计算活动→餐厅的路程。

        用餐时间 = 原始 meal_time（已经在前面的阶段基于活动结束时间计算好的）

        :param meal_time: 建议用餐时间
        :param restaurant: 用户指定的餐厅（如果为 None，则自动匹配）
        :param activity: 当前方案的活动（用于计算路程）
        :return: {
            "restaurant": dict,
            "available": bool,
            "queue_minutes": int,
            "route_to_restaurant": dict,   # 活动→餐厅的路程信息
            "adjusted_meal_time": datetime, # 加上路程时间后的实际用餐时间
            "summary": str,
        }
        """
        # 如果用户已指定餐厅，直接使用
        if restaurant is not None:
            check_result = self.tools["check_reservation"].run(
                restaurant["name"], meal_time, self.people
            )

            # 计算活动→餐厅的路程
            act_address = (activity or {}).get("address", "") or self.user_address
            route = self.tools["route_time"].run(
                from_address=act_address,
                to_address=restaurant.get("address", ""),
            )
            travel_minutes = route["duration_minutes"]
            adjusted_time = meal_time + timedelta(minutes=travel_minutes)

            return {
                "restaurant": restaurant,
                "available": check_result["available"],
                "queue_minutes": check_result["queue_minutes"],
                "route_to_restaurant": route,
                "adjusted_meal_time": adjusted_time,
                "summary": (
                    f"  {route['transport_icon']} 路程：{act_address} → {restaurant['address']}，"
                    f"{route['transport']}约{travel_minutes}分钟\n"
                    f"  匹配到：{restaurant['name']}（{restaurant['cuisine']}，人均{restaurant['price_per_person']}元）\n"
                    f"  预计到达餐厅：{adjusted_time.strftime('%H:%M')}，用餐时间：{adjusted_time.strftime('%H:%M')}\n"
                    + (f"  [OK] 当前有位" if check_result["available"]
                       else f"  [排队] 预计排队 {check_result['queue_minutes']} 分钟")
                ),
            }

        # 自动匹配：遍历餐厅找有位的
        chosen_rest = None
        check_result = None

        for rest in self.restaurants:
            check = self.tools["check_reservation"].run(rest["name"], meal_time, self.people)
            if check["available"]:
                chosen_rest = rest
                check_result = check
                break

        if not chosen_rest:
            chosen_rest = self.restaurants[0]
            check_result = self.tools["check_reservation"].run(
                chosen_rest["name"], meal_time, self.people
            )

        # 计算路程
        act_address = (activity or {}).get("address", "") or self.user_address
        route = self.tools["route_time"].run(
            from_address=act_address,
            to_address=chosen_rest.get("address", ""),
        )
        travel_minutes = route["duration_minutes"]
        adjusted_time = meal_time + timedelta(minutes=travel_minutes)

        return {
            "restaurant": chosen_rest,
            "available": check_result["available"],
            "queue_minutes": check_result["queue_minutes"],
            "route_to_restaurant": route,
            "adjusted_meal_time": adjusted_time,
            "summary": (
                f"  {route['transport_icon']} 路程：{act_address} → {chosen_rest['address']}，"
                f"{route['transport']}约{travel_minutes}分钟\n"
                f"  匹配到：{chosen_rest['name']}（{chosen_rest['cuisine']}，人均{chosen_rest['price_per_person']}元）\n"
                f"  预计到达餐厅：{adjusted_time.strftime('%H:%M')}，用餐时间：{adjusted_time.strftime('%H:%M')}\n"
                + (f"  [OK] 当前有位" if check_result["available"]
                   else f"  [排队] 预计排队 {check_result['queue_minutes']} 分钟")
            ),
        }

    # ------------------------------------------------------------------
    # 阶段5：检查是否需要追加活动
    # ------------------------------------------------------------------
    def stage_check_fill_activities(self, current_hours: float) -> Dict:
        """
        阶段5：如果当前活动时长不足目标时长，搜索补充活动。
        
        :param current_hours: 当前已安排的活动总时长
        :return: {
            "needs_fill": bool,
            "remaining_hours": float,
            "fill_activities": list,  # 可追加的活动
            "summary": str,
        }
        """
        remaining = self.duration - current_hours

        if remaining <= 0.5:
            return {
                "needs_fill": False,
                "remaining_hours": 0,
                "fill_activities": [],
                "summary": f"  [OK] 活动时长 {current_hours:.1f}h 已满足目标 {self.duration}h",
            }

        # 搜索可以填补时长的活动（排除已选的）
        used_names = {a["name"] for a in self.activities}
        from data.activities import MOCK_ACTIVITIES
        candidates = [
            a for a in MOCK_ACTIVITIES
            if a["name"] not in used_names
            and a["duration_hours"] <= remaining
        ]

        # 按时长排序（优先接近剩余时长的）
        candidates.sort(key=lambda x: -x["duration_hours"])

        fill_activities = candidates[:3] if len(candidates) >= 3 else candidates

        if not fill_activities:
            return {
                "needs_fill": False,
                "remaining_hours": remaining,
                "fill_activities": [],
                "summary": f"  [提示] 活动时长 {current_hours:.1f}h，距离目标 {self.duration}h 还差 {remaining:.1f}h，暂无合适的补充活动",
            }

        lines = [
            f"  [提示] 当前活动时长 {current_hours:.1f}h，距离目标 {self.duration}h 还差 {remaining:.1f}h",
            f"  以下活动可补充（选择一个追加到行程中）："
        ]
        for i, a in enumerate(fill_activities, 1):
            lines.append(f"  补充{i}：{a['name']}（{a['duration_hours']}h）—— {a.get('description', '')}")

        return {
            "needs_fill": True,
            "remaining_hours": remaining,
            "fill_activities": fill_activities,
            "summary": "\n".join(lines),
        }

    # ------------------------------------------------------------------
    # 阶段6：生成方案对比（供用户选择）
    # ------------------------------------------------------------------
    def stage_build_plan_comparison(self, plan_configs: List[Dict]) -> Dict:
        """
        阶段6：根据所有方案的配置，生成对比信息。

        :param plan_configs: 每个方案的配置列表
        :return: {
            "comparison": list,
            "summary": str,
        }
        """
        comparison = []

        for i, cfg in enumerate(plan_configs, 1):
            act = cfg["activity"]
            rest = cfg.get("restaurant", {})
            meal_time = cfg.get("adjusted_meal_time") or cfg.get("meal_time")
            fill_act = cfg.get("fill_activity")
            pre_meal_act = cfg.get("pre_meal_fill_chosen")
            post_meal_act = cfg.get("post_meal_fill_chosen")
            meal_label = cfg.get("meal_label", "用餐")
            route_to_act = cfg.get("route_to_activity", {})
            route_to_rest = cfg.get("route_to_restaurant", {})

            act_end = self.start_time + timedelta(hours=act["duration_hours"])

            total_act_h = act["duration_hours"]
            if pre_meal_act:
                total_act_h += pre_meal_act["duration_hours"]
            if post_meal_act:
                total_act_h += post_meal_act["duration_hours"]
            if fill_act:
                total_act_h += fill_act["duration_hours"]

            # 构建方案标签：展示完整时间线
            travel_to_act = route_to_act.get("duration_minutes", 0)
            act_start_str = (self.start_time + timedelta(minutes=travel_to_act)).strftime("%H:%M")

            line = f"方案{i}："
            line += f"{self.start_time.strftime('%H:%M')}出发"
            line += f"{route_to_act.get('transport_icon', '🚶')}{route_to_act.get('transport', '')}约{travel_to_act}min"
            line += f"→ {act['name']}（{act['duration_hours']}h，{act_start_str}开始）"

            # 餐前活动（如果有）
            if pre_meal_act:
                activity_actual_start = cfg.get("activity_actual_start", self.start_time)
                act_end_time = activity_actual_start + timedelta(hours=act["duration_hours"])
                route_to_premeal = cfg.get("route_to_premeal", {})
                premeal_travel = route_to_premeal.get("duration_minutes", 0)
                premeal_start = cfg.get("premeal_start", act_end_time + timedelta(minutes=15 + premeal_travel))
                line += f" → {route_to_premeal.get('transport_icon', '🚶')}{route_to_premeal.get('transport', '')}约{premeal_travel}min"
                line += f"→ {pre_meal_act['name']}（{pre_meal_act['duration_hours']}h，{premeal_start.strftime('%H:%M')}开始）"
                route_premeal_rest = cfg.get("route_premeal_to_rest", {})
                if route_premeal_rest:
                    premeal_rest_travel = route_premeal_rest.get("duration_minutes", 0)
                    line += f" → {route_premeal_rest.get('transport_icon', '🚗')}{route_premeal_rest.get('transport', '')}约{premeal_rest_travel}min"
            elif fill_act:
                fill_route = cfg.get("route_to_fill", {})
                fill_travel = fill_route.get("duration_minutes", 0) if fill_route else 10
                fill_start_str = (act_end + timedelta(minutes=15 + fill_travel)).strftime("%H:%M")
                line += f" → {fill_act['name']}（{fill_act['duration_hours']}h，{fill_start_str}开始）"

            # 等待就餐（活动结束到出发去餐厅之间有空闲）
            has_wait = cfg.get("has_wait", False)
            if has_wait:
                wait_start = cfg.get("wait_start")
                wait_end = cfg.get("wait_end")
                wait_min = cfg.get("wait_minutes", 0)
                if wait_start and wait_end:
                    line += f" → ⏳等待{wait_min:.0f}min（{wait_start.strftime('%H:%M')}~{wait_end.strftime('%H:%M')}）"

            if meal_time:
                rest_travel = route_to_rest.get("duration_minutes", 0)
                if not pre_meal_act:
                    line += f" → {route_to_rest.get('transport_icon', '🚗')}{route_to_rest.get('transport', '')}约{rest_travel}min"
                line += f" → {meal_label}（{meal_time.strftime('%H:%M')}）"
            if rest:
                line += f" @ {rest['name']}"

            # 餐后活动（如果有）
            if post_meal_act:
                postmeal_start = cfg.get("postmeal_start")
                if postmeal_start:
                    route_rest_to_post = cfg.get("route_rest_to_postmeal", {})
                    post_travel = route_rest_to_post.get("duration_minutes", 0) if route_rest_to_post else 0
                    line += f" → {route_rest_to_post.get('transport_icon', '🚗') if route_rest_to_post else '🚗'}约{post_travel}min"
                    line += f"→ {post_meal_act['name']}（{post_meal_act['duration_hours']}h，{postmeal_start.strftime('%H:%M')}开始）"

            comparison.append({
                "index": i - 1,
                "label": line,
                "total_activity_hours": total_act_h,
                "activity": act,
                "fill_activity": fill_act,
                "pre_meal_activity": pre_meal_act,
                "post_meal_activity": post_meal_act,
                "restaurant": rest,
                "meal_time": meal_time,
                "adjusted_meal_time": cfg.get("adjusted_meal_time"),
                "meal_label": meal_label,
                "route_to_activity": route_to_act,
                "route_to_restaurant": route_to_rest,
                "has_wait": cfg.get("has_wait", False),
                "wait_start": cfg.get("wait_start"),
                "wait_end": cfg.get("wait_end"),
                "wait_minutes": cfg.get("wait_minutes", 0),
                "wait_label": cfg.get("wait_label", ""),
            })

        lines = ["方案对比："]
        for c in comparison:
            lines.append(f"  {c['label']}")

        return {
            "comparison": comparison,
            "summary": "\n".join(lines),
        }

    # ------------------------------------------------------------------
    # 阶段7：执行预订
    # ------------------------------------------------------------------
    def stage_book(self, plan_config: Dict) -> Dict:
        """
        阶段7：为用户选定的方案执行预订。

        :param plan_config: 选定方案的完整配置
        :return: {
            "booking_results": dict,
            "summary": str,
        }
        """
        act = plan_config["activity"]
        fill_act = plan_config.get("fill_activity")
        pre_meal_act = plan_config.get("pre_meal_activity")
        post_meal_act = plan_config.get("post_meal_activity")
        rest = plan_config.get("restaurant")
        meal_time = plan_config.get("meal_time")

        # 预订活动
        act_book = self.tools["book_activity"].run(
            act["name"], self.start_time, self.people,
            user_name=self.user_name, user_phone=self.user_phone,
        )

        # 预订补充活动（如果有）
        fill_book = None
        if fill_act:
            fill_start = self.start_time + timedelta(hours=act["duration_hours"]) + timedelta(minutes=15)
            fill_book = self.tools["book_activity"].run(
                fill_act["name"], fill_start, self.people,
                user_name=self.user_name, user_phone=self.user_phone,
            )

        # 预订餐前活动（如果有）
        pre_meal_book = None
        if pre_meal_act:
            activity_actual_start = plan_config.get("activity_actual_start", self.start_time)
            act_end = activity_actual_start + timedelta(hours=act["duration_hours"])
            route_to_premeal = plan_config.get("route_to_premeal", {})
            premeal_travel = route_to_premeal.get("duration_minutes", 10)
            premeal_start = act_end + timedelta(minutes=15 + premeal_travel)
            pre_meal_book = self.tools["book_activity"].run(
                pre_meal_act["name"], premeal_start, self.people,
                user_name=self.user_name, user_phone=self.user_phone,
            )

        # 预订餐后活动（如果有）
        post_meal_book = None
        if post_meal_act:
            postmeal_start = plan_config.get("postmeal_start")
            if postmeal_start:
                post_meal_book = self.tools["book_activity"].run(
                    post_meal_act["name"], postmeal_start, self.people,
                    user_name=self.user_name, user_phone=self.user_phone,
                )

        # 预订餐厅（如果有）
        rest_book = None
        if rest and meal_time:
            special = "请备注减肥低卡菜品推荐" if self.low_calorie else ""
            rest_book = self.tools["book_restaurant"].run(
                rest["name"], meal_time, self.people, special,
                user_name=self.user_name, user_phone=self.user_phone,
            )

        lines = [
            f"  [OK] 已预订【{act['name']}】门票 {self.people} 张，{self.start_time.strftime('%H:%M')} 场次，票号：{act_book['ticket_id']}",
        ]
        if fill_book:
            lines.append(f"  [OK] 已预订【{fill_act['name']}】门票 {self.people} 张，票号：{fill_book['ticket_id']}")
        if pre_meal_book:
            lines.append(f"  [OK] 已预订餐前活动【{pre_meal_act['name']}】门票 {self.people} 张，票号：{pre_meal_book['ticket_id']}")
        if post_meal_book:
            lines.append(f"  [OK] 已预订餐后活动【{post_meal_act['name']}】门票 {self.people} 张，票号：{post_meal_book['ticket_id']}")
        if rest_book:
            extra = f"，备注：减肥低卡菜品推荐" if self.low_calorie else ""
            lines.append(f"  [OK] 已预订【{rest['name']}】{self.people} 位，{meal_time.strftime('%H:%M')} 就餐{extra}，预订号：{rest_book['booking_id']}")

        self.final_plan = {
            "activity": act,
            "fill_activity": fill_act,
            "pre_meal_activity": pre_meal_act,
            "post_meal_activity": post_meal_act,
            "restaurant": rest,
            "meal_time": meal_time,
            "act_book": act_book,
            "fill_book": fill_book,
            "pre_meal_book": pre_meal_book,
            "post_meal_book": post_meal_book,
            "rest_book": rest_book,
        }

        return {
            "booking_results": {
                "act_book": act_book,
                "fill_book": fill_book,
                "pre_meal_book": pre_meal_book,
                "post_meal_book": post_meal_book,
                "rest_book": rest_book,
            },
            "summary": "\n".join(lines),
        }

    # ------------------------------------------------------------------
    # 阶段8：生成最终计划文本
    # ------------------------------------------------------------------
    def stage_generate_plan(self, plan_config: Dict):
        """
        阶段8：生成最终出行计划文案（流式输出）。
        逐 token yield 文本片段，供 Gradio 流式展示。
        """
        act = plan_config["activity"]
        fill_act = plan_config.get("fill_activity")
        rest = plan_config.get("restaurant")
        meal_time = plan_config.get("adjusted_meal_time") or plan_config.get("meal_time")
        meal_label = plan_config.get("meal_label", "用餐")
        route_to_act = plan_config.get("route_to_activity", {})
        route_to_rest = plan_config.get("route_to_restaurant", {})

        # 计算活动实际开始时间
        travel_to_act_min = route_to_act.get("duration_minutes", 0)
        activity_start = self.start_time + timedelta(minutes=travel_to_act_min)
        activity_end = activity_start + timedelta(hours=act["duration_hours"])

        # 等待信息
        has_wait = plan_config.get("has_wait", False)
        wait_start = plan_config.get("wait_start")
        wait_end = plan_config.get("wait_end")
        wait_minutes = plan_config.get("wait_minutes", 0)

        # 构建 LLM context
        activities_list = [{
            "name": act["name"],
            "duration_hours": act["duration_hours"],
            "address": act.get("address", ""),
            "start_time": activity_start.strftime("%H:%M"),
            "end_time": activity_end.strftime("%H:%M"),
        }]
        ticket_ids = [self.final_plan["act_book"]["ticket_id"]]

        # 餐前活动（在主活动结束后、用餐之前）
        pre_meal_act = plan_config.get("pre_meal_activity")
        if pre_meal_act:
            route_to_premeal = plan_config.get("route_to_premeal", {})
            premeal_travel = route_to_premeal.get("duration_minutes", 10)
            premeal_start = activity_end + timedelta(minutes=15 + premeal_travel)
            premeal_end = premeal_start + timedelta(hours=pre_meal_act["duration_hours"])
            activities_list.append({
                "name": pre_meal_act["name"],
                "duration_hours": pre_meal_act["duration_hours"],
                "address": pre_meal_act.get("address", ""),
                "start_time": premeal_start.strftime("%H:%M"),
                "end_time": premeal_end.strftime("%H:%M"),
            })
            if self.final_plan.get("pre_meal_book"):
                ticket_ids.append(self.final_plan["pre_meal_book"]["ticket_id"])
            activity_end = premeal_end

        if fill_act:
            fill_travel = plan_config.get("route_to_fill", {}).get("duration_minutes", 10)
            fill_start = activity_end + timedelta(minutes=15 + fill_travel)
            fill_end = fill_start + timedelta(hours=fill_act["duration_hours"])
            activities_list.append({
                "name": fill_act["name"],
                "duration_hours": fill_act["duration_hours"],
                "address": fill_act.get("address", ""),
                "start_time": fill_start.strftime("%H:%M"),
                "end_time": fill_end.strftime("%H:%M"),
            })
            if self.final_plan.get("fill_book"):
                ticket_ids.append(self.final_plan["fill_book"]["ticket_id"])

        total_act_h = sum(a["duration_hours"] for a in activities_list)

        # 餐后活动（在用餐之后）
        post_meal_act = plan_config.get("post_meal_activity")
        if post_meal_act:
            postmeal_start = plan_config.get("postmeal_start")
            postmeal_end = plan_config.get("postmeal_end")
            if postmeal_start and postmeal_end:
                activities_list.append({
                    "name": post_meal_act["name"],
                    "duration_hours": post_meal_act["duration_hours"],
                    "address": post_meal_act.get("address", ""),
                    "start_time": postmeal_start.strftime("%H:%M"),
                    "end_time": postmeal_end.strftime("%H:%M"),
                })
                if self.final_plan.get("post_meal_book"):
                    ticket_ids.append(self.final_plan["post_meal_book"]["ticket_id"])
                total_act_h += post_meal_act["duration_hours"]

        # 路程信息文本
        route_to_rest_min = route_to_rest.get("duration_minutes", 0)
        route_to_premeal = plan_config.get("route_to_premeal", {})
        route_premeal_to_rest = plan_config.get("route_premeal_to_rest", {})
        route_rest_to_postmeal = plan_config.get("route_rest_to_postmeal", {})

        route_summary = (
            f"出发地：{self.user_address or '家'}\n"
            f"出发→活动1：{route_to_act.get('transport_icon', '🚶')} {route_to_act.get('transport', '步行')}"
            f"约{travel_to_act_min}分钟（{route_to_act.get('distance_km', 0)}km）\n"
        )
        if pre_meal_act and route_to_premeal:
            premeal_travel = route_to_premeal.get("duration_minutes", 0)
            route_summary += (
                f"活动1→餐前活动：{route_to_premeal.get('transport_icon', '🚶')} {route_to_premeal.get('transport', '步行')}"
                f"约{premeal_travel}分钟\n"
            )
            if route_premeal_to_rest:
                premeal_rest_travel = route_premeal_to_rest.get("duration_minutes", 0)
                route_summary += (
                    f"餐前活动→餐厅：{route_premeal_to_rest.get('transport_icon', '🚗')} {route_premeal_to_rest.get('transport', '打车')}"
                    f"约{premeal_rest_travel}分钟\n"
                )
        else:
            route_summary += (
                f"活动→餐厅：{route_to_rest.get('transport_icon', '🚗')} {route_to_rest.get('transport', '打车')}"
                f"约{route_to_rest_min}分钟（{route_to_rest.get('distance_km', 0)}km）"
            )

        if post_meal_act and route_rest_to_postmeal:
            postmeal_travel = route_rest_to_postmeal.get("duration_minutes", 0)
            route_summary += (
                f"\n餐厅→餐后活动：{route_rest_to_postmeal.get('transport_icon', '🚗')} {route_rest_to_postmeal.get('transport', '打车')}"
                f"约{postmeal_travel}分钟"
            )

        context = {
            "scene": self.scene,
            "user_name": self.user_name,
            "people": self.people,
            "start_time": self.start_time.strftime("%Y-%m-%d %H:%M"),
            "total_activity_hours": total_act_h,
            "activities": activities_list,
            "has_wait": has_wait,
            "wait_info": {
                "start": wait_start.strftime("%H:%M") if wait_start else "",
                "end": wait_end.strftime("%H:%M") if wait_end else "",
                "minutes": int(wait_minutes) if wait_minutes else 0,
                "label": f"等待就餐，从{wait_start.strftime('%H:%M')}到{wait_end.strftime('%H:%M')}，约{wait_minutes:.0f}分钟" if has_wait and wait_start and wait_end else "",
                "suggestions": [
                    f"{s['icon']} {s['text']}" for s in self._get_wait_suggestions(wait_minutes)
                ] if has_wait and wait_minutes else [],
            } if has_wait else None,
            "restaurant": {
                "name": rest.get("name", "") if rest else "",
                "address": rest.get("address", "") if rest else "",
                "meal_time": meal_time.strftime("%H:%M") if meal_time else "",
                "meal_label": meal_label,
            } if rest else {},
            "ticket_ids": ticket_ids,
            "booking_id": self.final_plan["rest_book"]["booking_id"] if self.final_plan.get("rest_book") else "",
            "special_note": "请备注减肥低卡菜品推荐" if self.low_calorie else "",
            "route_summary": route_summary,
        }

        # 先 yield header，再流式输出正文
        if self.user_name and self.user_name != "用户":
            header = f"\n{'='*55}\n全部完成！{self.user_name}，您的出行计划已准备就绪\n{'='*55}\n\n"
        else:
            header = f"\n{'='*55}\n全部完成！您的出行计划已准备就绪\n{'='*55}\n\n"

        # 尝试 LLM 流式输出
        full_text = ""
        for chunk in self.llm.generate_plan_text_stream(context):
            full_text += chunk
            yield header + full_text

        # LLM 流式无输出，降级到模板（逐段 yield）
        if not full_text:
            fallback_text = self._fallback_plan_text(context, plan_config)
            yield header + fallback_text

    def _get_wait_suggestions(self, wait_minutes: float) -> list:
        """根据场景和等待时长，推荐打发时间的方法。

        返回建议列表，每条格式为 {"icon": str, "text": str}
        """
        if self.scene == "family":
            # 家庭亲子场景
            if wait_minutes <= 30:
                suggestions = [
                    {"icon": "🎮", "text": "带孩子玩一把手游（王者荣耀/蛋仔派对）"},
                    {"icon": "☕", "text": "找家便利店/咖啡店坐坐，买点零食"},
                    {"icon": "📸", "text": "在附近拍拍照片，记录美好瞬间"},
                    {"icon": "🌳", "text": "找个公园长椅休息，聊聊天"},
                ]
            elif wait_minutes <= 60:
                suggestions = [
                    {"icon": "🎮", "text": "打两局王者荣耀/和平精英，时间刚刚好"},
                    {"icon": "🛍️", "text": "附近商场逛逛，看看有什么好玩的"},
                    {"icon": "🍦", "text": "找个奶茶店或甜品店，享受下午茶时光"},
                    {"icon": "🏃", "text": "去附近公园走走，让孩子跑跑跳跳消耗体力"},
                    {"icon": "📸", "text": "来一组创意拍照，发朋友圈打卡"},
                ]
            else:
                suggestions = [
                    {"icon": "🎮", "text": "开黑打几局游戏，王者/吃鸡走起"},
                    {"icon": "🛍️", "text": "附近商场逛一圈，顺便给孩子买点小礼物"},
                    {"icon": "🎬", "text": "找家影院看场短电影或动画片"},
                    {"icon": "☕", "text": "找个咖啡厅坐下来，点杯喝的刷刷手机"},
                    {"icon": "🎮", "text": "找个电玩城/抓娃娃机店，大人小孩都能玩"},
                    {"icon": "🌳", "text": "去附近的公园散步遛弯，消食放松"},
                ]
        else:
            # 朋友聚会场景
            if wait_minutes <= 30:
                suggestions = [
                    {"icon": "🎮", "text": "来一局王者荣耀/金铲铲，等位不打紧"},
                    {"icon": "☕", "text": "买杯咖啡或奶茶，边喝边聊"},
                    {"icon": "🚬", "text": "找个地方坐坐，聊聊八卦和近况"},
                    {"icon": "📸", "text": "拍几张合照发朋友圈，等人不如拍照"},
                ]
            elif wait_minutes <= 60:
                suggestions = [
                    {"icon": "🎮", "text": "打两把王者/吃鸡，输了的请吃饭"},
                    {"icon": "🛍️", "text": "附近商场逛逛，消磨一下时间"},
                    {"icon": "🎱", "text": "找个台球厅打一局，输了买奶茶"},
                    {"icon": "🍦", "text": "找个甜品店坐下聊天，来份下午茶"},
                    {"icon": "🏃", "text": "去周边转转，说不定能发现宝藏小店"},
                ]
            else:
                suggestions = [
                    {"icon": "🎮", "text": "网吧开黑！王者/LOL/吃鸡，来几把热血对决"},
                    {"icon": "🛍️", "text": "商场逛街购物，顺便看看有没有好吃的"},
                    {"icon": "🎬", "text": "找个私人影院/KTV，嗨唱几首等饭点"},
                    {"icon": "🎱", "text": "去打台球/保龄球，运动一下等吃饭"},
                    {"icon": "☕", "text": "找个安静的咖啡厅，点杯拿铁慢慢聊"},
                    {"icon": "🎮", "text": "找个电玩城，抓娃娃赛车投篮机通通安排"},
                    {"icon": "💆", "text": "附近按个脚/做个SPA，吃完饭刚好放松"},
                ]

        return suggestions

    def _format_wait_section(self, wait_start, wait_end, wait_minutes: float, suggestions: list) -> list:
        """格式化等待段落的文本行。"""
        lines = [
            "",
            f"  {wait_start.strftime('%H:%M')}  ⏳ 等待就餐（约{wait_minutes:.0f}分钟）",
            f"  {wait_start.strftime('%H:%M')}~{wait_end.strftime('%H:%M')}  💡 推荐以下方式消磨时间：",
        ]
        for s in suggestions:
            lines.append(f"    {s['icon']} {s['text']}")
        lines.append(f"  {wait_end.strftime('%H:%M')}  出发前往餐厅")
        return lines

    def _fallback_plan_text(self, context: dict, plan_config: Dict) -> str:
        """降级模板生成，展示完整时间线（含路程时间、餐后活动）"""
        act = plan_config["activity"]
        fill_act = plan_config.get("fill_activity")
        pre_meal_act = plan_config.get("pre_meal_activity")
        post_meal_act = plan_config.get("post_meal_activity")
        rest = plan_config.get("restaurant")
        meal_time = plan_config.get("adjusted_meal_time") or plan_config.get("meal_time")
        meal_label = plan_config.get("meal_label", "用餐")
        route_to_act = plan_config.get("route_to_activity", {})
        route_to_rest = plan_config.get("route_to_restaurant", {})
        route_to_premeal = plan_config.get("route_to_premeal", {})
        route_premeal_to_rest = plan_config.get("route_premeal_to_rest", {})
        route_rest_to_postmeal = plan_config.get("route_rest_to_postmeal", {})

        user_name = self.user_name
        scene_label = "家庭亲子" if self.scene == "family" else "朋友聚会"

        if user_name and user_name != "用户":
            greeting = f"{user_name}！这是为您精心准备的出行计划，请查收！"
        else:
            greeting = "这是为您精心准备的出行计划，请查收！"

        # 计算实际时间线
        travel_to_act_min = route_to_act.get("duration_minutes", 0)
        activity_start = self.start_time + timedelta(minutes=travel_to_act_min)
        activity_end = activity_start + timedelta(hours=act["duration_hours"])

        total_travel_min = travel_to_act_min
        travel_to_rest_min = route_to_rest.get("duration_minutes", 0)

        lines = [
            f"**{greeting}**",
            f"",
            f"**出发时间**：{self.start_time.strftime('%Y-%m-%d %H:%M')}（{self.user_address or '家'}）",
            f"**出行人数**：{self.people} 人 · {scene_label}",
            f"**活动总时长**：{context['total_activity_hours']}小时",
            f"",
            f"{'='*40}",
            f"**时间线**",
            f"",
            f"  {self.start_time.strftime('%H:%M')}  🏠 出发",
            f"  {route_to_act.get('transport_icon', '🚶')} {route_to_act.get('transport', '步行')}前往{act['name']}，"
            f"约{travel_to_act_min}分钟（{route_to_act.get('distance_km', 0)}km）",
            f"",
            f"  {activity_start.strftime('%H:%M')}  🎯 {act['name']}",
            f"  地址：{act.get('address', '见地图')}",
            f"  时长：约 {act['duration_hours']} 小时",
            f"  预订号：{self.final_plan['act_book']['ticket_id']}",
            f"  {activity_end.strftime('%H:%M')}  活动结束",
        ]

        # 餐前活动（在主活动结束后、用餐之前）
        if pre_meal_act:
            premeal_travel = route_to_premeal.get("duration_minutes", 10)
            premeal_start = activity_end + timedelta(minutes=15 + premeal_travel)
            premeal_end = premeal_start + timedelta(hours=pre_meal_act["duration_hours"])
            premeal_rest_travel = route_premeal_to_rest.get("duration_minutes", 0)
            total_travel_min += premeal_travel + premeal_rest_travel
            lines += [
                f"",
                f"  {route_to_premeal.get('transport_icon', '🚶')} {route_to_premeal.get('transport', '步行') if route_to_premeal else '步行'}前往{pre_meal_act['name']}，"
                f"约{premeal_travel}分钟",
                f"",
                f"  {premeal_start.strftime('%H:%M')}  🎯 {pre_meal_act['name']}",
                f"  地址：{pre_meal_act.get('address', '见地图')}",
                f"  时长：约 {pre_meal_act['duration_hours']} 小时",
                f"  预订号：{self.final_plan['pre_meal_book']['ticket_id']}" if self.final_plan.get("pre_meal_book") else "",
                f"  {premeal_end.strftime('%H:%M')}  活动结束",
            ]
            activity_end = premeal_end
            if route_premeal_to_rest:
                lines += [
                    f"",
                    f"  {route_premeal_to_rest.get('transport_icon', '🚗')} {route_premeal_to_rest.get('transport', '打车')}前往{rest['name']}，"
                    f"约{premeal_rest_travel}分钟（{route_premeal_to_rest.get('distance_km', 0)}km）",
                ]
        elif fill_act:
            fill_route = plan_config.get("route_to_fill", {})
            fill_travel = fill_route.get("duration_minutes", 10)
            fill_start = activity_end + timedelta(minutes=15 + fill_travel)
            fill_end = fill_start + timedelta(hours=fill_act["duration_hours"])
            total_travel_min += fill_travel
            lines += [
                f"",
                f"  {route_to_rest.get('transport_icon', '🚗')} {fill_route.get('transport', '打车') if fill_route else '打车'}前往{fill_act['name']}，"
                f"约{fill_travel}分钟",
                f"",
                f"  {fill_start.strftime('%H:%M')}  🎯 {fill_act['name']}",
                f"  地址：{fill_act.get('address', '见地图')}",
                f"  时长：约 {fill_act['duration_hours']} 小时",
                f"  预订号：{self.final_plan['fill_book']['ticket_id']}" if self.final_plan.get("fill_book") else "",
                f"  {fill_end.strftime('%H:%M')}  活动结束",
            ]
            activity_end = fill_end

        # 等待就餐（活动结束到出发去餐厅之间有空闲）
        has_wait = plan_config.get("has_wait", False)
        wait_start = plan_config.get("wait_start")
        wait_end = plan_config.get("wait_end")
        wait_minutes = plan_config.get("wait_minutes", 0)

        if has_wait and wait_start and wait_end and wait_minutes > 15:
            suggestions = self._get_wait_suggestions(wait_minutes)
            lines += self._format_wait_section(wait_start, wait_end, wait_minutes, suggestions)

        # 用餐
        if rest and meal_time:
            if not pre_meal_act:
                lines += [
                    f"",
                    f"  {route_to_rest.get('transport_icon', '🚗')} {route_to_rest.get('transport', '打车')}前往{rest['name']}，"
                    f"约{travel_to_rest_min}分钟（{route_to_rest.get('distance_km', 0)}km）",
                ]
                total_travel_min += travel_to_rest_min
            lines += [
                f"",
                f"  {meal_time.strftime('%H:%M')}  🍽️ {meal_label}：{rest['name']}（{rest.get('cuisine', '')}）",
                f"  地址：{rest['address']}",
                f"  人均：{rest['price_per_person']}元",
                f"  预订号：{self.final_plan['rest_book']['booking_id']}" if self.final_plan.get("rest_book") else "",
            ]
            if self.low_calorie:
                lines.append(f"  备注：已要求推荐低卡菜品")

        # 餐后活动（在用餐之后）
        if post_meal_act and route_rest_to_postmeal:
            postmeal_travel = route_rest_to_postmeal.get("duration_minutes", 0)
            postmeal_start = plan_config.get("postmeal_start")
            postmeal_end = plan_config.get("postmeal_end")
            if postmeal_start and postmeal_end:
                total_travel_min += postmeal_travel
                lines += [
                    f"",
                    f"  {route_rest_to_postmeal.get('transport_icon', '🚗')} {route_rest_to_postmeal.get('transport', '打车')}前往{post_meal_act['name']}，"
                    f"约{postmeal_travel}分钟",
                    f"",
                    f"  {postmeal_start.strftime('%H:%M')}  🎯 {post_meal_act['name']}",
                    f"  地址：{post_meal_act.get('address', '见地图')}",
                    f"  时长：约 {post_meal_act['duration_hours']} 小时",
                    f"  预订号：{self.final_plan['post_meal_book']['ticket_id']}" if self.final_plan.get("post_meal_book") else "",
                    f"  {postmeal_end.strftime('%H:%M')}  活动结束",
                ]

        lines += [
            f"",
            f"**路程总耗时**：约{total_travel_min}分钟",
            f"{'='*40}",
            f"门票 & 餐位已预订完成，按时出发即可！",
        ]
        return "\n".join(lines)
