import { useNavigate } from "react-router";
import { Button, Dropdown, Tag, Avatar, Popover, message } from "antd";
import { ExportOutlined, ForkOutlined, HomeOutlined, UserOutlined, LogoutOutlined } from "@ant-design/icons";
import { useTaskStore } from "../../stores/task-store";
import { useScriptStore } from "../../stores/script-store";
import { useAuthStore } from "../../stores/auth-store";
import { exportScript, forkScript } from "../../api/scripts";
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
  const scriptId = useScriptStore((s) => s.scriptId);
  const scriptStatus = useScriptStore((s) => s.sourceType);
  const title = useScriptStore((s) => s.title);
  const status = useTaskStore((s) => s.status);

  const statusInfo = STATUS_MAP[status ?? ""] ?? { color: "default", label: "未知" };
  const user = useAuthStore((s) => s.user);
  const clearUser = useAuthStore((s) => s.clearUser);

  const handleExport = async (format: "yaml" | "json" | "fountain") => {
    if (!scriptId) return;
    const content = await exportScript(scriptId, format);
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `script.${format === "fountain" ? "fountain" : format}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFork = async () => {
    if (!scriptId) return;
    try {
      const res = await forkScript(scriptId);
      message.success(`已创建副本: ${res.title}`);
    } catch {
      message.error("创建副本失败");
    }
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
        {title && (
          <span className="ns-taskbar-title" title={title}>
            {title.slice(0, 20)}{title.length > 20 ? "…" : ""}
          </span>
        )}
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
        {scriptId && (
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
        {scriptId && (
          <Button icon={<ForkOutlined />} onClick={handleFork}>创建副本</Button>
        )}
      </div>
    </header>
  );
}
