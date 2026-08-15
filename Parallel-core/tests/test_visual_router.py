from app.visual_router import VisualIntentRouter


router = VisualIntentRouter()


def test_routes_explicit_video_question_to_interaction() -> None:
    decision = router.decide("请你介绍一下视频的内容")

    assert decision.use_interaction is True
    assert decision.reason == "explicit_visual_request"


def test_routes_current_color_question_to_interaction() -> None:
    assert router.decide("你看一下这个东西是什么颜色").use_interaction is True


def test_routes_explicit_tool_request_to_interaction() -> None:
    assert router.decide("调用 interaction 帮我看看眼前是什么").use_interaction is True


def test_routes_general_knowledge_to_talker() -> None:
    assert router.decide("蓝色和什么颜色比较搭配").use_interaction is False


def test_video_product_capability_question_stays_with_talker() -> None:
    assert router.decide("他没有录屏功能吗，那怎么显示视频呢").use_interaction is False


def test_bare_video_technology_question_stays_with_talker() -> None:
    assert router.decide("视频编码应该怎么设计").use_interaction is False


def test_routes_visual_follow_up_with_context() -> None:
    assert router.decide("它是做什么用的", has_visual_context=True).use_interaction is True


def test_routes_visual_result_correction_with_context() -> None:
    decision = router.decide("而且为什么是说两个人呢", has_visual_context=True)

    assert decision.use_interaction is True
    assert decision.reason == "visual_result_follow_up"


def test_ambiguous_question_without_context_stays_with_talker() -> None:
    assert router.decide("怎么拆开呢", has_visual_context=False).use_interaction is False
