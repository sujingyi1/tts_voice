# -*- coding: utf-8 -*-
import asyncio
import base64
import os
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain, Record
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

VOICE_ALIASES = {
    "女声": "loongstella",
    "温柔": "loongstella",
    "御姐": "longxiaochun",
    "萝莉": "longwan",
    "少女": "longwan",
    "男声": "longchen",
    "少年": "longxiao",
    "大叔": "longchen",
    "气泡音": "longjing",
}


@register(
    "tts_voice",
    "苏静怡",
    "随心而语·语音",
    "1.0.0",
    "https://github.com/your-repo/astrbot_plugin_tts_voice",
)
class TtsVoicePlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.mode = str(self.config.get("tts_mode", "auto"))
        self.api_key = str(self.config.get("dashscope_api_key", "") or "")
        self.model = str(self.config.get("dashscope_model", "cosyvoice-v1"))
        self.voice = str(self.config.get("dashscope_voice", "loongstella"))
        self.timeout_ms = float(self.config.get("timeout", 30) or 30) * 1000
        self.temp_dir = Path(get_astrbot_temp_path())
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._pending_tasks = []

    # ------------------------------------------------------------------
    # LLM 工具: bot 可任意调用
    # ------------------------------------------------------------------
    @filter.llm_tool(name="speak_voice")
    async def speak_voice(self, event: AstrMessageEvent, text: str = "", voice: str = "") -> str:
        """把一段话转成语音消息(语音条)发送给用户。当你想用声音表达情绪、念出某句话、或用户要求你'说话/语音回复'时调用此工具。调用后无需再输出重复的文字。

        Args:
            text (string): 要说的话(语音内容), 必填。
            voice (string): 音色, 可选。支持: 女声/温柔/御姐/萝莉/少女/男声/少年/气泡音, 或直接填 dashscope 音色名(如 longxiaochun)。
        """
        text = (text or "").strip()
        if not text:
            return "[TOOL_FAILED] text 参数不能为空"
        task = asyncio.create_task(self._speak(event, text, voice))
        self._pending_tasks.append(task)
        task.add_done_callback(lambda t: self._pending_tasks.remove(t) if t in self._pending_tasks else None)
        return "[TOOL_STARTED] 正在合成语音, 稍后发送..."

    async def _speak(self, event: AstrMessageEvent, text: str, voice: str):
        try:
            path = await self._synthesize(text, voice)
            if not path or not Path(path).exists():
                try:
                    await event.send(event.chain_result([Plain("[语音] 合成失败, 请稍后再试或检查 TTS 配置")]))
                except Exception:
                    pass
                return
            try:
                await event.send(event.chain_result([Record.fromFileSystem(path)]))
                logger.info(f"[tts_voice] 已发送语音: {path}")
            except Exception as e:
                logger.error(f"[tts_voice] 发送语音失败: {e}")
        except Exception as e:
            logger.error(f"[tts_voice] 语音任务异常: {e}")

    # ------------------------------------------------------------------
    # 合成
    # ------------------------------------------------------------------
    async def _synthesize(self, text: str, voice: str) -> Optional[str]:
        if self.mode in ("auto", "provider"):
            path = await self._try_provider(text)
            if path:
                return path
            if self.mode == "provider":
                logger.warning("[tts_voice] 未找到可用 TTS provider")
                return None
        if self.mode in ("auto", "dashscope"):
            if not self.api_key:
                logger.warning("[tts_voice] 未配置 dashscope_api_key, 无法直连")
                return None
            return await self._synthesize_dashscope(text, voice)
        return None

    async def _try_provider(self, text: str) -> Optional[str]:
        try:
            providers = self.context.get_all_tts_providers()
        except Exception as e:
            logger.debug(f"[tts_voice] get_all_tts_providers failed: {e}")
            return None
        for prov in providers:
            try:
                if not hasattr(prov, "get_audio"):
                    continue
                path = await prov.get_audio(text)
                if path and Path(str(path)).exists():
                    logger.info(f"[tts_voice] 使用 AstrBot TTS provider {prov.get_model()} 合成")
                    return str(path)
            except Exception as e:
                logger.warning(f"[tts_voice] provider 合成失败: {e}")
        return None

    # ------------------------------------------------------------------
    # DashScope 直连
    # ------------------------------------------------------------------
    def _is_qwen_tts(self, model: str) -> bool:
        m = model.lower()
        return "tts" in m and m.startswith("qwen")

    def _resolve_voice(self, voice: str) -> str:
        voice = (voice or "").strip()
        if not voice:
            return self.voice
        return VOICE_ALIASES.get(voice, voice)

    async def _synthesize_dashscope(self, text: str, voice: str) -> Optional[str]:
        import dashscope
        dashscope.api_key = self.api_key
        voice = self._resolve_voice(voice)
        try:
            if self._is_qwen_tts(self.model):
                audio_bytes, ext = await self._synth_qwen(text, voice)
            else:
                audio_bytes, ext = await self._synth_cosyvoice(text, voice)
            if not audio_bytes:
                logger.error("[tts_voice] dashscope 合成返回为空")
                return None
            path = os.path.join(str(self.temp_dir), f"tts_{uuid.uuid4().hex[:8]}{ext}")
            Path(path).write_bytes(audio_bytes)
            return path
        except Exception as e:
            logger.error(f"[tts_voice] dashscope 合成异常: {e}")
            return None

    async def _synth_cosyvoice(self, text: str, voice: str):
        from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

        synthesizer = SpeechSynthesizer(
            model=self.model,
            voice=voice,
            format=AudioFormat.WAV_24000HZ_MONO_16BIT,
        )
        audio_bytes = await asyncio.to_thread(synthesizer.call, text, self.timeout_ms)
        if not audio_bytes:
            resp = synthesizer.get_response()
            if resp and isinstance(resp, dict):
                raise RuntimeError(str(resp)[:300])
        return audio_bytes, ".wav"

    async def _synth_qwen(self, text: str, voice: str):
        try:
            from dashscope.aigc.multimodal_conversation import MultiModalConversation
        except ImportError as e:
            raise RuntimeError("dashscope SDK 缺少 MultiModalConversation, 请升级 dashscope") from e

        def call():
            return MultiModalConversation.call(
                model=self.model,
                messages=None,
                api_key=self.api_key,
                voice=voice or "Cherry",
                text=text,
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, call)
        output = getattr(response, "output", None)
        audio_obj = getattr(output, "audio", None) if output is not None else None
        if not audio_obj:
            return None, ".wav"
        data_b64 = getattr(audio_obj, "data", None)
        if data_b64:
            try:
                return base64.b64decode(data_b64), ".wav"
            except Exception as e:
                logger.error(f"[tts_voice] qwen tts base64 解码失败: {e}")
        url = getattr(audio_obj, "url", None)
        if url:
            try:
                timeout = aiohttp.ClientTimeout(total=max(self.timeout_ms / 1000, 10))
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.read(), ".wav"
                        logger.warning(f"[tts_voice] 下载音频失败 HTTP {resp.status}")
            except Exception as e:
                logger.error(f"[tts_voice] 下载音频异常: {e}")
        return None, ".wav"

    # ------------------------------------------------------------------
    # 命令
    # ------------------------------------------------------------------
    @filter.command("语音状态")
    async def cmd_status(self, event: AstrMessageEvent):
        lines = ["[随心而语·语音]"]
        lines.append(f"模式: {self.mode}")
        lines.append(f"模型: {self.model} | 音色: {self.voice}")
        try:
            providers = self.context.get_all_tts_providers()
            lines.append(f"可用 TTS provider: {len(providers)} 个")
            for p in providers:
                lines.append(f"  - {p.get_model()}")
        except Exception:
            lines.append("可用 TTS provider: 获取失败")
        yield event.chain_result([Plain("\n".join(lines))])

    @filter.command("语音测试")
    async def cmd_test(self, event: AstrMessageEvent, text: str = ""):
        if not text:
            yield event.chain_result([Plain("用法: /语音测试 <要说的内容>")])
            return
        path = await self._synthesize(text, "")
        if not path:
            yield event.chain_result([Plain("[语音] 合成失败, 检查配置与 api_key")])
            return
        yield event.chain_result([Record.fromFileSystem(path)])

    async def terminate(self):
        for t in self._pending_tasks:
            t.cancel()
        for t in self._pending_tasks:
            try:
                await t
            except Exception:
                pass
        self._pending_tasks.clear()
