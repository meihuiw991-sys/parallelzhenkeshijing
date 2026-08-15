import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VisualRouteDecision:
    use_interaction: bool
    reason: str


class VisualIntentRouter:
    _explicit_patterns = (
        r"(?:调用|使用|用).{0,8}(?:interaction|视觉工具|视觉模型|看图工具)",
        r"(?:看一下|看一看|看看|帮我看|你看|请看).{0,12}(?:画面|视频|镜头|眼前|前面|这个|那个|颜色|穿搭|东西)?",
        r"(?:介绍|描述|分析|讲讲).{0,8}(?:视频|画面|镜头|眼前|当前场景|周围环境)",
    )
    _strong_visual_source_terms = (
        "当前画面",
        "画面里",
        "画面中",
        "视频里",
        "视频中",
        "镜头里",
        "镜头中",
        "摄像头里",
        "眼前",
        "面前",
        "当前看到",
        "你看到",
        "我看到",
        "屏幕里",
        "图中",
    )
    _weak_visual_source_terms = ("画面", "视频", "镜头", "摄像头")
    _visual_action_terms = (
        "内容",
        "有什么",
        "是什么",
        "是谁",
        "在哪里",
        "做什么",
        "发生什么",
        "什么颜色",
        "穿什么",
        "看见",
        "看到",
        "描述",
        "介绍",
        "分析",
    )
    _visual_question_terms = (
        "什么颜色",
        "穿什么",
        "穿搭",
        "拿着什么",
        "手里是什么",
        "有几个人",
        "几个人",
        "在哪里",
        "这是哪里",
        "这里是哪",
        "我在哪",
        "正在做什么",
        "发生了什么",
        "长什么样",
        "是什么东西",
        "是什么物体",
        "怎么拆",
        "怎么打开",
    )
    _deictic_terms = ("这个", "那个", "这些", "那些", "他", "她", "它", "前面", "这里", "那里")
    _visual_follow_up_terms = (
        "为什么是",
        "为什么说",
        "怎么会",
        "不对",
        "说错",
        "看错",
        "确定吗",
        "你确定",
        "刚才说",
        "你说",
    )

    def decide(self, transcript: str, has_visual_context: bool = False) -> VisualRouteDecision:
        text = self._normalize(transcript)
        if not text:
            return VisualRouteDecision(False, "empty")

        for pattern in self._explicit_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return VisualRouteDecision(True, "explicit_visual_request")

        if any(term in text for term in self._strong_visual_source_terms):
            return VisualRouteDecision(True, "visual_source_reference")

        has_weak_source = any(term in text for term in self._weak_visual_source_terms)
        has_visual_action = any(term in text for term in self._visual_action_terms)
        if has_weak_source and has_visual_action:
            return VisualRouteDecision(True, "visual_content_question")

        has_visual_question = any(term in text for term in self._visual_question_terms)
        has_deictic_reference = any(term in text for term in self._deictic_terms)
        if has_visual_question and (has_deictic_reference or has_visual_context):
            return VisualRouteDecision(True, "visual_attribute_question")

        if has_visual_context and has_deictic_reference and len(text) <= 24:
            return VisualRouteDecision(True, "visual_follow_up")

        if has_visual_context and any(term in text for term in self._visual_follow_up_terms):
            return VisualRouteDecision(True, "visual_result_follow_up")

        return VisualRouteDecision(False, "general_conversation")

    @staticmethod
    def _normalize(transcript: str) -> str:
        return re.sub(r"[\s，。！？、,.!?]", "", transcript).lower()
