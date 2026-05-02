"""
路程时间计算工具
Mock 模式：根据两个地址的行政区划前缀生成合理的路程时间

Mock 规则：
- 同一区（如都是"朝阳区"）→ 步行10-20min 或 骑车10-15min
- 不同区（如"朝阳区" vs "海淀区"）→ 地铁25-45min 或 打车20-40min
- 返回：路程时长（分钟）、交通方式建议、距离估算
"""

import random
import re
from typing import Dict, Optional, Tuple

from .base import Tool


# 北京主要行政区划
_DISTRICTS = [
    "东城区", "西城区", "朝阳区", "海淀区", "丰台区", "石景山区",
    "通州区", "顺义区", "大兴区", "昌平区", "房山区", "门头沟区",
]


def _extract_district(address: str) -> Optional[str]:
    """从地址中提取行政区划"""
    for d in _DISTRICTS:
        if d in address:
            return d
    return None


def _extract_street(address: str) -> Optional[str]:
    """从地址中提取路名/街道（取第一个"路"或"街"开头的词）"""
    m = re.search(r'([\u4e00-\u9fa5]+(?:路|街|大道|巷|胡同))', address)
    return m.group(1) if m else None


class RouteTimeTool(Tool):
    """
    路程时间计算工具。
    根据两个地点的地址，估算路程时间和推荐交通方式。
    """

    def __init__(self):
        super().__init__("route_time")

    def run(
        self,
        from_address: str,
        to_address: str,
    ) -> Dict:
        """
        :param from_address: 出发地点地址
        :param to_address: 目的地地址
        :return: {
            "from_address": str,
            "to_address": str,
            "duration_minutes": int,      # 路程时长（分钟）
            "distance_km": float,         # 估算距离（公里）
            "transport": str,             # 推荐交通方式：步行/骑行/地铁/打车
            "transport_icon": str,        # 交通方式 emoji
            "same_district": bool,        # 是否同一区
            "summary": str,               # 自然语言描述
        }
        """
        from_district = _extract_district(from_address)
        to_district = _extract_district(to_address)

        # 提取路名判断是否同一区域（更精细的同区位判断）
        from_street = _extract_street(from_address)
        to_street = _extract_street(to_address)
        same_street = (
            from_street and to_street
            and from_street == to_street
        )

        # 判断同一区
        same_district = (
            from_district and to_district
            and from_district == to_district
        )

        if same_street:
            # 同一条路 → 步行
            minutes = random.randint(5, 15)
            distance = round(minutes * 0.08, 1)  # 步行约5km/h
            transport = "步行"
            transport_icon = "🚶"
        elif same_district:
            # 同区不同路 → 骑车或短途打车
            minutes = random.randint(10, 25)
            distance = round(minutes * 0.3, 1)  # 骑车约15km/h
            if minutes <= 15:
                transport = "骑行"
                transport_icon = "🚲"
            else:
                transport = "打车"
                transport_icon = "🚗"
        elif from_district and to_district:
            # 不同区 → 地铁或打车
            minutes = random.randint(25, 50)
            distance = round(minutes * 0.4, 1)  # 市区约25km/h
            if minutes <= 35:
                transport = "地铁"
                transport_icon = "🚇"
            else:
                transport = "打车"
                transport_icon = "🚗"
        else:
            # 无法识别区划，给默认值
            minutes = random.randint(15, 35)
            distance = round(minutes * 0.35, 1)
            transport = "打车"
            transport_icon = "🚗"

        summary = (
            f"  {transport_icon} {from_address} → {to_address}\n"
            f"  交通方式：{transport}\n"
            f"  预计路程：约 {distance} km，{minutes} 分钟"
        )

        return {
            "from_address": from_address,
            "to_address": to_address,
            "duration_minutes": minutes,
            "distance_km": distance,
            "transport": transport,
            "transport_icon": transport_icon,
            "same_district": same_district,
            "summary": summary,
        }
