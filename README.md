# ComfyUI Z-Image → NoobAI Bridge

用自然语言描述画面：Z-Image 负责构图和姿势，DWPose 提取骨架，NoobAI/Illustrious 负责角色与平涂画风，最后使用 RealESRGAN 做 2× 超分。

## 安装

在 ComfyUI 的 `custom_nodes` 目录执行：

```powershell
git clone https://github.com/RicterZ/ComfyUI-ZImage-NoobAI-Bridge.git
```

再通过 ComfyUI 扩展管理安装 `comfyui_controlnet_aux`。

重启 ComfyUI，加载：

```text
example_workflows/z-image-openpose-noobai-flat-2x.json
```

## 模型文件

以下路径均相对于 ComfyUI 根目录。`comfyui_controlnet_aux` 自动管理的 DWPose 文件无需手动准备。

| 文件名 | 放置目录 |
| --- | --- |
| `z_image_turbo_fp8_e4m3fn.safetensors` | `models\diffusion_models` |
| `qwen_3_4b.safetensors` | `models\text_encoders` |
| `ae.safetensors` | `models\vae` |
| `zukiNewCuteILL_newV20.safetensors` | `models\checkpoints` |
| `jyt3136-000010.safetensors` | `models\loras` |
| `Blue Archive Animation Style.safetensors` | `models\loras` |
| `openpose_pre.safetensors` | `models\controlnet` |
| `RealESRGAN_x4plus_anime_6B.pth` | `models\upscale_models` |

旧安装中的 Z-Image UNET 如果已放在 `models\unet` 且加载节点可以识别，可以保持原位。

## 文本模型

示例默认使用本机 Ollama：

```powershell
ollama pull orcarouter/Qwen3.8-27B-Uncensored:q4_K_M
ollama serve
```

也可以在“文本模型：中文场景 → NoobAI 动态标签”节点中切换为 `openai_compatible`，然后填写：

- `api_base`：服务地址，例如 `https://example.com/v1`
- `model`：在线模型名称
- `api_key`：API Key，直接保存在当前 workflow 中，无需设置环境变量或重启 ComfyUI

分享 workflow 前请清空 `api_key`。

## Usage

### 1. 输入自然语言与人物标签

只需修改左侧输入节点的两项内容。

正面示例：

```text
简单描述：
两个人并排站在学校走廊，各占画面约一半，身穿校服和过膝袜，
双手抬到胸前做猫爪握拳姿势，闭嘴微笑，略带得意地看向镜头，
全身构图，轻微仰视

人物标签：
(momoi \(blue archive\):1.2), (midori \(blue archive\):1.2)
```

### 2. 第一次生成

设置：

- NoobAI 提示词开关：`始终跟随简单输入（变更时调用文本模型）`
- Z-Image 骨架开关：`生成并保存新骨架（运行 Z-Image）`

点击 Queue。工作流将依次完成：

```text
自然语言 → Z-Image 构图 → DWPose 骨架 → NoobAI 生成 → RealESRGAN 2×
```

NoobAI 的 seed 已连接 ComfyUI 原生 `PrimitiveInt` 节点，并设为 `randomize`，每次 Queue 都会使用新种子。

### 3. 复用骨架，只调整 NoobAI

构图满意后设置：

- NoobAI 提示词开关：`使用下方完整提示词（不调用模型）`
- Z-Image 骨架开关：`复用上次骨架（跳过 Z-Image）`

然后直接修改完整提示词并再次 Queue。此模式会跳过文本模型、Z-Image 和 DWPose，只重新运行 NoobAI 与超分。

需要新构图时，把两个开关切回第一次生成的设置即可。

## License

[MIT](LICENSE)
