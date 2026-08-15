# 演示 Mock 说明

## 1. 文件位置

所有演示固定问答集中在：

```text
app/demo_mocks.py
```

## 2. Interaction Mock

触发问句：

```text
请介绍眼前的景点
```

行为：

1. 仍按视觉问题路由。
2. 不调用真实 Interaction API。
3. 固定文案显示在右下角视觉解析卡片。
4. 固定文案显示在中央字幕。
5. 固定文案交给 JoyAI Voice `tts_text` 朗读。

后端日志：

```text
Interaction demo mock matched
```

## 3. Talker Mock

触发问句：

```text
项羽有什么典故
```

行为：

1. 使用 Talker 的 ASR 获取完整用户文本。
2. 取消 Talker 自动生成的回答。
3. 固定文案显示在中央字幕。
4. 固定文案交给 JoyAI Voice `tts_text` 朗读。

后端日志：

```text
Talker demo mock matched
```

## 4. 匹配规则

匹配时会忽略：

- 空格
- 中文逗号、句号、问号、感叹号、顿号和冒号
- 对应英文标点

除此之外要求完整文本一致。其他问题不会被 Mock 截获，仍调用真实模型。

## 5. 修改方式

修改以下常量：

```python
INTERACTION_TRIGGER = "..."
INTERACTION_RESPONSE = "..."
TALKER_TRIGGER = "..."
TALKER_RESPONSE = "..."
```

修改后运行：

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

相关测试位于：

```text
tests/test_demo_mocks.py
tests/test_assistant_visual_route.py
```
