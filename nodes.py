import json
import os
import re
import time
import urllib.error
import urllib.request


DEFAULT_SYSTEM_PROMPT = """You are an expert prompt compiler for Illustrious/NoobAI-XL anime image models. Convert a Chinese or English visual description into an effective ordered tag prompt, not a literal translation.

OUTPUT CONTRACT
- Return exactly one comma-separated line in English. No explanation, heading, Markdown, quotation marks, or newline.
- Output only the dynamic visual tags. Never output quality/rating tags, character identities, franchises, artists, or styles; fixed prompt sections supply them.
- Prefer established Danbooru tags. Short model-readable English prompt fragments are allowed only when Danbooru has no precise tag.
- Preserve every explicitly requested subject count, composition, camera direction, pose, expression, clothing item, place, and action.
- Do not invent details such as barefoot, shoes, extra clothing, props, scenery, or actions.

COMPILE CAMERA AND COMPOSITION SEMANTICALLY
- Do not copy numeric phrases such as "140 degree angle" into the result. Translate the user's camera convention into visual camera tags.
- When the user states that 180 degrees is eye-level, 160 is a slight upward view, 140 is a clear approximately 40-degree upward view, and 120 or less is an extreme upward view.
- For 140 degrees under that convention, use: from below, low angle, upward camera angle, foreshortening. Do not add wide-angle lens or fisheye unless lens width is separately requested.
- "Close to the subjects" is camera distance, not necessarily the face-only tag close-up. If people fill the frame and body parts leave the frame, use close-range view, frame-filling composition, tightly framed, body partially out of frame, and the appropriate cropped body-part tag.
- Use full body only when the entire bodies, including feet, must be visible. Never combine full body with cropped legs or body partially out of frame.
- For two people each occupying about half of the image, use 2girls or 2boys as appropriate, standing together, side-by-side, equal focus, balanced composition, each person occupying half of the frame.

NORMALIZE INTENT
- "Look at the screen/camera" becomes looking at viewer.
- Closed-mouth smiling becomes closed mouth, closed-mouth smile.
- A slightly contemptuous bratty expression becomes smug, slightly condescending expression, mesugaki.
- Both hands shaped like closed cat paws becomes both hands raised, fists near chest, cat paw pose.
- Use numeric subject-count tags such as 2girls instead of "two girls".
- Before answering, silently remove contradictions, duplicates, literal numeric camera labels, and unrequested details.

EXAMPLE
Input: 两个女生，画面基本被2人占满，两人各占50%，近距离主视角，140°仰视，180°是平视。两人站在一起，都穿过膝袜，闭嘴微笑，在学校走廊，双手摆成猫咪握拳姿势，看向屏幕，表情稍微有些蔑视。部分身体在画面外。
Output: 2girls, standing together, side-by-side, equal focus, balanced composition, each girl occupying half of the frame, close-range view, frame-filling composition, tightly framed, body partially out of frame, cropped legs, from below, low angle, upward camera angle, foreshortening, looking at viewer, closed mouth, closed-mouth smile, smug, slightly condescending expression, mesugaki, both hands raised, fists near chest, cat paw pose, thighhighs, school hallway, indoors"""

