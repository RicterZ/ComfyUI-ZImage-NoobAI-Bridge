# ComfyUI Z-Image → NoobAI Bridge

一组 ComfyUI 自定义节点与示例工作流：让 Z-Image 理解自然语言并规划人物构图，只通过 DWPose/OpenPose 把骨架交给 NoobAI/Illustrious，从而由 NoobAI 独立决定角色、服装和画风。

> 示例工作流不包含模型文件。它使用 Z-Image、NoobAI/Illustrious、DWPose、OpenPose ControlNet 和两个可替换的风格 LoRA；请按下文准备对应模型。

## 快速安装

在 ComfyUI 的 `custom_nodes` 目录执行：

```powershell
git clone https://github.com/RicterZ/ComfyUI-ZImage-NoobAI-Bridge.git
```

另外通过 ComfyUI Manager 安装：

- `comfyui_controlnet_aux`：提供 DWPose。
- `ComfyUI_LayerStyle`：提供工作流中的显存释放节点。

重启 ComfyUI，然后打开：

```text
example_workflows/z-image-openpose-noobai-flat-2x.json
```

## 准备模型

示例工作流需要手动准备下面 8 个模型文件。路径均相对于 ComfyUI 根目录；例如安装在 `S:\ComfyUI` 时，`models\checkpoints` 表示 `S:\ComfyUI\models\checkpoints`。

| 阶段 | 必须使用的文件名 | 放置目录 | 工作流中的加载节点 |
| --- | --- | --- | --- |
| Z-Image | `z_image_turbo_fp8_e4m3fn.safetensors` | `models\diffusion_models` | `Z-Image Turbo FP8` |
| Z-Image | `qwen_3_4b.safetensors` | `models\text_encoders` | `Z-Image Qwen Text Encoder` |
| Z-Image | `ae.safetensors` | `models\vae` | `Z-Image VAE` |
| NoobAI | `zukiNewCuteILL_newV20.safetensors` | `models\checkpoints` | `NoobAI/Illustrious 底模` |
| NoobAI 风格 | `jyt3136-000010.safetensors` | `models\loras` | `NoobAI LoRA 1：JYT` |
| NoobAI 风格 | `Blue Archive Animation Style.safetensors` | `models\loras` | `NoobAI LoRA 2：BA Animation` |
| 姿势控制 | `openpose_pre.safetensors` | `models\controlnet` | `NoobAI OpenPose ControlNet` |
| 最终超分 | `RealESRGAN_x4plus_anime_6B.pth` | `models\upscale_models` | `动漫超分模型：RealESRGAN 4×` |

以 `S:\ComfyUI` 为例，最终目录应为：

```text
S:\ComfyUI\
└─ models\
   ├─ diffusion_models\
   │  └─ z_image_turbo_fp8_e4m3fn.safetensors
   ├─ text_encoders\
   │  └─ qwen_3_4b.safetensors
   ├─ vae\
   │  └─ ae.safetensors
   ├─ checkpoints\
   │  └─ zukiNewCuteILL_newV20.safetensors
   ├─ loras\
   │  ├─ jyt3136-000010.safetensors
   │  └─ Blue Archive Animation Style.safetensors
   ├─ controlnet\
   │  └─ openpose_pre.safetensors
   └─ upscale_models\
      └─ RealESRGAN_x4plus_anime_6B.pth
```

`comfyui_controlnet_aux` 会自行管理 DWPose 所需的检测文件，因此不在这份手动模型清单中。第一次运行 DWPose 时保持网络可用即可。

注意：

- 这里的 `qwen_3_4b.safetensors` 是 **Z-Image 的文本编码器**，不是负责“自然语言转 NoobAI 标签”的 Ollama 模型；两者不能互相替代。
- 旧版 ComfyUI 也可能把 Z-Image UNET 放在 `models\unet`。现有安装如果能够在加载节点中选到它，可以保持原位；新安装推荐使用 `models\diffusion_models`。
- 示例 JSON 按上表文件名保存。若文件被改名或放在子目录中，加载工作流后需要在相应 Loader 节点重新选择一次。
- 两个 LoRA 都属于 NoobAI 阶段；Z-Image 阶段不加载任何 LoRA。

