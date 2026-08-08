# 随心而语·语音 (tts_voice)

作者: 苏静怡

注册 `speak_voice` LLM 工具, bot 可**任意调用**——把文本转成语音消息(语音条)发送给用户。兼容 **dashscope_tts**(阿里云百炼 CosyVoice / Qwen-TTS),也可复用 AstrBot 已配置的 TTS provider。

## 工作原理

```
LLM 调用 speak_voice(text, voice)
  → 合成(优先复用 AstrBot TTS provider, 否则 DashScope 直连)
  → 生成 .wav 临时文件
  → 异步发送语音消息(Record)
  → 工具返回, 不阻塞 LLM 回复
```

## 安装

1. 将 `astrbot_plugin_tts_voice` 放入 AstrBot `data/plugins/`
2. 安装依赖: `pip install dashscope aiohttp`(或重载插件让 AstrBot 自动装)
3. 管理面板配置:
   - `tts_mode`: `auto`(默认)/ `provider` / `dashscope`
   - 直连模式需填 `dashscope_api_key`(阿里云百炼 DashScope 的 API Key)

## 配置

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `tts_mode` | `auto` | `auto`=优先 provider, 没有则 dashscope 直连; `provider`=只用 AstrBot 已配置的 TTS; `dashscope`=只用直连 |
| `dashscope_api_key` | 空 | DashScope API Key(直连用) |
| `dashscope_model` | `cosyvoice-v1` | 模型, 也支持 `qwen-tts-flash` / `qwen2.5-tts` |
| `dashscope_voice` | `loongstella` | 默认音色 |
| `timeout` | `30` | 合成超时(秒) |

## 音色

LLM 工具的 `voice` 参数支持中文别名: 女声/温柔/御姐/萝莉/少女/男声/少年/气泡音, 或直接填 dashscope 音色名(loongstella、longxiaochun、longwan、longchen、longxiao、longjing 等)。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/语音状态` | 查看模式/模型/音色/可用 provider |
| `/语音测试 <文本>` | 手动合成并发送语音 |

## 说明

- 优先复用 AstrBot 已配置的 TTS provider(如 dashscope_tts), 无需重复填 key; `auto` 模式下无 provider 且未配直连 key 时会提示失败
- 语音合成在后台异步进行, 不影响 LLM 回复速度
- 临时音频保存在 AstrBot temp 目录
