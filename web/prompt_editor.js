import { app } from "../../scripts/app.js";

const NODE_NAME = "IllustriousPromptEditor";
const MANUAL_MODE = "使用下方完整提示词（不调用模型）";

app.registerExtension({
    name: "comfyui_nl_prompt.prompt_editor",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const originalOnExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            originalOnExecuted?.apply(this, arguments);

            const selected = message?.selected_prompt?.[0];
            if (typeof selected !== "string" || selected.length === 0) return;

            const promptWidget = this.widgets?.find((widget) => widget.name === "full_prompt");
            if (promptWidget) {
                promptWidget.value = selected;
                promptWidget.callback?.(selected);
            }

            if (message?.lock_after_run?.[0]) {
                const modeWidget = this.widgets?.find((widget) => widget.name === "source_mode");
                if (modeWidget) {
                    modeWidget.value = MANUAL_MODE;
                    modeWidget.callback?.(MANUAL_MODE);
                }
            }

            this.setDirtyCanvas?.(true, true);
            app.graph?.setDirtyCanvas?.(true, true);
        };
    },
});