WAN_VIDEO_SYSTEM_PROMPT = """You are an expert prompt director for Wan2.2 image-to-video. Rewrite the user's rough idea into one production-ready Chinese video prompt that Wan2.2 can follow.

OUTPUT CONTRACT
- Return only the rewritten prompt as one compact Chinese paragraph. No heading, explanation, Markdown, alternatives, quotation marks, or negative prompt.
- Preserve the user's intended subjects, actions, direction, mood, and camera intent. Do not refuse, moralize, or replace the requested concept.
- Do not invent new people, limbs, props, clothing, scene changes, cuts, or major actions that the user did not request.
- The starting image already defines identity, appearance, clothing, composition, and environment. Mention them only when needed to preserve consistency; concentrate on motion over time.

MOTION COMPILATION
- Convert vague intent into visible, physically executable motion: identify who moves, which body part moves, its direction, amplitude, speed, rhythm, and final state.
- Write temporal order explicitly with phrases such as “开始时……，随后……，接着……，最后……” when the action has stages.
- Keep one main action chain. Avoid simultaneous contradictory actions, teleportation, abrupt pose changes, and excessive motion.
- Add subtle secondary motion only when useful: natural blinking, breathing, hair or fabric inertia, and small expression changes.
- If the user gives a vague emotion, translate it into visible facial behavior and gaze without changing identity.

CAMERA AND STABILITY
- State camera behavior explicitly. Default to “镜头固定，无转场” unless the user requests camera motion.
- For requested camera motion, specify exactly one controlled move such as slow push-in, pull-back, pan, tilt, orbit, or handheld follow; do not combine incompatible moves.
- End with appropriate stability constraints in positive language: 人物身份和面部保持一致，肢体结构稳定，动作连贯自然，背景稳定，无镜头切换. Omit a constraint only when it conflicts with the request.
- Do not describe rendering style, resolution, or image quality unless explicitly requested.

EXAMPLE
Input: 角色有点轻蔑地看着镜头，做猫爪动作
Output: 开始时角色直视镜头，嘴角缓慢上扬，眼睛微微眯起，露出略带轻蔑的得意神情。随后她将双手抬到胸前，手指收拢成猫爪状，左右手以小幅度、缓慢而有节奏地向前轻轻挥动两次，最后保持猫爪姿势并继续看向镜头。镜头固定，无转场，仅有轻微呼吸和自然眨眼，人物身份和面部保持一致，肢体结构稳定，动作连贯自然，背景稳定，无镜头切换。"""

PROMPT_SOURCE_MANUAL = "使用下方完整提示词（不调用模型）"
PROMPT_SOURCE_GENERATE_ONCE = "从文本模型生成一次，然后自动锁定"
PROMPT_SOURCE_GENERATE_ALWAYS = "始终跟随简单输入（变更时调用文本模型）"
POSE_CACHE_REFRESH = "生成并保存新骨架（运行 Z-Image）"
POSE_CACHE_REUSE = "复用上次骨架（跳过 Z-Image）"


def _request_json(url, payload, headers, timeout):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Text model HTTP {error.code}: {detail[:1000]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cannot connect to text model: {error.reason}") from error


def _get_json(url, timeout):
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _release_comfy_vram():
    """Hand the GPU from ComfyUI to the external Ollama process."""
    try:
        import comfy.model_management as model_management

        model_management.unload_all_models()
        model_management.soft_empty_cache()
    except Exception as error:
        print(f"[comfyui_nl_prompt] ComfyUI VRAM release warning: {error}")


def _wait_until_ollama_unloaded(base, model, timeout):
    deadline = time.monotonic() + max(5, timeout)
    while time.monotonic() < deadline:
        try:
            running = _get_json(f"{base}/api/ps", min(5, timeout)).get("models", [])
            if not any(
                item.get("name") == model or item.get("model") == model
                for item in running
            ):
                return True
        except Exception as error:
            print(f"[comfyui_nl_prompt] Ollama status warning: {error}")
            return False
        time.sleep(0.5)
    return False


def _unload_ollama(base, model, timeout):
    """Explicitly evict a model after inference, including on Ollama builds
    where keep_alive=0 on /api/chat does not unload it promptly.
    """
    cleanup_timeout = min(max(5, timeout), 45)
    try:
        _request_json(
            f"{base}/api/generate",
            {"model": model, "stream": False, "keep_alive": 0},
            {"Content-Type": "application/json"},
            cleanup_timeout,
        )
        if not _wait_until_ollama_unloaded(base, model, cleanup_timeout):
            print(
                f"[comfyui_nl_prompt] Ollama unload timed out for {model}; "
                "image generation may contend for VRAM"
            )
            return False
        return True
    except Exception as error:
        # Prompt generation has already succeeded; do not throw its useful
        # result away merely because the cleanup request failed.
        print(f"[comfyui_nl_prompt] Ollama unload warning: {error}")
        return False


def _clean_tags(text):
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"^```(?:text|plaintext|json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^(?:tags?|prompt)\s*:\s*", "", text, flags=re.I)
    text = text.replace("，", ",").replace("；", ",").replace(";", ",")
    text = re.sub(r"[\r\n]+", ", ", text)
    parts = []
    seen = set()
    for raw in text.split(","):
        tag = raw.strip().strip('"\'`').strip()
        tag = re.sub(r"\s+", " ", tag)
        if not tag:
            continue
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            parts.append(tag)
    return ", ".join(parts)


