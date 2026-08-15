import re


INTERACTION_TRIGGER = "请介绍眼前的景点"
INTERACTION_RESPONSE = (
    "项王故居位于项王故里景区核心区域，是项羽出生和少年时期生活的地方，距今已有2200余年历史。"
    "故居整体为仿汉式建筑群，古朴庄重，青砖黛瓦间透出楚地民居的敦厚气息。"
    "院落内有项羽亲手植下的古槐，相传树龄已逾两千年，至今仍枝繁叶茂，被视为项王故里的“镇园之宝”；"
    "另有乌骓马亭，纪念陪伴项羽征战一生的坐骑。"
    "故居正堂内陈列着项氏宗谱、秦汉时期的兵甲器物及相关史料，还原了项羽从将门之后到起兵反秦的成长轨迹。"
    "这方院落不仅是项羽生命的起点，更是那个“彼可取而代也”的少年豪言发出的地方——"
    "两千多年过去，梧桐巷里的风声，似乎仍在诉说着这位悲情英雄的传奇开端。"
)

TALKER_TRIGGER = "项羽有什么典故"
TALKER_RESPONSE = (
    "项羽一生留下诸多脍炙人口的典故：少年时见秦始皇出游，脱口而出“彼可取而代也”，豪气已露峥嵘；"
    "公元前207年巨鹿之战，他率军破釜沉舟，大败秦军主力，一战成名；"
    "公元前206年入关后，于鸿门宴上放走刘邦，留下“项庄舞剑，意在沛公”的千古警示；"
    "此后楚汉相争，韩信以四面楚歌之计瓦解楚军士气；"
    "公元前202年，项羽兵困垓下，与虞姬诀别，上演霸王别姬的千古悲歌；"
    "突围至乌江岸边，他本可渡江逃生，却以“无颜见江东父老”为由拒绝，自刎而死——"
    "这些典故串联起来，正是一个力能扛鼎却最终失天下的悲剧英雄的完整肖像，"
    "其勇武、刚愎与气节，至今仍令人唏嘘不已。"
)


def normalize_trigger(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:]", "", text)


def interaction_mock(text: str) -> str | None:
    if normalize_trigger(text) == normalize_trigger(INTERACTION_TRIGGER):
        return INTERACTION_RESPONSE
    return None


def talker_mock(text: str) -> str | None:
    if normalize_trigger(text) == normalize_trigger(TALKER_TRIGGER):
        return TALKER_RESPONSE
    return None
