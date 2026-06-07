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
    <div className="ns-panel">
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
      <div className="ns-panel-tab-content">
        <div className="ns-panel-tab-pane" style={{ display: activeTab === "preview" ? "block" : "none" }}>
          <ScriptPreview traceHook={traceHook} />
        </div>
        <div className="ns-panel-tab-pane" style={{ display: activeTab === "graph" ? "block" : "none" }}>
          <KnowledgeGraph />
        </div>
        <div className="ns-panel-tab-pane" style={{ display: activeTab === "chat" ? "block" : "none" }}>
          <AIChat editorHook={editorHook} />
        </div>
      </div>
    </div>
  );
}