## 配置自然语言转换

示例默认通过本机 Ollama 调用：

```powershell
ollama pull orcarouter/Qwen3.8-27B-Uncensored:q4_K_M
ollama serve
```

默认地址是 `http://127.0.0.1:11434`。专用的 NoobAI 动态标签节点会在请求前释放 ComfyUI 显存，并在请求结束后让 Ollama 卸载模型，减少第二次运行时的显存争用。

通用的“自然语言 → Illustrious 提示词”节点还支持 OpenAI-compatible API。API key 只从环境变量读取，不写入工作流 JSON。

## 生成新构图

1. 在左侧输入简单描述和明确的人物 Danbooru 标签。
2. 将“骨架开关”设为“生成并保存新骨架（运行 Z-Image）”。
3. 将提示词编辑节点设为“始终跟随简单输入”。
4. Queue 一次。工作流会依次执行：

```text
自然语言 → Z-Image 构图 → DWPose 骨架 → NoobAI 空 Latent 生成 → RealESRGAN 2×
```

NoobAI 从空 Latent、`denoise = 1.0` 开始，因此不会继承 Z-Image 的衣服、颜色或纹理。Z-Image 阶段不需要额外 LoRA。

## 复用骨架并微调 NoobAI

1. 骨架满意后，将“骨架开关”改为“复用上次骨架（跳过 Z-Image）”。
2. 将“Qwen 结果”改为“使用下方完整提示词（不调用模型）”。
3. 直接编辑完整提示词并反复 Queue。

复用模式使用懒输入阻断整个 Z-Image/DWPose 分支，而不是仅依赖 ComfyUI 的临时执行缓存。最后一次骨架保存为：

```text
ComfyUI/user/default/comfyui_nl_prompt_cache/last_openpose.png
```

要更换构图，只需把骨架开关切回“生成并保存新骨架”。

## 节点说明

| 节点 | 作用 |
| --- | --- |
| `ZImageNoobAIPromptBridge` | 从两项输入生成 Z-Image 构图描述，并原样转发人物标签 |
| `NoobAIDynamicPromptCompiler` | 把场景描述转换为动态 Danbooru 标签，再拼接人物与固定风格词 |
| `IllustriousNaturalLanguagePrompt` | 可配置的通用 Illustrious/NoobAI 自然语言转换节点 |
| `IllustriousPromptEditor` | 显示、编辑、锁定或持续同步完整提示词；手动模式会懒阻断 LLM |
| `ReusablePoseCache` | 保存最后一次 OpenPose 图，复用时懒阻断 Z-Image 与 DWPose |
| `WanVideoNaturalLanguagePrompt` | 把简短动作意图整理成 Wan2.2 图生视频提示词 |

## 常见问题

### 复用骨架时 Z-Image 仍然执行

确认工作流中没有任何 `SaveImage` 或 `PreviewImage` 直接连接在 Z-Image 分支上。独立输出节点会强制执行它的上游，绕过骨架缓存的懒阻断设计。

### 第一次复用骨架时报错

必须先用“生成并保存新骨架”成功运行一次。缓存文件不存在时，节点会明确拒绝复用。

### NoobAI 不遵循人物外观

确认人物标签是模型认识的精确 Danbooru 标签，并使用兼容 NoobAI/Illustrious 的 checkpoint 和 LoRA。OpenPose 只约束身体关键点，不负责角色身份。

### 风格被 ControlNet 压弱

示例把 OpenPose 强度设为 `0.8`，结束比例设为 `0.65`，让后 35% 采样过程留给 NoobAI 与风格 LoRA。必要时进一步降低结束比例，不要改成 RGB img2img。

## License

[MIT](LICENSE)
