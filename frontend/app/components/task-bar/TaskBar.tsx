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
    <header className="ns-taskbar">
      {/* Left */}
      <div className="ns-taskbar-left">
        <Button type="text" icon={<HomeOutlined />} onClick={() => navigate("/")}>
          <span className="ns-taskbar-brand">
            NovelScript
          </span>
        </Button>
        {isLoading && <Tag color="processing">加载中...</Tag>}
        {!isLoading && status && <Tag color={statusInfo.color}>{statusInfo.label}</Tag>}
      </div>

      {/* Right */}
      <div className="ns-taskbar-right">
        {user ? (
          <Popover
            trigger="click"
            placement="bottomRight"
            overlayStyle={{ width: 220 }}
            content={
              <div className="ns-popover-wrap">
                <div className="ns-popover-field">
                  <div className="ns-popover-label">用户名</div>
                  <div className="ns-popover-value ns-popover-value--strong">{user.username}</div>
                </div>
                <div className="ns-popover-field">
                  <div className="ns-popover-label">邮箱</div>
                  <div className="ns-popover-value">{user.email ?? "—"}</div>
                </div>
                <div className="ns-popover-field--last">
                  <div className="ns-popover-label">角色</div>
                  <div className="ns-popover-value">{user.role === "admin" ? "管理员" : "用户"}</div>
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
            <span className="ns-popover-user-trigger">
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
