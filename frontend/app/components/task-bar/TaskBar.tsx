import { useNavigate } from "react-router";
import { Button, Dropdown, Tag } from "antd";
import { ExportOutlined, HomeOutlined } from "@ant-design/icons";
import { useTaskStore } from "../../stores/task-store";
import { exportScript } from "../../api/scripts";

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending:       { color: "default", label: "待开始" },
  preprocessing: { color: "processing", label: "预处理中" },
  converting:    { color: "processing", label: "转换中" },
  completed:     { color: "success", label: "已完成" },
  failed:        { color: "error", label: "失败" },
};

export function TaskBar() {
  const navigate = useNavigate();
  const taskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);

  const statusInfo = STATUS_MAP[status ?? ""] ?? { color: "default", label: "未知" };

  const handleExport = async (format: "yaml" | "json" | "fountain") => {
    if (!taskId) return;
    const content = await exportScript(taskId, format);
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `script.${format === "fountain" ? "fountain" : format}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <header
      style={{
        height: 48,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
        backgroundColor: "var(--color-bg-surface)",
        borderBottom: "1px solid var(--color-border-subtle)",
        flexShrink: 0,
      }}
    >
      {/* Left */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Button type="text" icon={<HomeOutlined />} onClick={() => navigate("/")}>
          <span style={{ fontWeight: 600, color: "var(--color-text-primary)" }}>
            NovelScript
          </span>
        </Button>
        {status && <Tag color={statusInfo.color}>{statusInfo.label}</Tag>}
      </div>

      {/* Right */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {taskId && (
          <Dropdown
            menu={{
              items: [
                { key: "yaml", label: "导出 YAML" },
                { key: "json", label: "导出 JSON" },
                { key: "fountain", label: "导出 Fountain" },
              ],
              onClick: ({ key }) => handleExport(key as "yaml" | "json" | "fountain"),
            }}
          >
            <Button icon={<ExportOutlined />}>导出</Button>
          </Dropdown>
        )}
      </div>
    </header>
  );
}