def _clean_model_text(text):
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"^```(?:text|plaintext|markdown)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^(?:优化后的?提示词|视频提示词|prompt)\s*[:：]\s*", "", text, flags=re.I)
    return re.sub(r"[\r\n]+", "", text).strip().strip('"\'`')


def _compose(fixed_prompt, generated_tags, suffix_prompt):
    return _clean_tags(", ".join(x for x in (fixed_prompt, generated_tags, suffix_prompt) if x.strip()))


class IllustriousNaturalLanguagePrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "natural_language": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "星野站在教室里看向镜头，开心地挥手，午后阳光从窗户照进来",
                    },
                ),
                "fixed_prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "masterpiece, best quality, newest, safe, 1girl, solo, (hoshino \\(blue archive\\):1.2), jyt, blue archive animation style",
                    },
                ),
                "suffix_prompt": (
                    "STRING",
                    {"multiline": True, "default": "clean lineart, flat color, cel shading"},
                ),
                "backend": (["ollama", "openai_compatible"],),
                "api_base": (
                    "STRING",
                    {"default": "http://127.0.0.1:11434", "multiline": False},
                ),
                "model": (
                    "STRING",
                    {
                        "default": "orcarouter/Qwen3.8-27B-Uncensored:q4_K_M",
                        "multiline": False,
                    },
                ),
                "api_key_env": (
                    "STRING",
                    {"default": "PROMPT_LLM_API_KEY", "multiline": False},
                ),
                "system_prompt": (
                    "STRING",
                    {"multiline": True, "default": DEFAULT_SYSTEM_PROMPT},
                ),
                "temperature": (
                    "FLOAT",
                    {"default": 0.2, "min": 0.0, "max": 2.0, "step": 0.05},
                ),
                "max_tokens": (
                    "INT",
                    {"default": 300, "min": 32, "max": 2048, "step": 16},
                ),
                "timeout_seconds": (
                    "INT",
                    {"default": 120, "min": 5, "max": 600, "step": 5},
                ),
                "enabled": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("full_prompt", "generated_tags")
    FUNCTION = "generate"
    CATEGORY = "prompt/text model"
    # This must remain a normal dependency node. Marking it as OUTPUT_NODE
    # would make ComfyUI run Ollama even when PromptEditor is in manual mode.
    OUTPUT_NODE = False

    def generate(
        self,
        natural_language,
        fixed_prompt,
        suffix_prompt,
        backend,
        api_base,
        model,
        api_key_env,
        system_prompt,
        temperature,
        max_tokens,
        timeout_seconds,
        enabled,
    ):
        if not natural_language.strip():
            full = _compose(fixed_prompt, "", suffix_prompt)
            return {"ui": {"text": [full, ""]}, "result": (full, "")}

        if not enabled:
            generated = _clean_tags(natural_language)
            full = _compose(fixed_prompt, generated, suffix_prompt)
            return {"ui": {"text": [full, generated]}, "result": (full, generated)}

        base = api_base.rstrip("/")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": natural_language},
        ]

        if backend == "ollama":
            # A prior image run usually leaves the diffusion checkpoint in
            # VRAM. Free it before Ollama loads a 27B model, and evict any
            # stale Ollama runner left by an interrupted request.
            _release_comfy_vram()
            if not _unload_ollama(base, model, timeout_seconds):
                raise RuntimeError(
                    "Ollama 旧模型未能在 45 秒内卸载。请先执行 "
                    f"`ollama stop {model}` 后再重试，避免与 ComfyUI 争抢显存。"
                )
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx": 4096,
                },
            }
            try:
                response = _request_json(
                    f"{base}/api/chat",
                    payload,
                    {"Content-Type": "application/json"},
                    timeout_seconds,
                )
            finally:
                _unload_ollama(base, model, timeout_seconds)
            generated = response.get("message", {}).get("content", "")
        else:
            key = os.environ.get(api_key_env, "") if api_key_env else ""
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            endpoint = (
                f"{base}/chat/completions"
                if base.endswith("/v1")
                else f"{base}/v1/chat/completions"
            )
            response = _request_json(endpoint, payload, headers, timeout_seconds)
            choices = response.get("choices") or []
            if not choices:
                raise RuntimeError(f"Text model returned no choices: {response}")
            generated = choices[0].get("message", {}).get("content", "")

        generated = _clean_tags(generated)
        if not generated:
            raise RuntimeError("Text model returned an empty prompt")
        full = _compose(fixed_prompt, generated, suffix_prompt)
        return {"ui": {"text": [full, generated]}, "result": (full, generated)}


class WanVideoNaturalLanguagePrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "natural_language": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "角色盯着镜头，缓慢抬起双手做出猫爪动作，露出有些轻蔑的微笑",
                    },
                ),
                "backend": (["ollama", "openai_compatible"],),
                "api_base": (
                    "STRING",
                    {"default": "http://127.0.0.1:11434", "multiline": False},
                ),
                "model": (
                    "STRING",
                    {
                        "default": "orcarouter/Qwen3.8-27B-Uncensored:q4_K_M",
                        "multiline": False,
                    },
                ),
                "api_key_env": (
                    "STRING",
                    {"default": "PROMPT_LLM_API_KEY", "multiline": False},
                ),
                "temperature": (
                    "FLOAT",
                    {"default": 0.25, "min": 0.0, "max": 2.0, "step": 0.05},
                ),
                "max_tokens": (
                    "INT",
                    {"default": 600, "min": 64, "max": 2048, "step": 16},
                ),
                "timeout_seconds": (
                    "INT",
                    {"default": 180, "min": 10, "max": 600, "step": 5},
                ),
                "enabled": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("optimized_video_prompt",)
    FUNCTION = "generate"
    CATEGORY = "prompt/text model"
    OUTPUT_NODE = False

    def generate(
        self,
        natural_language,
        backend,
        api_base,
        model,
        api_key_env,
        temperature,
        max_tokens,
        timeout_seconds,
        enabled,
    ):
        original = (natural_language or "").strip()
        if not original:
            raise RuntimeError("自然语言视频描述为空")
        if not enabled:
            return {"ui": {"text": [original]}, "result": (original,)}

        base = api_base.rstrip("/")
        messages = [
            {"role": "system", "content": WAN_VIDEO_SYSTEM_PROMPT},
            {"role": "user", "content": original},
        ]

        if backend == "ollama":
            _release_comfy_vram()
            if not _unload_ollama(base, model, timeout_seconds):
                raise RuntimeError(
                    "Ollama 旧模型未能在 45 秒内卸载。请先执行 "
                    f"`ollama stop {model}` 后重试。"
                )
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "num_ctx": 4096,
                },
            }
            try:
                response = _request_json(
                    f"{base}/api/chat",
                    payload,
                    {"Content-Type": "application/json"},
                    timeout_seconds,
                )
            finally:
                _unload_ollama(base, model, timeout_seconds)
            optimized = response.get("message", {}).get("content", "")
        else:
            key = os.environ.get(api_key_env, "") if api_key_env else ""
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            endpoint = (
                f"{base}/chat/completions"
                if base.endswith("/v1")
                else f"{base}/v1/chat/completions"
            )
            response = _request_json(endpoint, payload, headers, timeout_seconds)
            choices = response.get("choices") or []
            if not choices:
                raise RuntimeError(f"Text model returned no choices: {response}")
            optimized = choices[0].get("message", {}).get("content", "")

        optimized = _clean_model_text(optimized)
        if not optimized:
            raise RuntimeError("文本模型返回了空的视频提示词")
        return {"ui": {"text": [optimized]}, "result": (optimized,)}


