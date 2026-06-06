import { useNavigate } from "react-router";
import { Button, Dropdown, Tag, Avatar, Popover } from "antd";
import { ExportOutlined, HomeOutlined, UserOutlined, LogoutOutlined } from "@ant-design/icons";
import { useTaskStore } from "../../stores/task-store";
import { useAuthStore } from "../../stores/auth-store";
import { exportScript } from "../../api/scripts";
import { logout } from "../../api/auth";

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending:       { color: "default", label: "待开始" },
  preprocessing: { color: "processing", label: "预处理中" },
  converting:    { color: "processing", label: "转换中" },
  completed:     { color: "success", label: "已完成" },
  failed:        { color: "error", label: "失败" },
};

export function TaskBar({ loading: isLoading }: { loading?: boolean }) {
  const navigate = useNavigate();
  const taskId = useTaskStore((s) => s.taskId);
  const status = useTaskStore((s) => s.status);

  const statusInfo = STATUS_MAP[status ?? ""] ?? { color: "default", label: "未知" };
  const user = useAuthStore((s) => s.user);
  const clearUser = useAuthStore((s) => s.clearUser);

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
        {isLoading && <Tag color="processing">加载中...</Tag>}
        {!isLoading && status && <Tag color={statusInfo.color}>{statusInfo.label}</Tag>}
      </div>

      {/* Right */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {user ? (
          <Popover
            trigger="click"
            placement="bottomRight"
            overlayStyle={{ width: 220 }}
            content={
              <div style={{ fontSize: 13 }}>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: "var(--color-text-muted)", fontSize: 11, marginBottom: 2 }}>用户名</div>
                  <div style={{ color: "var(--color-text-primary)", fontWeight: 600 }}>{user.username}</div>
                </div>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ color: "var(--color-text-muted)", fontSize: 11, marginBottom: 2 }}>邮箱</div>
                  <div style={{ color: "var(--color-text-primary)" }}>{user.email ?? "—"}</div>
                </div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ color: "var(--color-text-muted)", fontSize: 11, marginBottom: 2 }}>角色</div>
                  <div style={{ color: "var(--color-text-primary)" }}>{user.role === "admin" ? "管理员" : "用户"}</div>
                </div>
                <Button
                  block
                  danger
                  size="small"
                  icon={<LogoutOutlined />}
                  onClick={() => { logout().catch(() => {}); clearUser(); navigate("/login"); }}
                >
                  退出登录
                </Button>
              </div>
            }
          >
            <span
              style={{
                fontSize: 13,
                color: "var(--color-text-secondary)",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <Avatar
                size="small"
                icon={<UserOutlined />}
                style={{ backgroundColor: "var(--color-accent-primary)" }}
              />
              {user.username}
            </span>
          </Popover>
        ) : (
          <Button type="link" size="small" onClick={() => navigate("/login")}>
            登录
          </Button>
        )}
        {taskId && status === "completed" && (
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
