import { useState } from "react";
import { useNavigate } from "react-router";
import { Button, Form, Input, message, Tabs } from "antd";
import { UserOutlined, LockOutlined, MailOutlined } from "@ant-design/icons";
import { login, register } from "../api/auth";
import type { Route } from "./+types/login";

export function meta({}: Route.MetaArgs) {
  return [{ title: "登录 — NovelScript 析幕" }];
}

export default function LoginPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<"login" | "register">("login");
  const [submitting, setSubmitting] = useState(false);

  const handleLogin = async (values: { email: string; password: string }) => {
    setSubmitting(true);
    try {
      const res = await login(values.email, values.password);
      localStorage.setItem("auth_token", res.token);
      message.success("登录成功");
      navigate("/");
    } catch {
      message.error("邮箱或密码错误");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegister = async (values: {
    username: string;
    email: string;
    password: string;
    passwordConfirm: string;
  }) => {
    if (values.password !== values.passwordConfirm) {
      message.error("两次密码不一致");
      return;
    }
    setSubmitting(true);
    try {
      await register(values.username, values.email, values.password);
      message.success("注册成功，请登录");
      setActiveTab("login");
    } catch {
      message.error("注册失败，邮箱或用户名可能已被占用");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "var(--color-bg-canvas)",
      }}
    >
      <div
        style={{
          width: 400,
          padding: "40px 32px",
          backgroundColor: "var(--color-bg-elevated)",
          border: "1px solid var(--color-border-subtle)",
          borderRadius: 12,
        }}
      >
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <h1
            style={{
              fontSize: 28,
              fontWeight: 600,
              color: "var(--color-text-primary)",
              margin: 0,
            }}
          >
            NovelScript
          </h1>
          <p
            style={{
              color: "var(--color-text-secondary)",
              fontSize: 14,
              marginTop: 4,
            }}
          >
            析幕 — AI 驱动的剧本转换系统
          </p>
        </div>

        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as "login" | "register")}
          centered
          size="large"
          items={[
            {
              key: "login",
              label: "登录",
              children: (
                <Form
                  layout="vertical"
                  onFinish={handleLogin}
                  size="large"
                  style={{ marginTop: 8 }}
                >
                  <Form.Item
                    name="email"
                    rules={[
                      { required: true, message: "请输入邮箱" },
                      { type: "email", message: "邮箱格式不正确" },
                    ]}
                  >
                    <Input
                      prefix={<MailOutlined style={{ color: "var(--color-text-muted)" }} />}
                      placeholder="邮箱"
                    />
                  </Form.Item>
                  <Form.Item
                    name="password"
                    rules={[{ required: true, message: "请输入密码" }]}
                  >
                    <Input.Password
                      prefix={<LockOutlined style={{ color: "var(--color-text-muted)" }} />}
                      placeholder="密码"
                    />
                  </Form.Item>
                  <Form.Item>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={submitting}
                      block
                    >
                      登录
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            {
              key: "register",
              label: "注册",
              children: (
                <Form
                  layout="vertical"
                  onFinish={handleRegister}
                  size="large"
                  style={{ marginTop: 8 }}
                >
                  <Form.Item
                    name="username"
                    rules={[
                      { required: true, message: "请输入用户名" },
                      { min: 2, message: "用户名至少 2 个字符" },
                    ]}
                  >
                    <Input
                      prefix={<UserOutlined style={{ color: "var(--color-text-muted)" }} />}
                      placeholder="用户名"
                    />
                  </Form.Item>
                  <Form.Item
                    name="email"
                    rules={[
                      { required: true, message: "请输入邮箱" },
                      { type: "email", message: "邮箱格式不正确" },
                    ]}
                  >
                    <Input
                      prefix={<MailOutlined style={{ color: "var(--color-text-muted)" }} />}
                      placeholder="邮箱"
                    />
                  </Form.Item>
                  <Form.Item
                    name="password"
                    rules={[{ required: true, min: 6, message: "密码至少 6 位" }]}
                  >
                    <Input.Password
                      prefix={<LockOutlined style={{ color: "var(--color-text-muted)" }} />}
                      placeholder="密码"
                    />
                  </Form.Item>
                  <Form.Item
                    name="passwordConfirm"
                    rules={[{ required: true, message: "请确认密码" }]}
                  >
                    <Input.Password
                      prefix={<LockOutlined style={{ color: "var(--color-text-muted)" }} />}
                      placeholder="确认密码"
                    />
                  </Form.Item>
                  <Form.Item>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={submitting}
                      block
                    >
                      注册
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
          ]}
        />

        {/* Skip for now */}
        <div style={{ textAlign: "center", marginTop: -8 }}>
          <Button
            type="link"
            size="small"
            style={{ color: "var(--color-text-muted)" }}
            onClick={() => navigate("/")}
          >
            跳过，直接进入
          </Button>
        </div>
      </div>
    </div>
  );
}