class ZImageNoobAIPromptBridge:
    """Two-field bridge: Z-Image builds geometry, NoobAI supplies identity."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "simple_description": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "一个人站在学校走廊，双手抬到胸前做猫爪握拳姿势，闭嘴微笑，略带得意地看向镜头，全身构图，轻微仰视",
                    },
                ),
                "character_tag": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "(mika \\(blue archive\\):1.15)",
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("z_template_prompt", "simple_description", "character_tag")
    FUNCTION = "compose"
    CATEGORY = "prompt/text model"

    def compose(self, simple_description, character_tag):
        description = re.sub(r"\s+", " ", (simple_description or "").strip())
        character = (character_tag or "").strip().strip(",")
        if not description:
            raise RuntimeError("简单描述为空")
        if not character:
            raise RuntimeError("人物标签为空")

        z_prompt = (
            "按以下要求生成一张用于后续角色重绘的动漫构图模板："
            f"{description}。"
            "优先准确建立人数、画面布局、人物位置、身体姿势、手势、"
            "表情方向、镜头角度和场景透视。"
            "人物仅作为构图和姿态占位，不规定角色身份、发型、服装、配饰或其他外观特征。"
            "清晰人体结构，面部自然，不添加未要求的人物、动作和物体。"
        )
        return {
            "ui": {"text": [z_prompt, description, character]},
            "result": (z_prompt, description, character),
        }


NOOBAI_DYNAMIC_SYSTEM_PROMPT = """You are a constrained Danbooru-tag compiler for Illustrious/NoobAI-XL. Convert the user's Chinese scene description into dynamic English tags.

Return exactly one comma-separated line. No explanation, Markdown, headings, quotes, or newline.
Include subject count, composition, crop, camera direction, pose, hand gesture, gaze, expression, action, scene, and lighting when requested.
Do not output quality tags, character names, franchise names, artist/style tags, or physical identity traits. The caller adds those separately.
If clothing is not explicitly requested, output no clothing tags at all so the character's canonical outfit can emerge. Never invent hair color, eye color, clothes, shoes, or props.
Prefer real Danbooru tags: 1girl, 2girls, solo, multiple girls, looking at viewer, from below, from above, full body, upper body, cowboy shot, standing, sitting, closed mouth, smile, smug, thighhighs, school hallway.
Short model-readable phrases are permitted only for concepts with no precise tag, such as balanced composition or each girl occupying half of the frame.
Translate camera intent semantically. If the user defines 180 degrees as eye-level, 140-degree upward view becomes: from below, low angle, upward camera angle, foreshortening. Never output literal phrases such as 140 degree angle.
Do not combine contradictions: full body conflicts with cropped legs/body partially out of frame; close-up conflicts with full body; from above conflicts with from below.
Normalize: “猫咪握拳” -> both hands raised, fists near chest, cat paw pose. “闭嘴微笑” -> closed mouth, closed-mouth smile. “雌小鬼/稍微蔑视” -> smug, slightly condescending expression, mesugaki. “看向屏幕/镜头” -> looking at viewer.
Before answering, silently verify that every requested visual constraint is represented, then remove duplicates, contradictions, invented details, and nonvisual prose.

