import { Tabs } from "antd";
import { PictureOutlined, ShareAltOutlined, MessageOutlined } from "@ant-design/icons";
import { useUIStore, type RightTab } from "../../stores/ui-store";
import { ScriptPreview } from "./ScriptPreview";
import { KnowledgeGraph } from "./KnowledgeGraph";
import { AIChat } from "./AIChat";
import type { useTraceLinking } from "../../hooks/useTraceLinking";
import type { useScriptEditor } from "../../hooks/useScriptEditor";

interface Props {
  traceHook: ReturnType<typeof useTraceLinking>;
  editorHook: ReturnType<typeof useScriptEditor>;
}

const TABS: { key: RightTab; label: string; icon: React.ReactNode }[] = [
  { key: "preview", label: "预览", icon: <PictureOutlined /> },
  { key: "graph", label: "图谱", icon: <ShareAltOutlined /> },
  { key: "chat", label: "AI", icon: <MessageOutlined /> },
];

export function RightPanel({ traceHook, editorHook }: Props) {
  const activeTab = useUIStore((s) => s.activeTab);
  const setActiveTab = useUIStore((s) => s.setActiveTab);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", paddingLeft: 8, paddingRight: 8 }}>
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as RightTab)}
        items={TABS.map((tab) => ({
          key: tab.key,
          label: (
            <span>
              {tab.icon} {tab.label}
            </span>
          ),
          children: null,
        }))}
        size="small"
        style={{ marginBottom: 0 }}
        tabBarStyle={{ paddingLeft: 8 }}
      />
      <div style={{ flex: 1, overflow: "hidden" }}>
        <div style={{ display: activeTab === "preview" ? "block" : "none", height: "100%" }}>
          <ScriptPreview traceHook={traceHook} />
        </div>
        <div style={{ display: activeTab === "graph" ? "block" : "none", height: "100%" }}>
          <KnowledgeGraph />
        </div>
        <div style={{ display: activeTab === "chat" ? "block" : "none", height: "100%" }}>
          <AIChat editorHook={editorHook} />
        </div>
      </div>
    </div>
  );
}
