import { useNavigate } from "react-router";
import { Button, Avatar, Popover } from "antd";
import { UserOutlined, LogoutOutlined } from "@ant-design/icons";
import { useAuthStore } from "../stores/auth-store";
import { logout } from "../api/auth";

/**
 * Shared top-bar for authenticated pages (workspace, dashboard).
 * Brand on the left, optional title + children, and user menu on the right.
 */
export function AppHeader({
  title,
  children,
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const clearUser = useAuthStore((s) => s.clearUser);

  const handleLogout = () => { logout().catch(() => {}); clearUser(); navigate("/"); };

  return (
    <header className="ns-app-header">
      {/* Left */}
      <div className="ns-app-header-left">
        <span className="ns-app-header-brand" onClick={() => navigate("/")}>
          NovelScript <span className="ns-app-header-sub">析幕</span>
        </span>
        {title && <span className="ns-app-header-title" title={title}>{title}</span>}
        {children}
      </div>

      {/* Right */}
      <div className="ns-app-header-right">
        {user ? (
          <Popover trigger="click" placement="bottomRight" overlayStyle={{ width: 220 }}
            content={
              <div className="ns-popover-wrap">
                <div className="ns-popover-field"><div className="ns-popover-label">用户名</div><div className="ns-popover-value ns-popover-value--strong">{user.username}</div></div>
                <div className="ns-popover-field"><div className="ns-popover-label">邮箱</div><div className="ns-popover-value">{user.email ?? "—"}</div></div>
                <div className="ns-popover-field--last"><div className="ns-popover-label">角色</div><div className="ns-popover-value">{user.role === "admin" ? "管理员" : "用户"}</div></div>
                <Button block danger size="small" icon={<LogoutOutlined />} onClick={handleLogout}>退出登录</Button>
              </div>
            }>
            <span className="ns-popover-user-trigger">
              <Avatar size="small" icon={<UserOutlined />} style={{ backgroundColor: "var(--color-accent-primary)" }} />
              {user.username}
            </span>
          </Popover>
        ) : (
          <Button type="primary" size="small" icon={<UserOutlined />} onClick={() => navigate("/login")}>登录</Button>
        )}
      </div>
    </header>
  );
}
