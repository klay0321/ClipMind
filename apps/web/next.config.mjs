/** @type {import('next').NextConfig} */
// 浏览器只访问同源 /api/*；由运行时 Route Handler（app/api/[...path]/route.ts）
// 在服务端动态转发到内部 api 容器。不用 rewrites，避免 build 时把目标 URL 固化。
const nextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
