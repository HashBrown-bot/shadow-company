import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Shadow · 仿真测试工作台",
  description: "本地退款与审批工程控制台 · E8",
};

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
