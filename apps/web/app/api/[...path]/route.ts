import { type NextRequest } from "next/server";

// 运行时反向代理：浏览器只访问同源 /api/*，由本 Route Handler 在服务端
// 动态转发到内部 api 容器（每次请求读取 API_INTERNAL_URL，不在 build 时固化）。
export const dynamic = "force-dynamic";

function apiBase(): string {
  return process.env.API_INTERNAL_URL || "http://localhost:8000";
}

async function proxy(req: NextRequest, path: string[]): Promise<Response> {
  const target = `${apiBase()}/api/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("content-length"); // 让 fetch 按实际 body 重新计算

  const method = req.method.toUpperCase();
  const body =
    method === "GET" || method === "HEAD" ? undefined : await req.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(target, { method, headers, body, redirect: "manual" });
  } catch {
    return Response.json({ detail: "无法连接后端服务" }, { status: 502 });
  }

  const respHeaders = new Headers(upstream.headers);
  // 仅删除 hop-by-hop / 会被运行时重写的头。
  // 保留 content-length / content-range / accept-ranges：代理视频需要它们支持
  // HTTP Range（206 + 浏览器拖动进度条）。后端不对响应做 gzip，content-length 准确。
  respHeaders.delete("content-encoding");
  respHeaders.delete("transfer-encoding");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

type Ctx = { params: { path: string[] } };

export function GET(req: NextRequest, { params }: Ctx) {
  return proxy(req, params.path);
}
export function POST(req: NextRequest, { params }: Ctx) {
  return proxy(req, params.path);
}
export function PUT(req: NextRequest, { params }: Ctx) {
  return proxy(req, params.path);
}
export function PATCH(req: NextRequest, { params }: Ctx) {
  return proxy(req, params.path);
}
export function DELETE(req: NextRequest, { params }: Ctx) {
  return proxy(req, params.path);
}
