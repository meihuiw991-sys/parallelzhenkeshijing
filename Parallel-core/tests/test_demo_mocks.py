from app.demo_mocks import (
    INTERACTION_RESPONSE,
    TALKER_RESPONSE,
    interaction_mock,
    talker_mock,
)


def test_interaction_mock_matches_target_question() -> None:
    assert interaction_mock("请介绍眼前的景点。") == INTERACTION_RESPONSE


def test_interaction_mock_does_not_affect_other_visual_questions() -> None:
    assert interaction_mock("请介绍眼前的人物") is None


def test_talker_mock_matches_target_question() -> None:
    assert talker_mock("项羽有什么典故？") == TALKER_RESPONSE


def test_talker_mock_does_not_affect_other_questions() -> None:
    assert talker_mock("项羽为什么失败") is None