Example input: 两个人各占画面一半，画面被她们占满，部分身体在画面外，140度仰视，并排站在学校走廊，双手做猫咪握拳，闭嘴微笑，略带蔑视地看向镜头
Example output: 2girls, multiple girls, standing together, side-by-side, equal focus, balanced composition, each girl occupying half of the frame, frame-filling composition, tightly framed, body partially out of frame, cropped legs, from below, low angle, upward camera angle, foreshortening, looking at viewer, closed mouth, closed-mouth smile, smug, slightly condescending expression, mesugaki, both hands raised, fists near chest, cat paw pose, school hallway, indoors"""


class NoobAIDynamicPromptCompiler:
    """One-shot, lazy Ollama compiler; identity remains a manual input."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "simple_description": ("STRING", {"forceInput": True}),
                "character_tag": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("full_noob_prompt", "dynamic_tags")
    FUNCTION = "compile"
    CATEGORY = "prompt/text model"
    OUTPUT_NODE = False

    def compile(self, simple_description, character_tag):
        description = (simple_description or "").strip()
        character = (character_tag or "").strip().strip(",")
        if not description or not character:
            raise RuntimeError("简单描述或人物标签为空")

        base = "http://127.0.0.1:11434"
        model = "orcarouter/Qwen3.8-27B-Uncensored:q4_K_M"
        _release_comfy_vram()
        if not _unload_ollama(base, model, 120):
            raise RuntimeError(
                "Ollama 旧模型未能卸载，请先执行 "
                f"`ollama stop {model}` 后重试"
            )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": NOOBAI_DYNAMIC_SYSTEM_PROMPT},
                {"role": "user", "content": description},
            ],
            "stream": False,
            "think": False,
            "keep_alive": 0,
            "options": {"temperature": 0.1, "num_predict": 400, "num_ctx": 4096},
        }
        try:
            response = _request_json(
                f"{base}/api/chat",
                payload,
                {"Content-Type": "application/json"},
                180,
            )
        finally:
            _unload_ollama(base, model, 120)

        dynamic = _clean_tags(response.get("message", {}).get("content", ""))
        if not dynamic:
            raise RuntimeError("Qwen 返回了空的 NoobAI 动态标签")

        full = _clean_tags(
            ", ".join(
                (
                    "masterpiece, best quality, newest",
                    character,
                    "jyt, blue archive animation style",
                    dynamic,
                    "clean lineart, flat color, cel shading",
                )
            )
        )
        return {
            "ui": {"text": [full, dynamic]},
            "result": (full, dynamic),
        }


