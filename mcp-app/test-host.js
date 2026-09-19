import {
  AppBridge,
  PostMessageTransport,
} from "@modelcontextprotocol/ext-apps/app-bridge";

window.mountOuttake = async (html, result = null, options = {}) => {
  if (window.outtakeBridge) await window.outtakeBridge.close();
  const frame = document.createElement("iframe");
  frame.id = "app";
  frame.sandbox = "allow-scripts allow-downloads";
  frame.style = "width:100%;height:1250px;border:0";
  document.body.replaceChildren(frame);

  const capabilities = {
    serverTools: {},
    updateModelContext: {},
  };
  if (options.resources !== false) capabilities.serverResources = {};
  const bridge = new AppBridge(
    null,
    { name: "Independent Outtake AppBridge host", version: "1.0.0" },
    capabilities,
    {
      hostContext: {
        ...(options.theme ? { theme: options.theme } : {}),
        displayMode: options.displayMode || "inline",
      },
    },
  );
  bridge.oncalltool = (args) => window.hostCall(args);
  bridge.onreadresource = (args) => window.hostRead(args);
  bridge.onupdatemodelcontext = async (args) => {
    window.savedContext = args;
    return {};
  };
  window.setOuttakeHostContext = (context) => bridge.setHostContext(context);
  bridge.oninitialized = async () => {
    const reviewId =
      result?.structuredContent?.review_id ||
      result?.review_id ||
      options.reviewId ||
      undefined;
    if (reviewId) await bridge.sendToolInput({ arguments: { review_id: reviewId } });
    if (result) await bridge.sendToolResult(result);
  };
  await bridge.connect(
    new PostMessageTransport(frame.contentWindow, frame.contentWindow),
  );
  frame.srcdoc = html;
  window.outtakeBridge = bridge;
};