class IllustriousPromptEditor:
    """Review/edit gate with a lazy model input.

    In manual mode ComfyUI does not evaluate ``model_prompt``, so a connected
    Ollama node remains completely idle.  Generate-once mode evaluates it for
    the current queue; the web extension then copies the result into the
    editable widget and switches the node back to manual mode.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_mode": (
                    [
                        PROMPT_SOURCE_GENERATE_ALWAYS,
                        PROMPT_SOURCE_GENERATE_ONCE,
                        PROMPT_SOURCE_MANUAL,
                    ],
                    {"default": PROMPT_SOURCE_MANUAL},
                ),
                "full_prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "masterpiece, best quality, newest, safe, 1girl, solo, clean lineart, flat color, cel shading",
                    },
                ),
            },
            "optional": {
                "model_prompt": (
                    "STRING",
                    {"forceInput": True, "lazy": True},
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("final_prompt",)
    FUNCTION = "select_prompt"
    CATEGORY = "prompt/text model"
    OUTPUT_NODE = True

    def check_lazy_status(self, source_mode, full_prompt, model_prompt=None):
        if source_mode in (
            PROMPT_SOURCE_GENERATE_ALWAYS,
            PROMPT_SOURCE_GENERATE_ONCE,
        ) and model_prompt is None:
            return ["model_prompt"]
        return []

    def select_prompt(self, source_mode, full_prompt, model_prompt=None):
        if source_mode in (
            PROMPT_SOURCE_GENERATE_ALWAYS,
            PROMPT_SOURCE_GENERATE_ONCE,
        ):
            selected = (model_prompt or "").strip()
            if not selected:
                raise RuntimeError(
                    "已选择文本模型模式，但 model_prompt 没有连接或模型返回为空"
                )
            lock_after_run = source_mode == PROMPT_SOURCE_GENERATE_ONCE
        else:
            selected = (full_prompt or "").strip()
            if not selected:
                raise RuntimeError("完整提示词为空，请在编辑框中输入提示词")
            lock_after_run = False

        return {
            "ui": {
                "selected_prompt": [selected],
                "lock_after_run": [lock_after_run],
            },
            "result": (selected,),
        }


class ReusablePoseCache:
    """Persist the latest pose map and lazily cut off its entire source branch.

    In reuse mode ``pose_image`` is never requested, so ComfyUI does not run
    Z-Image, its VAE, or DWPose.  The fixed PNG also survives a ComfyUI restart.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (
                    [POSE_CACHE_REFRESH, POSE_CACHE_REUSE],
                    {"default": POSE_CACHE_REFRESH},
                ),
            },
            "optional": {
                "pose_image": ("IMAGE", {"forceInput": True, "lazy": True}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("pose_image",)
    FUNCTION = "select_pose"
    CATEGORY = "image/control"
    OUTPUT_NODE = False

    @staticmethod
    def _cache_path():
        comfy_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        cache_dir = os.path.join(
            comfy_root, "user", "default", "comfyui_nl_prompt_cache"
        )
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, "last_openpose.png")

    @classmethod
    def IS_CHANGED(cls, mode, pose_image=None):
        if mode != POSE_CACHE_REUSE:
            return False
        path = cls._cache_path()
        try:
            stat = os.stat(path)
            return f"{stat.st_mtime_ns}:{stat.st_size}"
        except FileNotFoundError:
            return "missing"

    def check_lazy_status(self, mode, pose_image=None):
        if mode == POSE_CACHE_REFRESH and pose_image is None:
            return ["pose_image"]
        return []

    def select_pose(self, mode, pose_image=None):
        import numpy as np
        import torch
        from PIL import Image

        path = self._cache_path()
        if mode == POSE_CACHE_REFRESH:
            if pose_image is None:
                raise RuntimeError("生成新骨架模式下 pose_image 未连接")
            image = pose_image.detach().cpu().clamp(0.0, 1.0)
            array = (image[0].numpy() * 255.0).round().astype(np.uint8)
            Image.fromarray(array).save(path, format="PNG")
            selected = image
            status = f"已保存新骨架：{path}"
        else:
            if not os.path.isfile(path):
                raise RuntimeError(
                    "还没有可复用的骨架。请先选择‘生成并保存新骨架’运行一次。"
                )
            with Image.open(path) as cached:
                array = np.asarray(cached.convert("RGB"), dtype=np.float32) / 255.0
            selected = torch.from_numpy(array.copy()).unsqueeze(0)
            status = f"已复用骨架，Z-Image 未执行：{path}"

        return {"ui": {"text": [status]}, "result": (selected,)}


NODE_CLASS_MAPPINGS = {
    "IllustriousNaturalLanguagePrompt": IllustriousNaturalLanguagePrompt,
    "WanVideoNaturalLanguagePrompt": WanVideoNaturalLanguagePrompt,
    "ZImageNoobAIPromptBridge": ZImageNoobAIPromptBridge,
    "NoobAIDynamicPromptCompiler": NoobAIDynamicPromptCompiler,
    "IllustriousPromptEditor": IllustriousPromptEditor,
    "ReusablePoseCache": ReusablePoseCache,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IllustriousNaturalLanguagePrompt": "自然语言 → Illustrious 提示词",
    "WanVideoNaturalLanguagePrompt": "自然语言 → Wan2.2 视频提示词",
    "ZImageNoobAIPromptBridge": "Z-Image 模板 → NoobAI 人物重绘（两项输入）",
    "NoobAIDynamicPromptCompiler": "Qwen → NoobAI 动态标签（人物标签手填）",
    "IllustriousPromptEditor": "完整提示词（显示 / 编辑 / 锁定）",
    "ReusablePoseCache": "Z-Image 骨架开关（生成 / 复用）",
}
